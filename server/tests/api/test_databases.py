"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the /v1/db CRUD endpoints.
"""
# spell-checker: disable
# pylint: disable=redefined-outer-name import-outside-toplevel

import importlib
import sys
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from .conftest import MODULES_TO_RELOAD as _BASE_MODULES

MODULES_TO_RELOAD = _BASE_MODULES + (
    "server.app.api.v1.endpoints.databases",
    "server.app.api.v1.endpoints.oci_profiles",
    "server.app.api.v1.schemas.databases",
    "server.app.api.v1.schemas.oci_profiles",
    "server.app.database.settings",
    "server.app.oci.settings",
)

API_KEY = "test-secret"
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture
def app_client(monkeypatch):
    """Build a TestClient after setting env vars and reloading the app.

    The client is entered as a context manager so that the FastAPI lifespan
    runs and the CORE database alias is registered.
    """

    stack = ExitStack()

    def _make(env_vars: dict | None = None):
        # Set DB vars to empty strings (not delenv) so they override .env.dev
        for key in ("AIO_DB_USERNAME", "AIO_DB_PASSWORD", "AIO_DB_DSN"):
            monkeypatch.setenv(key, "")
        monkeypatch.delenv("AIO_API_KEY", raising=False)
        monkeypatch.delenv("AIO_URL_PREFIX", raising=False)

        env = {"AIO_API_KEY": API_KEY}
        if env_vars:
            env.update(env_vars)
        for key, value in env.items():
            monkeypatch.setenv(key, value)

        for mod in MODULES_TO_RELOAD:
            sys.modules.pop(mod, None)

        main = importlib.import_module("server.app.main")
        client = TestClient(main.app)
        stack.enter_context(client)
        return client

    yield _make

    stack.close()


class TestListDatabases:
    """GET /v1/db"""

    def test_list_returns_core(self, app_client):
        """CORE alias is always present in the list."""
        client = app_client()
        response = client.get("/v1/db", headers=HEADERS)
        assert response.status_code == 200
        aliases = [db["alias"] for db in response.json()]
        assert "CORE" in aliases

    def test_list_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.get("/v1/db")
        assert response.status_code == 403

    def test_list_rejects_wrong_api_key(self, app_client):
        """Request with wrong API key returns 403."""
        client = app_client()
        response = client.get("/v1/db", headers={"X-API-Key": "wrong"})
        assert response.status_code == 403


class TestCreateDatabase:
    """POST /v1/db"""

    def test_create_core_returns_409(self, app_client):
        """Cannot create an alias named CORE."""
        client = app_client()
        response = client.post("/v1/db", json={"alias": "CORE"}, headers=HEADERS)
        assert response.status_code == 409

    def test_create_duplicate_returns_409(self, app_client):
        """Cannot create the same alias twice."""
        client = app_client()
        # First create should either succeed or fail connectivity (422) — alias is saved either way
        client.post("/v1/db", json={"alias": "dup_test"}, headers=HEADERS)
        # Second attempt is a duplicate
        response = client.post("/v1/db", json={"alias": "dup_test"}, headers=HEADERS)
        assert response.status_code == 409

    def test_create_invalid_alias_returns_422(self, app_client):
        """Alias must match the allowed pattern."""
        client = app_client()
        response = client.post("/v1/db", json={"alias": "123bad"}, headers=HEADERS)
        assert response.status_code == 422

    def test_create_no_creds_returns_422(self, app_client):
        """Create without credentials saves but returns 422 (not usable)."""
        client = app_client()
        response = client.post("/v1/db", json={"alias": "nocreds"}, headers=HEADERS)
        # No credentials means no connectivity test can pass
        assert response.status_code == 422

    def test_create_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.post("/v1/db", json={"alias": "test"})
        assert response.status_code == 403


class TestGetDatabase:
    """GET /v1/db/{alias}"""

    def test_get_core(self, app_client):
        """CORE alias is always retrievable."""
        client = app_client()
        response = client.get("/v1/db/CORE", headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["alias"] == "CORE"

    def test_get_missing_returns_404(self, app_client):
        """Unknown alias returns 404."""
        client = app_client()
        response = client.get("/v1/db/nonexistent", headers=HEADERS)
        assert response.status_code == 404

    def test_get_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.get("/v1/db/CORE")
        assert response.status_code == 403


class TestUpdateDatabase:
    """PUT /v1/db/{alias}"""

    def test_update_missing_returns_404(self, app_client):
        """Unknown alias returns 404."""
        client = app_client()
        response = client.put("/v1/db/nonexistent", json={"dsn": "x"}, headers=HEADERS)
        assert response.status_code == 404

    def test_update_core_no_creds_returns_422(self, app_client):
        """Updating CORE (which has no creds in test) with partial info still fails connectivity."""
        client = app_client()
        response = client.put("/v1/db/CORE", json={"dsn": "newdsn"}, headers=HEADERS)
        # CORE has usable=False (no creds in test), so update is applied but 422
        assert response.status_code == 422

    def test_update_closes_old_pool(self, app_client):
        """Updating CORE closes the old pool but keeps the validation pool for persistence."""
        client = app_client()

        # Import through the same path the app uses to share the same registry
        from server.app.api.v1.endpoints import databases as db_ep

        state = db_ep.get_registered_database("CORE")
        old_pool = AsyncMock()
        state.pool = old_pool

        validation_pool = AsyncMock()

        async def fake_init(settings):
            target = db_ep.get_registered_database(settings.alias)
            target.usable = True
            target.pool = None
            return validation_pool

        with (
            patch.object(db_ep, "initialize_schema", side_effect=fake_init),
            patch.object(db_ep, "persist_settings", new_callable=AsyncMock),
        ):
            response = client.put("/v1/db/CORE", json={"dsn": "newdsn"}, headers=HEADERS)

        assert response.status_code == 200
        old_pool.close.assert_awaited_once()
        # CORE keeps the validation pool as its runtime pool for persistence
        validation_pool.close.assert_not_awaited()
        # Clean up: remove mock pool so it doesn't leak into later tests
        state.pool = None

    def test_update_core_persists_settings(self, app_client):
        """Updating CORE must persist settings (pool stays open for persistence)."""
        client = app_client()

        from server.app.api.v1.endpoints import databases as db_ep

        validation_pool = AsyncMock()

        async def fake_init(settings):
            target = db_ep.get_registered_database(settings.alias)
            target.usable = True
            target.pool = None
            return validation_pool

        with (
            patch.object(db_ep, "initialize_schema", side_effect=fake_init),
            patch.object(db_ep, "persist_settings", new_callable=AsyncMock) as mock_persist,
        ):
            response = client.put("/v1/db/CORE", json={"dsn": "newdsn"}, headers=HEADERS)

        assert response.status_code == 200
        mock_persist.assert_awaited_once()
        # Clean up: remove mock pool so it doesn't leak into later tests
        state = db_ep.get_registered_database("CORE")
        state.pool = None

    def test_update_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.put("/v1/db/CORE", json={"dsn": "x"})
        assert response.status_code == 403


class TestDeleteDatabase:
    """DELETE /v1/db/{alias}"""

    def test_delete_core_returns_403(self, app_client):
        """CORE alias cannot be deleted."""
        client = app_client()
        response = client.delete("/v1/db/CORE", headers=HEADERS)
        assert response.status_code == 403

    def test_delete_missing_returns_404(self, app_client):
        """Unknown alias returns 404."""
        client = app_client()
        response = client.delete("/v1/db/nonexistent", headers=HEADERS)
        assert response.status_code == 404

    def test_delete_existing_returns_204(self, app_client):
        """Successfully delete a non-CORE alias."""
        client = app_client()
        # Create an alias first (will be saved even if connectivity fails)
        client.post("/v1/db", json={"alias": "todelete"}, headers=HEADERS)
        response = client.delete("/v1/db/todelete", headers=HEADERS)
        assert response.status_code == 204
        # Verify it's gone
        response = client.get("/v1/db/todelete", headers=HEADERS)
        assert response.status_code == 404

    def test_delete_closes_pool(self, app_client):
        """Deleting an alias closes its pool if one was open."""
        client = app_client()

        # Import through the same path the app uses to share the same registry
        from server.app.api.v1.endpoints import databases as db_ep
        from server.app.database.config import DatabaseSettings

        # Register an alias directly, then attach a mock pool
        mock_pool = AsyncMock()
        state = db_ep.register_database(DatabaseSettings(alias="pooltest"))
        state.pool = mock_pool

        response = client.delete("/v1/db/pooltest", headers=HEADERS)
        assert response.status_code == 204
        mock_pool.close.assert_awaited_once()

    def test_delete_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.delete("/v1/db/CORE")
        assert response.status_code == 403


class TestPasswordsNeverExposed:
    """Passwords must never appear in any response body."""

    def test_list_no_passwords(self, app_client):
        """List endpoint strips password fields from response."""
        client = app_client({"AIO_DB_USERNAME": "u", "AIO_DB_PASSWORD": "secret", "AIO_DB_DSN": "d"})
        response = client.get("/v1/db", headers=HEADERS)
        text = response.text
        assert "secret" not in text
        assert "password" not in text.lower() or "wallet_password" not in text.lower()
        for db in response.json():
            assert "password" not in db
            assert "wallet_password" not in db

    def test_get_no_passwords(self, app_client):
        """Get endpoint strips password fields from response."""
        client = app_client({"AIO_DB_USERNAME": "u", "AIO_DB_PASSWORD": "secret", "AIO_DB_DSN": "d"})
        response = client.get("/v1/db/CORE", headers=HEADERS)
        data = response.json()
        assert "password" not in data
        assert "wallet_password" not in data
        assert "secret" not in response.text


class TestActiveDatabase:
    """GET/PUT /v1/db/active"""

    def test_get_active_returns_core(self, app_client):
        """Active alias defaults to CORE."""
        client = app_client()
        response = client.get("/v1/db/active", headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["alias"] == "CORE"

    def test_set_active_unknown_alias_returns_404(self, app_client):
        """Setting active to unknown alias returns 404."""
        client = app_client()
        response = client.put("/v1/db/active", json={"alias": "NOPE"}, headers=HEADERS)
        assert response.status_code == 404

    def test_set_active_to_core(self, app_client):
        """Can explicitly set active back to CORE."""
        client = app_client()
        response = client.put("/v1/db/active", json={"alias": "CORE"}, headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["alias"] == "CORE"

    def test_set_active_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.put("/v1/db/active", json={"alias": "CORE"})
        assert response.status_code == 403

    def test_delete_active_alias_resets_to_core(self, app_client):
        """Deleting the active alias resets it to CORE."""
        client = app_client()

        from server.app.api.v1.endpoints import databases as db_ep
        from server.app.database.config import DatabaseSettings

        # Register an alias and set it as active
        db_ep.register_database(DatabaseSettings(alias="temp"))
        db_ep.set_active_alias("temp")

        response = client.delete("/v1/db/temp", headers=HEADERS)
        assert response.status_code == 204

        response = client.get("/v1/db/active", headers=HEADERS)
        assert response.json()["alias"] == "CORE"
