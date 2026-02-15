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
    "server.app.api.v1.schemas.databases",
)

API_KEY = "test-secret"
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture
def app_client(monkeypatch):
    """Build a TestClient after setting env vars and reloading the app.

    The client is entered as a context manager so that the FastAPI lifespan
    runs and the DEFAULT database alias is registered.
    """

    stack = ExitStack()

    def _make(env_vars: dict | None = None):
        for key in ("AIO_DB_USERNAME", "AIO_DB_PASSWORD", "AIO_DB_DSN"):
            monkeypatch.delenv(key, raising=False)
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

    def test_list_returns_default(self, app_client):
        """DEFAULT alias is always present in the list."""
        client = app_client()
        response = client.get("/v1/db", headers=HEADERS)
        assert response.status_code == 200
        aliases = [db["alias"] for db in response.json()]
        assert "DEFAULT" in aliases

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

    def test_create_default_returns_409(self, app_client):
        """Cannot create an alias named DEFAULT."""
        client = app_client()
        response = client.post("/v1/db", json={"alias": "DEFAULT"}, headers=HEADERS)
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

    def test_get_default(self, app_client):
        """DEFAULT alias is always retrievable."""
        client = app_client()
        response = client.get("/v1/db/DEFAULT", headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["alias"] == "DEFAULT"

    def test_get_missing_returns_404(self, app_client):
        """Unknown alias returns 404."""
        client = app_client()
        response = client.get("/v1/db/nonexistent", headers=HEADERS)
        assert response.status_code == 404

    def test_get_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.get("/v1/db/DEFAULT")
        assert response.status_code == 403


class TestUpdateDatabase:
    """PUT /v1/db/{alias}"""

    def test_update_missing_returns_404(self, app_client):
        """Unknown alias returns 404."""
        client = app_client()
        response = client.put("/v1/db/nonexistent", json={"dsn": "x"}, headers=HEADERS)
        assert response.status_code == 404

    def test_update_default_no_creds_returns_422(self, app_client):
        """Updating DEFAULT (which has no creds in test) with partial info still fails connectivity."""
        client = app_client()
        response = client.put("/v1/db/DEFAULT", json={"dsn": "newdsn"}, headers=HEADERS)
        # DEFAULT has usable=False (no creds in test), so update is applied but 422
        assert response.status_code == 422

    def test_update_closes_old_pool(self, app_client):
        """Updating an alias closes the old pool that was replaced by a successful update."""
        client = app_client()

        # Import through the same path the app uses to share the same registry
        from server.app.api.v1.endpoints import databases as db_ep

        existing = db_ep.get_registered_database("DEFAULT")
        old_pool = AsyncMock()
        db_ep.register_database(existing.with_pool(old_pool))

        validation_pool = AsyncMock()

        async def fake_init(settings):
            db_ep.register_database(settings.mark_usable(True).with_pool(None))
            return validation_pool

        with patch.object(db_ep, "initialize_schema", side_effect=fake_init):
            response = client.put("/v1/db/DEFAULT", json={"dsn": "newdsn"}, headers=HEADERS)

        assert response.status_code == 200
        old_pool.close.assert_awaited_once()
        validation_pool.close.assert_awaited_once()

    def test_update_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.put("/v1/db/DEFAULT", json={"dsn": "x"})
        assert response.status_code == 403


class TestDeleteDatabase:
    """DELETE /v1/db/{alias}"""

    def test_delete_default_returns_403(self, app_client):
        """DEFAULT alias cannot be deleted."""
        client = app_client()
        response = client.delete("/v1/db/DEFAULT", headers=HEADERS)
        assert response.status_code == 403

    def test_delete_missing_returns_404(self, app_client):
        """Unknown alias returns 404."""
        client = app_client()
        response = client.delete("/v1/db/nonexistent", headers=HEADERS)
        assert response.status_code == 404

    def test_delete_existing_returns_204(self, app_client):
        """Successfully delete a non-DEFAULT alias."""
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

        # Register an alias directly with a mock pool
        mock_pool = AsyncMock()
        db_ep.register_database(DatabaseSettings(alias="pooltest", usable=False, pool=mock_pool))

        response = client.delete("/v1/db/pooltest", headers=HEADERS)
        assert response.status_code == 204
        mock_pool.close.assert_awaited_once()

    def test_delete_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.delete("/v1/db/DEFAULT")
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
        response = client.get("/v1/db/DEFAULT", headers=HEADERS)
        data = response.json()
        assert "password" not in data
        assert "wallet_password" not in data
        assert "secret" not in response.text
