"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared async runner for chat-side stress scripts in this folder. Each
worker is a simulated demo participant with a unique ``Client`` header
(so per-client settings, history, and session caches stay isolated) and
walks through a sequence of demo prompts via /v1/chat/completions.

The flow for a single worker is:

    PATCH  /v1/chat/history   (optional reset for a clean run)
    PUT    /v1/settings       (set tools_enabled + vector_search alias for this step)
    POST   /v1/chat/completions  ... repeated per question in the step
    PUT    /v1/settings       (toggle tools for the next step)
    POST   /v1/chat/completions  ...

The script does NOT embed documents — the vector store is assumed to
already exist (see embed_per_document_table.py / embed_same_table.py).
It only exercises the chat path.

NOTE: the server defaults to ``max_clients=64`` (see ``AIO_MAX_CLIENTS``).
For a 100-worker run, raise that on the server first, otherwise older
clients will be evicted mid-run and lose their history.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class QuestionResult:
    step: str
    question: str
    status: str = "pending"          # "ok" | "failed"
    seconds: float = 0.0
    chars: int = 0
    route: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error: Optional[str] = None


@dataclass
class WorkerResult:
    worker_id: int
    client_id: str
    driver_n: int
    driver_m: int
    questions: list[QuestionResult] = field(default_factory=list)
    setup_seconds: float = 0.0
    total_seconds: float = 0.0
    fatal_error: Optional[str] = None


@dataclass
class StepPlan:
    """A demo step the worker should run end-to-end.

    ``tools_enabled`` is the exact list passed to PUT /v1/settings, e.g.
    ``["NL2SQL"]`` or ``["Vector Search", "NL2SQL"]`` or ``[]``.
    ``vs_alias`` is the worker-specific vector_search.alias to set when
    Vector Search is in ``tools_enabled``; ignored otherwise.
    """

    name: str
    tools_enabled: list[str]
    questions: list[str]
    vs_alias: Optional[str] = None


@dataclass
class RunConfig:
    base_url: str
    api_key: str
    workers: int
    client_prefix: str
    database_alias: str
    embedding_provider: Optional[str]
    embedding_model: Optional[str]
    request_timeout: float
    poll_interval: float
    reset_history: bool
    stagger_seconds: float


# ---------------------------------------------------------------------------
# Argparser
# ---------------------------------------------------------------------------


