"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for probe endpoints (liveness, readiness, healthz).
"""
# pylint: disable=duplicate-code

import pytest


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
    """Readiness probe returns 200 with ready status."""
    resp = await app_client.get("/v1/readiness")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


@pytest.mark.unit
@pytest.mark.anyio
async def test_healthz(app_client):
    """Healthz probe returns 200 with version and ok status (no auth required)."""
    resp = await app_client.get("/v1/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body
    assert body["status"] == "ok"
