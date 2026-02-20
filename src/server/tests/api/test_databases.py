"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for databases endpoint.
"""
# pylint: disable=duplicate-code

from unittest.mock import AsyncMock, patch

import pytest

from server.app.database.model import DatabaseConfig, DatabaseSensitive
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


# --- POST /databases ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database(app_client, auth_headers):
    """POST new alias returns 201 and config appears in list."""
    resp = await app_client.post(
        "/v1/databases",
        json={"alias": "NEW_DB", "username": "newuser"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["alias"] == "NEW_DB"
    assert body["username"] == "newuser"
    for key in SENSITIVE_KEYS:
        assert key not in body
    # Verify it appears in the list
    list_resp = await app_client.get("/v1/databases", headers=auth_headers)
    aliases = [db["alias"] for db in list_resp.json()]
    assert "NEW_DB" in aliases


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_duplicate(app_client, auth_headers):
    """POST existing alias returns 409."""
    resp = await app_client.post(
        "/v1/databases",
        json={"alias": "TEST"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_duplicate_case_insensitive(app_client, auth_headers):
    """POST 'test' when 'TEST' exists returns 409."""
    resp = await app_client.post(
        "/v1/databases",
        json={"alias": "test"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


# --- PUT /databases/{alias} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_database(app_client, auth_headers):
    """PUT with new username returns 200 and field is changed."""
    resp = await app_client.put(
        "/v1/databases/TEST",
        json={"username": "updated_user"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "updated_user"
    for key in SENSITIVE_KEYS:
        assert key not in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_database_not_found(app_client, auth_headers):
    """PUT unknown alias returns 404."""
    resp = await app_client.put(
        "/v1/databases/MISSING",
        json={"username": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_database_partial(app_client, auth_headers):
    """PUT only one field leaves others unchanged."""
    resp = await app_client.put(
        "/v1/databases/TEST",
        json={"dsn": "new_dsn"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dsn"] == "new_dsn"
    assert body["username"] == "testuser"  # unchanged


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_core_database_reinitializes(app_client, auth_headers):
    """PUT on CORE alias closes existing pool, re-initialises, then persists."""
    settings.database_configs.append(DatabaseConfig(alias="CORE", username="coreuser"))
    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock) as mock_close,
        patch("server.app.api.v1.endpoints.databases.init_core_database", new_callable=AsyncMock) as mock_init,
        patch("server.app.api.v1.endpoints.databases.persist_settings", new_callable=AsyncMock) as mock_persist,
    ):
        resp = await app_client.put(
            "/v1/databases/CORE",
            json={"username": "new_core_user"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        mock_close.assert_called_once()
        mock_init.assert_called_once()
        mock_persist.assert_called_once()


# --- DELETE /databases/{alias} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_database(app_client, auth_headers):
    """DELETE removes config and closes pool."""
    with patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock) as mock_close:
        resp = await app_client.delete("/v1/databases/TEST", headers=auth_headers)
        assert resp.status_code == 204
        mock_close.assert_called_once()
    # Verify it's gone
    list_resp = await app_client.get("/v1/databases", headers=auth_headers)
    aliases = [db["alias"] for db in list_resp.json()]
    assert "TEST" not in aliases


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_database_not_found(app_client, auth_headers):
    """DELETE unknown alias returns 404."""
    resp = await app_client.delete("/v1/databases/MISSING", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_database_core_forbidden(app_client, auth_headers):
    """DELETE CORE alias returns 403."""
    settings.database_configs.append(DatabaseConfig(alias="CORE"))
    resp = await app_client.delete("/v1/databases/CORE", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_database_core_case_insensitive(app_client, auth_headers):
    """DELETE 'core' (lowercase) is also forbidden."""
    resp = await app_client.delete("/v1/databases/core", headers=auth_headers)
    assert resp.status_code == 403
