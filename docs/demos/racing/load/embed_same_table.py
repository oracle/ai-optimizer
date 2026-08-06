"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Embed the racing corpus into a SINGLE shared vector store table.

The server names the target vector_store table — and its ``<target>_TMP``
staging table — deterministically from the alias plus the embedding
parameters, so two concurrent embed jobs against the same alias would
race on DROP/CREATE/MERGE of the same ``_TMP`` table. This script
avoids that contention by uploading every corpus file from a single
client in one POST and scheduling exactly one embed job: the server
then claims the whole staged batch under the per-client lock and runs
the parse/chunk/embed/MERGE pipeline once.

For concurrent embed stress with isolated targets (per-driver tables),
use ``embed_per_document_table.py``.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _embed_common import (  # noqa: E402
    _discover_embedding_model,
    _poll,
    _post_schedule,
    build_argparser,
    cfg_from_args,
)


async def _post_upload_many(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    paths: list[Path],
) -> None:
    """Stage every corpus file under a single client in one multipart POST."""
    files = [
        ("files", (p.name, p.read_bytes(), "application/octet-stream"))
        for p in paths
    ]
    resp = await client.post(
        f"{base_url}/v1/embed/local/store", headers=headers, files=files
    )
    resp.raise_for_status()


async def _run(args: Any) -> int:
    cfg = cfg_from_args(args)
    corpus_dir = Path(args.corpus_dir)
    paths = sorted(
        p for p in corpus_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    if not paths:
        raise SystemExit(f"No corpus files found under {corpus_dir}")

    client_id = f"{cfg.client_prefix}shared"
    headers = {"X-API-Key": cfg.api_key, "Client": client_id}
    timeout = httpx.Timeout(cfg.timeout, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        if not cfg.embedding_provider or not cfg.embedding_model:
            cfg.embedding_provider, cfg.embedding_model = await _discover_embedding_model(
                http, cfg.base_url, cfg.api_key
            )
            print(
                f"Discovered embedding model: {cfg.embedding_provider}/{cfg.embedding_model}"
            )

        t0 = time.monotonic()
        await _post_upload_many(http, cfg.base_url, headers, paths)
        upload_seconds = time.monotonic() - t0
        print(
            f"Uploaded {len(paths)} corpus files in {upload_seconds:.2f}s "
            f"(client={client_id}, alias={args.alias})"
        )

        body = {
            "alias": args.alias,
            "embedding_model": {
                "provider": cfg.embedding_provider,
                "id": cfg.embedding_model,
            },
            "chunk_size": cfg.chunk_size,
            "chunk_overlap": cfg.chunk_overlap,
            "distance_strategy": cfg.distance_strategy,
            "index_type": cfg.index_type,
            "parsing_mode": cfg.parsing_mode,
        }
        t0 = time.monotonic()
        accepted = await _post_schedule(
            http, cfg.base_url, headers, body, cfg.rate_limit
        )
        schedule_seconds = time.monotonic() - t0
        job_id = accepted.get("job_id")
        if not isinstance(job_id, str):
            raise SystemExit("schedule response did not include a job_id")
        print(
            f"Scheduled embed job {job_id} in {schedule_seconds:.2f}s; "
            f"polling every {cfg.poll_interval:.1f}s (timeout {cfg.timeout:.0f}s)"
        )

        t0 = time.monotonic()
        info = await _poll(
            http, cfg.base_url, headers, job_id, cfg.poll_interval, cfg.timeout
        )
        wait_seconds = time.monotonic() - t0

    status = info.get("status", "unknown")
    print(f"Final status: {status} after {wait_seconds:.2f}s wait")
    if status != "succeeded":
        print(f"Error: {info.get('error') or '(no error message)'}")
        return 1
    return 0


def main() -> int:
    parser = build_argparser(__doc__)
    parser.add_argument(
        "--alias",
        default="RACING_SHARED",
        help="Shared alias for the single vector store table",
    )
    # --workers is inherited from the shared argparser but has no role
    # here: this script issues exactly one upload + one embed job; the
    # docstring above is the canonical explanation.
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
