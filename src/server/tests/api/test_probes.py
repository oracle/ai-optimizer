"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for probe endpoints (liveness, readiness, status).
"""

import pytest


@pytest.mark.unit
@pytest.mark.anyio
async def test_liveness(app_client):
    """Liveness probe returns 200 with alive status."""
    resp = await app_client.get('/v1/liveness')
    assert resp.status_code == 200
    assert resp.json() == {'status': 'alive'}


@pytest.mark.unit
@pytest.mark.anyio
async def test_readiness(app_client):
    """Readiness probe returns 200 with ready status."""
    resp = await app_client.get('/v1/readiness')
    assert resp.status_code == 200
    assert resp.json() == {'status': 'ready'}


@pytest.mark.unit
@pytest.mark.anyio
async def test_status_authenticated(app_client, auth_headers):
    """Status endpoint returns version and ok with valid API key."""
    resp = await app_client.get('/v1/status', headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert 'version' in body
    assert body['status'] == 'ok'


@pytest.mark.unit
@pytest.mark.anyio
async def test_status_no_auth(app_client):
    """Status endpoint rejects requests without API key."""
    resp = await app_client.get('/v1/status')
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_status_wrong_key(app_client):
    """Status endpoint rejects requests with an invalid API key."""
    resp = await app_client.get('/v1/status', headers={'X-API-Key': 'wrong-key'})
    assert resp.status_code == 403
