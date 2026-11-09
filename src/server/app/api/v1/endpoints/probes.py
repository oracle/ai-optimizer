"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore noauth fastmcp healthz

import asyncio

from fastapi import APIRouter, HTTPException

from _version import __version__
from server.app.api.v1.schemas.probes import ProbeResponse, StatusResponse
from server.app.database.config import get_core_pool
from server.app.database.sql import execute_sql

noauth = APIRouter()
_READINESS_TIMEOUT_SECONDS = 2.0
_CORE_UNAVAILABLE = "CORE database is unavailable"


@noauth.get("/liveness", response_model=ProbeResponse)
async def liveness_probe():
    """Kubernetes liveness probe"""
    return {"status": "alive"}


@noauth.get("/readiness", response_model=ProbeResponse)
async def readiness_probe():
    """Return ready after a bounded CORE database round trip."""

    async def _check_core() -> None:
        pool = get_core_pool()
        if pool is None:
            raise RuntimeError(_CORE_UNAVAILABLE)
        async with pool.acquire() as conn:
            rows = await execute_sql(conn, "SELECT 1 FROM DUAL", max_rows=1)
        if rows != [(1,)]:
            raise RuntimeError(_CORE_UNAVAILABLE)

    try:
        await asyncio.wait_for(_check_core(), timeout=_READINESS_TIMEOUT_SECONDS)
    except Exception:
        raise HTTPException(status_code=503, detail=_CORE_UNAVAILABLE) from None
    return {"status": "ready"}


@noauth.get("/healthz", response_model=StatusResponse)
async def get_status():
    """Return application version and status."""
    return {"version": __version__, "status": "ok"}
