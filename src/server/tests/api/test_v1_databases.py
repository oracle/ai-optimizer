"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for databases endpoint.
"""
# spell-checker:disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from server.app.core.settings import settings
from server.app.database.schemas import DatabaseSensitive
from server.app.embed.schemas import VectorStoreConfig
from server.tests.conftest import assert_no_sensitive_keys, make_test_database_config

SENSITIVE_KEYS = set(DatabaseSensitive.model_fields.keys())


@pytest.fixture(autouse=True)
def _populate_configs():
    """Inject test DatabaseConfig entries into settings."""
    original = settings.database_configs
    settings.database_configs = [
        make_test_database_config(),
        make_test_database_config(alias="PROD", username="produser", password="prod_secret", wallet_password=None),
        make_test_database_config(alias="CORE", username="coreuser", password="core_secret"),
    ]
    yield
    settings.database_configs = original


@pytest.fixture(autouse=True)
def mock_persist_settings():
    """Prevent persist_settings from doing real DB I/O in every test."""
    with patch("server.app.api.v1.endpoints.databases.persist_settings", new_callable=AsyncMock) as mock_persist:
        yield mock_persist


@pytest.fixture(autouse=True)
def mock_refresh_sqlcl():
    """Prevent the SQLcl proxy refresh from spawning a real sqlcl daemon in tests."""
    with patch("server.app.api.v1.endpoints.databases.refresh_sqlcl_proxy", new_callable=AsyncMock) as mock_refresh:
        yield mock_refresh


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_databases_no_auth(app_client):
    """Databases endpoint rejects requests without API key."""
    resp = await app_client.get("/v1/databases")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_no_auth(app_client):
    """POST databases rejects requests without API key."""
    resp = await app_client.post("/v1/databases", json={"alias": "X"})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_database_no_auth(app_client):
    """PUT databases rejects requests without API key."""
    resp = await app_client.put("/v1/databases/TEST", json={"username": "x"})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_database_no_auth(app_client):
    """DELETE databases rejects requests without API key."""
    resp = await app_client.delete("/v1/databases/TEST")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_vector_store_no_auth(app_client):
    """DELETE vector-store rejects requests without API key."""
    resp = await app_client.delete("/v1/databases/TEST/vector-stores/VS1")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_databases(app_client, auth_headers):
    """Default response returns all configs without sensitive fields."""
    resp = await app_client.get("/v1/databases", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3
    assert_no_sensitive_keys(body, SENSITIVE_KEYS, "alias")


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_databases_uses_standard_projection(app_client, auth_headers):
    """The list endpoint uses the standard projection when extra params are present."""
    resp = await app_client.get("/v1/databases", params={"include_sensitive": "true"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3
    assert_no_sensitive_keys(body, SENSITIVE_KEYS, "alias")


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
async def test_get_database_alternate_projection(app_client, auth_headers):
    """Fetch the alternate projection for a single database."""
    resp = await app_client.get(
        "/v1/databases/TEST",
        params={"include_sensitive": "true"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["password"] == "secret"


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
    with patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock):
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


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_core_database_initializes_schema(app_client, auth_headers):
    """POST CORE alias calls init_core_database instead of test_connection."""
    settings.database_configs = [
        make_test_database_config(),
    ]
    with (
        patch("server.app.api.v1.endpoints.databases.init_core_database", new_callable=AsyncMock) as mock_init,
        patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock) as mock_test,
    ):
        resp = await app_client.post(
            "/v1/databases",
            json={"alias": "CORE", "username": "coreuser"},
            headers=auth_headers,
        )
    assert resp.status_code == 201
    mock_init.assert_called_once()
    mock_test.assert_not_called()


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_requires_core_first(app_client, auth_headers):
    """POST non-CORE alias returns 422 when no CORE database exists."""
    settings.database_configs = [
        make_test_database_config(),
        make_test_database_config(alias="PROD", username="produser", password="prod_secret", wallet_password=None),
    ]
    resp = await app_client.post(
        "/v1/databases",
        json={"alias": "NEW_DB", "username": "newuser"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "CORE" in resp.json()["detail"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_duplicate_credentials(app_client, auth_headers):
    """Duplicate username/dsn combination returns 409."""
    settings.database_configs[0].username = "shared_user"
    settings.database_configs[0].dsn = "ORCL"
    resp = await app_client.post(
        "/v1/databases",
        json={"alias": "SECOND", "username": "shared_user", "dsn": "orcl"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


# --- PUT /databases/{alias} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_database(app_client, auth_headers):
    """PUT with new username returns 200 and field is changed."""
    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock),
        patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock),
    ):
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
    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock),
        patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock),
    ):
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
async def test_update_database_duplicate_credentials(app_client, auth_headers):
    """Updating to duplicate username/dsn returns 409."""
    settings.database_configs[0].username = "primary"
    settings.database_configs[0].dsn = "ORCL"
    settings.database_configs[1].username = "secondary"
    settings.database_configs[1].dsn = "REMOTE"

    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock) as mock_close,
        patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock) as mock_test,
    ):
        resp = await app_client.put(
            "/v1/databases/PROD",
            json={"username": "primary", "dsn": "orcl"},
            headers=auth_headers,
        )

    assert resp.status_code == 409
    mock_close.assert_not_called()
    mock_test.assert_not_called()


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_vector_store_persist_failure_still_removes(app_client, auth_headers, mock_persist_settings):
    """Persist failure after DROP TABLE still removes vector_stores entry (table is already gone)."""
    vector_store = VectorStoreConfig(vector_store="VS_GONE", alias="vs")
    conn = AsyncMock()
    pool = _create_mock_pool(conn)
    settings.database_configs[0].vector_stores = [vector_store]
    settings.database_configs[0].pool = pool

    mock_persist_settings.return_value = False

    with patch("server.app.api.v1.endpoints.databases.drop_vector_store", new_callable=AsyncMock) as mock_drop:
        resp = await app_client.delete(
            "/v1/databases/TEST/vector-stores/VS_GONE",
            headers=auth_headers,
        )

    assert resp.status_code == 204
    mock_drop.assert_called_once_with(conn, "VS_GONE")
    assert settings.database_configs[0].vector_stores == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_core_database_reinitializes(app_client, auth_headers, mock_persist_settings):
    """PUT on CORE alias closes existing pool, re-initialises, then persists."""
    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock) as mock_close,
        patch("server.app.api.v1.endpoints.databases.init_core_database", new_callable=AsyncMock) as mock_init,
    ):
        resp = await app_client.put(
            "/v1/databases/CORE",
            json={"username": "new_core_user"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        mock_close.assert_called_once()
        mock_init.assert_called_once()
        mock_persist_settings.assert_called_once()
        # CORE path does not call test_connection


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_persists_settings(app_client, auth_headers, mock_persist_settings):
    """POST persists settings after successful creation."""
    with patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock):
        resp = await app_client.post(
            "/v1/databases",
            json={"alias": "PERSIST_DB", "username": "u"},
            headers=auth_headers,
        )
    assert resp.status_code == 201
    mock_persist_settings.assert_called_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_connection_error(app_client, auth_headers):
    """POST returns 201 with a fallback error field when connection test fails."""
    with patch(
        "server.app.api.v1.endpoints.databases.test_connection",
        new_callable=AsyncMock,
        side_effect=Exception("marker-alpha marker-beta marker-gamma"),
    ):
        resp = await app_client.post(
            "/v1/databases",
            json={"alias": "BAD_DB", "username": "u", "password": "p", "dsn": "bad"},
            headers=auth_headers,
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["usable"] is False
    assert body["error"]
    for token in ("marker-alpha", "marker-beta", "marker-gamma"):
        assert token not in body["error"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_core_database_connection_failure(app_client, auth_headers, mock_persist_settings):
    """Rule 4 (CORE path): not-working → not-working = accept (200 with error)."""
    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock),
        patch(
            "server.app.api.v1.endpoints.databases.init_core_database",
            new_callable=AsyncMock,
            side_effect=Exception("marker-alpha marker-beta marker-gamma"),
        ),
    ):
        resp = await app_client.put(
            "/v1/databases/CORE",
            json={"username": "new_core_user"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["usable"] is False
    assert body["error"]
    for token in ("marker-alpha", "marker-beta", "marker-gamma"):
        assert token not in body["error"]
    mock_persist_settings.assert_called_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_database_connection_error_not_usable(app_client, auth_headers):
    """Rule 4: not-working → not-working = accept (200 with error field)."""
    assert settings.database_configs[0].usable is False
    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock),
        patch(
            "server.app.api.v1.endpoints.databases.test_connection",
            new_callable=AsyncMock,
            side_effect=Exception("marker-alpha marker-beta marker-gamma"),
        ),
    ):
        resp = await app_client.put(
            "/v1/databases/TEST",
            json={"username": "updated_user"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["usable"] is False
    assert body["error"]
    for token in ("marker-alpha", "marker-beta", "marker-gamma"):
        assert token not in body["error"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_usable_database_rejects_broken_config(app_client, auth_headers):
    """Rule 1: working → doesn't work = REJECT (422), old config preserved."""
    cfg = settings.database_configs[0]
    cfg.usable = True
    cfg.pool = MagicMock()
    original_dsn = cfg.dsn

    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock),
        patch(
            "server.app.api.v1.endpoints.databases.test_connection",
            new_callable=AsyncMock,
            side_effect=Exception("marker-alpha marker-beta marker-gamma"),
        ),
    ):
        resp = await app_client.put(
            "/v1/databases/TEST",
            json={"dsn": "//bad-host:9999/NONEXIST"},
            headers=auth_headers,
        )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail
    for token in ("marker-alpha", "marker-beta", "marker-gamma"):
        assert token not in detail
    # Old config fully restored
    assert cfg.usable is True
    assert cfg.dsn == original_dsn
    assert cfg.pool is not None


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_usable_database_persist_fails_restores_pool(app_client, auth_headers, mock_persist_settings):
    """Persist failure restores original pool and usable state instead of leaving them None/False."""
    cfg = settings.database_configs[0]
    cfg.usable = True
    original_pool = MagicMock(name="original_pool")
    cfg.pool = original_pool
    new_pool = MagicMock(name="new_pool")

    mock_persist_settings.return_value = False

    async def fake_test_connection(db_cfg):
        db_cfg.pool = new_pool
        db_cfg.usable = True

    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock) as mock_close,
        patch(
            "server.app.api.v1.endpoints.databases.test_connection",
            new_callable=AsyncMock,
            side_effect=fake_test_connection,
        ),
    ):
        resp = await app_client.put(
            "/v1/databases/TEST",
            json={"username": "updated_user"},
            headers=auth_headers,
        )

    assert resp.status_code == 503
    # Original pool restored, not set to None
    assert cfg.pool is original_pool
    assert cfg.usable is True
    # New pool was closed, old pool was NOT closed
    mock_close.assert_called_once_with(new_pool)


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
    resp = await app_client.delete("/v1/databases/CORE", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_database_core_case_insensitive(app_client, auth_headers):
    """DELETE 'core' (lowercase) is also forbidden."""
    resp = await app_client.delete("/v1/databases/core", headers=auth_headers)
    assert resp.status_code == 403


# --- DELETE /databases/{alias}/vector-stores/{table} ---


def _create_mock_pool(conn: AsyncMock) -> MagicMock:
    """Return a MagicMock that behaves like an async pool with .acquire()."""
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_vector_store_success(app_client, auth_headers, mock_persist_settings):
    """Dropping a vector store removes it and calls drop_vector_store."""
    vector_store = VectorStoreConfig(vector_store="VS1", alias="vs")
    conn = AsyncMock()
    pool = _create_mock_pool(conn)
    settings.database_configs[0].vector_stores = [vector_store]
    settings.database_configs[0].pool = pool

    with patch("server.app.api.v1.endpoints.databases.drop_vector_store", new_callable=AsyncMock) as mock_drop:
        resp = await app_client.delete(
            "/v1/databases/TEST/vector-stores/VS1",
            headers=auth_headers,
        )

    assert resp.status_code == 204
    mock_drop.assert_called_once_with(conn, "VS1")
    mock_persist_settings.assert_called_once()
    assert settings.database_configs[0].vector_stores == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_vector_store_missing_db(app_client, auth_headers):
    """Unknown database alias returns 404."""
    resp = await app_client.delete(
        "/v1/databases/MISSING/vector-stores/VS1",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_vector_store_missing_entry(app_client, auth_headers):
    """Missing vector store entry returns 404."""
    settings.database_configs[0].vector_stores = []
    resp = await app_client.delete(
        "/v1/databases/TEST/vector-stores/VS1",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_vector_store_requires_pool(app_client, auth_headers):
    """Vector store cannot be dropped when database is not usable."""
    settings.database_configs[0].vector_stores = [VectorStoreConfig(vector_store="VS1")]
    settings.database_configs[0].pool = None

    resp = await app_client.delete(
        "/v1/databases/TEST/vector-stores/VS1",
        headers=auth_headers,
    )

    assert resp.status_code == 409


# --- SQLcl refresh hook ---
#
# The SQLcl MCP daemon caches the connection store it reads at startup, so any
# database CRUD that the daemon should see must trigger a proxy refresh.  The
# refresh is expensive (a multi-second tear-down/rebuild), so creates/updates
# that can't affect the store (no credentials) must skip it.


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_refreshes_sqlcl_with_creds(app_client, auth_headers, mock_refresh_sqlcl):
    """Creating a DB with full credentials triggers a SQLcl proxy refresh."""
    with patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock):
        resp = await app_client.post(
            "/v1/databases",
            json={"alias": "WITH_CREDS", "username": "u", "password": "p", "dsn": "d"},
            headers=auth_headers,
        )
    assert resp.status_code == 201
    mock_refresh_sqlcl.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_skips_sqlcl_without_creds(app_client, auth_headers, mock_refresh_sqlcl):
    """Creating a DB row without full credentials leaves the SQLcl store untouched."""
    with patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock):
        resp = await app_client.post(
            "/v1/databases",
            json={"alias": "NO_CREDS", "username": "u"},
            headers=auth_headers,
        )
    assert resp.status_code == 201
    mock_refresh_sqlcl.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_persist_failure_skips_sqlcl(
    app_client, auth_headers, mock_refresh_sqlcl, mock_persist_settings
):
    """Persist rollback must not leave SQLcl rebuilt around a dropped config."""
    mock_persist_settings.return_value = False
    with patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock):
        resp = await app_client.post(
            "/v1/databases",
            json={"alias": "ROLLBACK_DB", "username": "u", "password": "p", "dsn": "d"},
            headers=auth_headers,
        )
    assert resp.status_code == 503
    mock_refresh_sqlcl.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_database_duplicate_skips_sqlcl(app_client, auth_headers, mock_refresh_sqlcl):
    """Conflict (409) before mutation must not trigger a refresh."""
    resp = await app_client.post(
        "/v1/databases",
        json={"alias": "TEST", "username": "u", "password": "p", "dsn": "d"},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    mock_refresh_sqlcl.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_database_refreshes_sqlcl(app_client, auth_headers, mock_refresh_sqlcl):
    """Updating a config with credentials triggers a SQLcl refresh so the daemon sees the new creds."""
    # Give TEST full creds so the updated config is SQLcl-relevant.
    cfg = settings.database_configs[0]
    cfg.username = "u"
    cfg.password = SecretStr("p")
    cfg.dsn = "d"
    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock),
        patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock),
    ):
        resp = await app_client.put(
            "/v1/databases/TEST",
            json={"password": "new_password"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    mock_refresh_sqlcl.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_database_rejection_skips_sqlcl(app_client, auth_headers, mock_refresh_sqlcl):
    """Rule 1: working + new fails → 422 reject; the proxy must not be rebuilt."""
    cfg = settings.database_configs[0]
    cfg.usable = True
    cfg.pool = MagicMock()
    cfg.username = "u"
    cfg.password = SecretStr("p")
    cfg.dsn = "d"
    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock),
        patch(
            "server.app.api.v1.endpoints.databases.test_connection",
            new_callable=AsyncMock,
            side_effect=Exception("ORA-12541"),
        ),
    ):
        resp = await app_client.put(
            "/v1/databases/TEST",
            json={"dsn": "//bad-host:9999/X"},
            headers=auth_headers,
        )
    assert resp.status_code == 422
    mock_refresh_sqlcl.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_database_removing_creds_refreshes_sqlcl(app_client, auth_headers, mock_refresh_sqlcl):
    """Clearing credentials must drop the alias from the SQLcl store."""
    cfg = settings.database_configs[0]
    cfg.username = "u"
    cfg.password = SecretStr("p")
    cfg.dsn = "d"
    with (
        patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock),
        patch("server.app.api.v1.endpoints.databases.test_connection", new_callable=AsyncMock),
    ):
        resp = await app_client.put(
            "/v1/databases/TEST",
            json={"password": None},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    mock_refresh_sqlcl.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_database_refreshes_sqlcl(app_client, auth_headers, mock_refresh_sqlcl):
    """Deleting a database always refreshes the SQLcl proxy."""
    with patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock):
        resp = await app_client.delete("/v1/databases/TEST", headers=auth_headers)
    assert resp.status_code == 204
    mock_refresh_sqlcl.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_database_persist_failure_skips_sqlcl(
    app_client, auth_headers, mock_refresh_sqlcl, mock_persist_settings
):
    """Persist rollback on DELETE must not leave SQLcl rebuilt around a restored config."""
    mock_persist_settings.return_value = False
    with patch("server.app.api.v1.endpoints.databases.close_pool", new_callable=AsyncMock):
        resp = await app_client.delete("/v1/databases/TEST", headers=auth_headers)
    assert resp.status_code == 503
    mock_refresh_sqlcl.assert_not_awaited()
