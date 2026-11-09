"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for probe endpoints (liveness, readiness, healthz).
"""
# spell-checker: disable

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import oracledb
import pytest

MODULE = "server.app.api.v1.endpoints.probes"


def _mock_pool() -> MagicMock:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.mark.unit
@pytest.mark.anyio
async def test_liveness(app_client):
    """Liveness probe returns 200 with alive status."""
    resp = await app_client.get("/v1/liveness")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


@pytest.mark.unit
@pytest.mark.anyio
async def test_readiness(app_client):
    """Readiness returns 200 after a successful CORE round trip."""
    with (
        patch(f"{MODULE}.get_core_pool", return_value=_mock_pool()),
        patch(f"{MODULE}.execute_sql", new_callable=AsyncMock, return_value=[(1,)]),
    ):
        resp = await app_client.get("/v1/readiness")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


@pytest.mark.unit
@pytest.mark.anyio
async def test_readiness_missing_core_pool(app_client):
    with patch(f"{MODULE}.get_core_pool", return_value=None):
        resp = await app_client.get("/v1/readiness")

    assert resp.status_code == 503
    assert resp.json() == {"detail": "CORE database is unavailable"}


@pytest.mark.unit
@pytest.mark.anyio
async def test_readiness_oracle_error(app_client):
    with (
        patch(f"{MODULE}.get_core_pool", return_value=_mock_pool()),
        patch(f"{MODULE}.execute_sql", new_callable=AsyncMock, side_effect=oracledb.Error("connection lost")),
    ):
        resp = await app_client.get("/v1/readiness")

    assert resp.status_code == 503
    assert resp.json() == {"detail": "CORE database is unavailable"}


@pytest.mark.unit
@pytest.mark.anyio
async def test_readiness_timeout(app_client):
    async def _slow_query(*_args, **_kwargs):
        await asyncio.sleep(1)

    with (
        patch(f"{MODULE}.get_core_pool", return_value=_mock_pool()),
        patch(f"{MODULE}.execute_sql", side_effect=_slow_query),
        patch(f"{MODULE}._READINESS_TIMEOUT_SECONDS", 0.01),
    ):
        resp = await app_client.get("/v1/readiness")

    assert resp.status_code == 503
    assert resp.json() == {"detail": "CORE database is unavailable"}


@pytest.mark.unit
@pytest.mark.anyio
async def test_healthz(app_client):
    """Healthz probe returns 200 with version and ok status (no auth required)."""
    resp = await app_client.get("/v1/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body
    assert body["status"] == "ok"
