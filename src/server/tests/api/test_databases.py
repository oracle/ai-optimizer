"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for databases endpoint.
"""
# pylint: disable=duplicate-code

import pytest

from server.app.core.databases import DatabaseConfig, DatabaseSensitive
from server.app.core.settings import settings

SENSITIVE_KEYS = set(DatabaseSensitive.model_fields.keys())


@pytest.fixture(autouse=True)
def _populate_configs():
    """Inject test DatabaseConfig entries into settings."""
    original = settings.database_configs
    settings.database_configs = [
        DatabaseConfig(
            alias="TEST",
            username="testuser",
            password="secret",
            wallet_password="wallet_secret",
        ),
        DatabaseConfig(
            alias="PROD",
            username="produser",
            password="prod_secret",
        ),
    ]
    yield
    settings.database_configs = original


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_databases_no_auth(app_client):
    """Databases endpoint rejects requests without API key."""
    resp = await app_client.get("/v1/databases")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_databases(app_client, auth_headers):
    """Default response returns all configs without sensitive fields."""
    resp = await app_client.get("/v1/databases", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    for entry in body:
        for key in SENSITIVE_KEYS:
            assert key not in entry
        assert "alias" in entry


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_databases_sensitive(app_client, auth_headers):
    """Response includes sensitive fields when include_sensitive=true."""
    resp = await app_client.get("/v1/databases", params={"include_sensitive": "true"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["password"] == "secret"
    assert body[0]["wallet_password"] == "wallet_secret"


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_database(app_client, auth_headers):
    """Fetch a single database config by alias."""
    resp = await app_client.get("/v1/databases/TEST", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["alias"] == "TEST"
    for key in SENSITIVE_KEYS:
        assert key not in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_database_not_found(app_client, auth_headers):
    """Return 404 for unknown alias."""
    resp = await app_client.get("/v1/databases/MISSING", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_database_case_insensitive(app_client, auth_headers):
    """Alias lookup is case-insensitive."""
    resp = await app_client.get("/v1/databases/test", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["alias"] == "TEST"
