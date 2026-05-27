"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared runner for the two corpus stress-embed scripts in this folder.
Both scripts spawn N worker coroutines that each upload one file and
schedule an embed job. Each worker uses a unique Client header value so
the per-client lock in /v1/embed does not serialize them.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "corpus"
TERMINAL_STATUSES = {"succeeded", "failed"}


@dataclass
class WorkerResult:
    worker_id: int
    client_id: str
    filename: str
    alias: str
    description: str | None = None
    status: str = "pending"
    job_id: str | None = None
    upload_seconds: float = 0.0
    schedule_seconds: float = 0.0
    poll_wait_seconds: float = 0.0
    total_seconds: float = 0.0
    error: str | None = None


@dataclass
class RunConfig:
    base_url: str
    api_key: str
    embedding_provider: str | None
    embedding_model: str | None
    distance_strategy: str
    index_type: str
    chunk_size: int
    chunk_overlap: int
    parsing_mode: str
    poll_interval: float
    timeout: float
    rate_limit: int
    client_prefix: str


def build_argparser(description: str | None) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--api-key", required=True, help="X-API-Key value (server's AIO_API_KEY)")
    p.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS))
    p.add_argument("--workers", type=int, default=100)
    p.add_argument(
        "--embedding-provider",
        default=None,
        help="Optional. Omit to auto-discover from GET /v1/models (one enabled embed model required).",
    )
    p.add_argument("--embedding-model", default=None)
    p.add_argument("--distance-strategy", default="COSINE")
    p.add_argument("--index-type", default="HNSW", choices=["HNSW", "IVF", "HYB"])
    p.add_argument("--chunk-size", type=int, default=1024)
    p.add_argument("--chunk-overlap", type=int, default=128)
    p.add_argument("--parsing-mode", default="fast", choices=["fast", "deep"])
    p.add_argument("--poll-interval", type=float, default=2.0)
    p.add_argument("--timeout", type=float, default=900.0, help="Per-job terminal-state timeout, seconds")
    p.add_argument("--rate-limit", type=int, default=0)
    p.add_argument("--client-prefix", default="racing-w")
    return p


def pick_files(corpus_dir: Path, workers: int) -> list[Path]:
    files = sorted(f for f in corpus_dir.iterdir() if f.is_file() and not f.name.startswith("."))
    if not files:
        raise SystemExit(f"No corpus files found under {corpus_dir}")
    return [files[i % len(files)] for i in range(workers)]


async def _post_upload(
    client: httpx.AsyncClient, base_url: str, headers: dict, file_path: Path
) -> list[str]:
    with file_path.open("rb") as fh:
        content = fh.read()
    files = {"files": (file_path.name, content, "application/octet-stream")}
    resp = await client.post(f"{base_url}/v1/embed/local/store", headers=headers, files=files)
    resp.raise_for_status()
    return resp.json()


async def _post_schedule(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict,
    body: dict,
    rate_limit: int,
) -> dict:
    resp = await client.post(
        f"{base_url}/v1/embed/",
        headers=headers,
        params={"rate_limit": rate_limit} if rate_limit else None,
        json=body,
    )
    resp.raise_for_status()
    return resp.json()


async def _poll(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict,
    job_id: str,
    interval: float,
    timeout: float,
) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        resp = await client.get(f"{base_url}/v1/embed/jobs/{job_id}", headers=headers)
        # 503 is the documented transient-CORE retry signal; do not abort.
        if resp.status_code != 503:
            resp.raise_for_status()
            info = resp.json()
            if info.get("status") in TERMINAL_STATUSES:
                return info
        if time.monotonic() > deadline:
            raise TimeoutError(f"job {job_id} did not reach terminal state in {timeout}s")
        await asyncio.sleep(interval)