def build_argparser(description: str | None) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--api-key", required=True, help="X-API-Key value (server's AIO_API_KEY)")
    p.add_argument("--workers", type=int, default=100)
    p.add_argument("--client-prefix", default="racing-chat-c")
    p.add_argument(
        "--database-alias",
        default="CORE",
        help="DatabaseSettings.alias to assign to each client for NL2SQL steps.",
    )
    p.add_argument(
        "--embedding-provider",
        default=None,
        help="Optional. Omit to auto-discover from GET /v1/models (one enabled embed model required).",
    )
    p.add_argument("--embedding-model", default=None)
    p.add_argument(
        "--request-timeout",
        type=float,
        default=180.0,
        help="Per-request HTTP timeout (combined-mode answers can run long).",
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=0.0,
        help="Reserved for parity with embed runner; unused on chat path.",
    )
    p.add_argument(
        "--reset-history",
        action="store_true",
        help="PATCH /v1/chat/history at worker start so stale state from a prior run is wiped.",
    )
    p.add_argument(
        "--stagger-seconds",
        type=float,
        default=0.0,
        help="Stagger worker starts (s). 0 = thundering herd, all start together.",
    )
    return p


def cfg_from_args(args: argparse.Namespace) -> RunConfig:
    return RunConfig(
        base_url=args.base_url.rstrip("/"),
        api_key=args.api_key,
        workers=args.workers,
        client_prefix=args.client_prefix,
        database_alias=args.database_alias,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        request_timeout=args.request_timeout,
        poll_interval=args.poll_interval,
        reset_history=args.reset_history,
        stagger_seconds=args.stagger_seconds,
    )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _discover_embedding_model(
    client: httpx.AsyncClient, base_url: str, api_key: str
) -> tuple[str, str]:
    resp = await client.get(
        f"{base_url}/v1/models",
        headers={"X-API-Key": api_key},
    )
    resp.raise_for_status()
    embeds = [
        m for m in resp.json()
        if m.get("type") == "embed" and m.get("enabled") and m.get("provider") and m.get("id")
    ]
    if not embeds:
        raise SystemExit(
            "No enabled embedding model found on server. "
            "Configure one in Configuration -> Models, or pass "
            "--embedding-provider / --embedding-model explicitly."
        )
    if len(embeds) > 1:
        listing = ", ".join(f"{m['provider']}/{m['id']}" for m in embeds)
        raise SystemExit(
            f"Multiple enabled embedding models found ({listing}). "
            "Pass --embedding-provider / --embedding-model to pick one."
        )
    return embeds[0]["provider"], embeds[0]["id"]


async def _put_settings(
    client: httpx.AsyncClient,
    cfg: RunConfig,
    client_id: str,
    tools_enabled: list[str],
    vs_alias: Optional[str],
) -> None:
    body: dict = {
        "tools_enabled": tools_enabled,
        "database": {"alias": cfg.database_alias},
    }
    if "Vector Search" in tools_enabled:
        body["vector_search"] = {
            "provider": cfg.embedding_provider,
            "id": cfg.embedding_model,
            "alias": vs_alias,
        }
    resp = await client.put(
        f"{cfg.base_url}/v1/settings",
        headers={"X-API-Key": cfg.api_key},
        params={"client": client_id},
        json=body,
    )
    resp.raise_for_status()


async def _patch_history(
    client: httpx.AsyncClient, cfg: RunConfig, client_id: str
) -> None:
    resp = await client.patch(
        f"{cfg.base_url}/v1/chat/history",
        headers={"X-API-Key": cfg.api_key, "Client": client_id},
    )
    resp.raise_for_status()


async def _post_chat(
    client: httpx.AsyncClient,
    cfg: RunConfig,
    client_id: str,
    question: str,
) -> dict:
    resp = await client.post(
        f"{cfg.base_url}/v1/chat/completions",
        headers={"X-API-Key": cfg.api_key, "Client": client_id},
        json={"messages": [{"role": "user", "content": question}]},
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


async def _run_worker(
    client: httpx.AsyncClient,
    cfg: RunConfig,
    result: WorkerResult,
    steps: list[StepPlan],
    barrier: asyncio.Barrier,
) -> None:
    reached_barrier = False
    try:
        t_setup_start = time.monotonic()
        if cfg.reset_history:
            await _patch_history(client, cfg, result.client_id)
        result.setup_seconds = time.monotonic() - t_setup_start

        await barrier.wait()
        reached_barrier = True
        # Stagger AFTER the barrier so the ramp-up actually spreads chat
        # traffic: the barrier aligns t=0 for every worker, then each one
        # waits its proportional delay before issuing its first request.
        # Sleeping before the barrier only delays the slowest worker —
        # once it arrives, everyone unblocks simultaneously.
        if cfg.stagger_seconds > 0:
            await asyncio.sleep(cfg.stagger_seconds * result.worker_id)
        wall_start = time.monotonic()

        for step in steps:
            # Toggle tools / vector store target for this step
            await _put_settings(
                client,
                cfg,
                result.client_id,
                step.tools_enabled,
                step.vs_alias,
            )
            for question in step.questions:
                qr = QuestionResult(step=step.name, question=question)
                t0 = time.monotonic()
                try:
                    info = await _post_chat(client, cfg, result.client_id, question)
                    qr.seconds = time.monotonic() - t0
                    qr.status = "ok"
                    content = info.get("content") or ""
                    qr.chars = len(content) if isinstance(content, str) else 0
                    qr.route = info.get("route")
                    tu = info.get("token_usage") or {}
                    qr.prompt_tokens = int(tu.get("prompt_tokens") or 0)
                    qr.completion_tokens = int(tu.get("completion_tokens") or 0)
                    qr.total_tokens = int(tu.get("total_tokens") or 0)
                except httpx.HTTPStatusError as ex:
                    qr.seconds = time.monotonic() - t0
                    qr.status = "failed"
                    qr.error = f"HTTP {ex.response.status_code}: {ex.response.text[:300]}"
                except Exception as ex:  # noqa: BLE001
                    qr.seconds = time.monotonic() - t0
                    qr.status = "failed"
                    qr.error = f"{type(ex).__name__}: {ex}"
                result.questions.append(qr)

        result.total_seconds = time.monotonic() - wall_start
    except httpx.HTTPStatusError as ex:
        result.fatal_error = f"setup HTTP {ex.response.status_code}: {ex.response.text[:300]}"
    except Exception as ex:  # noqa: BLE001
        result.fatal_error = f"setup {type(ex).__name__}: {ex}"
    finally:
        # Only "fill in" for the startup barrier if we failed before reaching
        # it. Calling wait() again here on a successful worker would consume
        # a second round on the same barrier, which deadlocks the run when a
        # peer worker already exited via this same fallback path.
        if not reached_barrier and not barrier.broken:
            with contextlib.suppress(asyncio.BrokenBarrierError, RuntimeError):
                await barrier.wait()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _summary(values: list[float]) -> str:
    if not values:
        return "n/a"
    vals = sorted(values)
    n = len(vals)
    p50 = vals[n // 2]
    p95 = vals[min(n - 1, int(n * 0.95))]
    return f"min={min(vals):.2f}s p50={p50:.2f}s p95={p95:.2f}s max={max(vals):.2f}s"


def _print_report(results: list[WorkerResult], wall_seconds: float) -> int:
    all_qs = [q for r in results for q in r.questions]
    ok = [q for q in all_qs if q.status == "ok"]
    failed = [q for q in all_qs if q.status != "ok"]
    fatal = [r for r in results if r.fatal_error]

    print()
    print(f"Wall clock:    {wall_seconds:.2f}s across {len(results)} workers")
    print(f"Questions:     {len(all_qs)} (ok={len(ok)} failed={len(failed)})")
    print(f"Fatal workers: {len(fatal)}")

    by_step: dict[str, list[QuestionResult]] = {}
    for q in all_qs:
        by_step.setdefault(q.step, []).append(q)

    for step, qs in by_step.items():
        ok_qs = [q for q in qs if q.status == "ok"]
        fail_qs = [q for q in qs if q.status != "ok"]
        latencies = [q.seconds for q in ok_qs]
        chars = sum(q.chars for q in ok_qs)
        toks = sum(q.total_tokens for q in ok_qs)
        print()
        print(f"[{step}]  ok={len(ok_qs)} failed={len(fail_qs)} chars={chars} tokens={toks}")
        print(f"  latency  {_summary(latencies)}")

    if fatal:
        print()
        print("Worker setup failures:")
        for r in fatal:
            print(f"  worker={r.worker_id:>3} client={r.client_id}")
            print(f"    -> {r.fatal_error}")

    if failed:
        print()
        print(f"Question failures (showing first 20 of {len(failed)}):")
        for q in failed[:20]:
            print(f"  [{q.step}] {q.question[:80]}")
            print(f"    -> {q.error}")

    return 0 if not failed and not fatal else 1


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


# Callable that builds per-worker step plans given the worker's driver number,
# its partner driver number, and an alias-builder for the vector store.
StepBuilder = Callable[[int, int, Callable[[int], str]], list[StepPlan]]


async def _run(
    cfg: RunConfig,
    results: list[WorkerResult],
    plan_builder: StepBuilder,
    vs_alias_for: Callable[[int], str],
) -> int:
    n = len(results)
    limits = httpx.Limits(max_connections=n * 2 + 10, max_keepalive_connections=n + 10)
    timeout = httpx.Timeout(cfg.request_timeout, connect=30.0)
    barrier = asyncio.Barrier(n)
    # Vector Search is the only step type that needs an embedding model, so
    # skip discovery (and its 0-or-many guardrails) when no selected step
    # enables it — e.g. an NL2SQL-only or LLM-only run.
    sample_plans = plan_builder(results[0].driver_n, results[0].driver_m, vs_alias_for)
    needs_embeddings = any("Vector Search" in s.tools_enabled for s in sample_plans)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        if needs_embeddings and (not cfg.embedding_provider or not cfg.embedding_model):
            cfg.embedding_provider, cfg.embedding_model = await _discover_embedding_model(
                client, cfg.base_url, cfg.api_key
            )
            print(
                f"Discovered embedding model: {cfg.embedding_provider}/{cfg.embedding_model}"
            )
        wall_start = time.monotonic()
        await asyncio.gather(
            *(
                _run_worker(
                    client,
                    cfg,
                    r,
                    plan_builder(r.driver_n, r.driver_m, vs_alias_for),
                    barrier,
                )
                for r in results
            ),
        )
        wall = time.monotonic() - wall_start
    return _print_report(results, wall)


def execute(
    cfg: RunConfig,
    results: list[WorkerResult],
    plan_builder: StepBuilder,
    vs_alias_for: Callable[[int], str],
) -> int:
    return asyncio.run(_run(cfg, results, plan_builder, vs_alias_for))
