"""Tests for fail-closed FastAPI authentication dependencies."""

import pytest

from server.app.auth.dependencies import set_authority_state

pytestmark = pytest.mark.unit


async def test_valid_bearer_establishes_test_principal(app_client, auth_headers):
    response = await app_client.get("/v1/settings", headers=auth_headers)
    assert response.status_code == 200


async def test_missing_bearer_returns_challenge(app_client):
    response = await app_client.get("/v1/settings")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_invalid_bearer_returns_challenge(app_client):
    response = await app_client.get("/v1/settings", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_x_api_key_has_no_authentication_meaning(app_client):
    response = await app_client.get("/v1/settings", headers={"X-API-Key": "test-token"})
    assert response.status_code == 401


async def test_authority_preflight_failure_returns_503(app_client, auth_headers):
    set_authority_state(False, "Authority record is missing")
    response = await app_client.get("/v1/settings", headers=auth_headers)
    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication authority is unavailable"}