async def _run_worker(
    client: httpx.AsyncClient,
    cfg: RunConfig,
    result: WorkerResult,
    file_path: Path,
    barrier: asyncio.Barrier,
) -> None:
    headers = {"X-API-Key": cfg.api_key, "Client": result.client_id}
    body = {
        "alias": result.alias,
        "embedding_model": {"provider": cfg.embedding_provider, "id": cfg.embedding_model},
        "chunk_size": cfg.chunk_size,
        "chunk_overlap": cfg.chunk_overlap,
        "distance_strategy": cfg.distance_strategy,
        "index_type": cfg.index_type,
        "parsing_mode": cfg.parsing_mode,
    }
    if result.description:
        body["description"] = result.description
    try:
        await barrier.wait()
        wall_start = time.monotonic()

        t0 = time.monotonic()
        await _post_upload(client, cfg.base_url, headers, file_path)
        result.upload_seconds = time.monotonic() - t0

        t0 = time.monotonic()
        accepted = await _post_schedule(client, cfg.base_url, headers, body, cfg.rate_limit)
        result.schedule_seconds = time.monotonic() - t0
        job_id = accepted.get("job_id")
        if not isinstance(job_id, str):
            raise ValueError("schedule response did not include a string job_id")
        result.job_id = job_id

        t0 = time.monotonic()
        info = await _poll(
            client, cfg.base_url, headers, job_id, cfg.poll_interval, cfg.timeout
        )
        result.poll_wait_seconds = time.monotonic() - t0
        result.total_seconds = time.monotonic() - wall_start

        result.status = info.get("status", "unknown")
        if result.status == "failed":
            result.error = info.get("error") or "(no error message)"
    except httpx.HTTPStatusError as ex:
        result.status = "failed"
        result.error = f"HTTP {ex.response.status_code}: {ex.response.text[:300]}"
    except Exception as ex:  # noqa: BLE001
        result.status = "failed"
        result.error = f"{type(ex).__name__}: {ex}"


def _summary(values: list[float]) -> str:
    if not values:
        return "n/a"
    vals = sorted(values)
    n = len(vals)
    p50 = vals[n // 2]
    p95 = vals[min(n - 1, int(n * 0.95))]
    return f"min={min(vals):.2f}s p50={p50:.2f}s p95={p95:.2f}s max={max(vals):.2f}s"


def _print_report(results: list[WorkerResult], wall_seconds: float) -> int:
    succeeded = [r for r in results if r.status == "succeeded"]
    failed = [r for r in results if r.status != "succeeded"]
    print()
    print(f"Wall clock:  {wall_seconds:.2f}s across {len(results)} workers")
    print(f"Succeeded:   {len(succeeded)}")
    print(f"Failed:      {len(failed)}")
    print(f"  upload     {_summary([r.upload_seconds for r in succeeded])}")
    print(f"  schedule   {_summary([r.schedule_seconds for r in succeeded])}")
    print(f"  poll_wait  {_summary([r.poll_wait_seconds for r in succeeded])}")
    print(f"  total      {_summary([r.total_seconds for r in succeeded])}")
    if failed:
        print()
        print("Failures:")
        for r in failed:
            print(f"  worker={r.worker_id:>3} client={r.client_id} file={r.filename} alias={r.alias}")
            print(f"    -> {r.error}")
    return 0 if not failed else 1


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


async def _run(cfg: RunConfig, results: list[WorkerResult], files: list[Path]) -> int:
    n = len(results)
    limits = httpx.Limits(max_connections=n * 2 + 10, max_keepalive_connections=n + 10)
    timeout = httpx.Timeout(60.0, connect=30.0)
    barrier = asyncio.Barrier(n)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        if not cfg.embedding_provider or not cfg.embedding_model:
            cfg.embedding_provider, cfg.embedding_model = await _discover_embedding_model(
                client, cfg.base_url, cfg.api_key
            )
            print(f"Discovered embedding model: {cfg.embedding_provider}/{cfg.embedding_model}")
        wall_start = time.monotonic()
        await asyncio.gather(
            *(_run_worker(client, cfg, r, f, barrier) for r, f in zip(results, files)),
        )
        wall = time.monotonic() - wall_start
    return _print_report(results, wall)


def cfg_from_args(args: argparse.Namespace) -> RunConfig:
    return RunConfig(
        base_url=args.base_url.rstrip("/"),
        api_key=args.api_key,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        distance_strategy=args.distance_strategy,
        index_type=args.index_type,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        parsing_mode=args.parsing_mode,
        poll_interval=args.poll_interval,
        timeout=args.timeout,
        rate_limit=args.rate_limit,
        client_prefix=args.client_prefix,
    )


def execute(cfg: RunConfig, results: list[WorkerResult], files: list[Path]) -> int:
    return asyncio.run(_run(cfg, results, files))
