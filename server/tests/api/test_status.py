"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the authenticated /status endpoint.
"""
# spell-checker: disable
# pylint: disable=redefined-outer-name import-outside-toplevel

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

MODULES_TO_RELOAD = (
    "server.app.main",
    "server.app.core.config",
    "server.app.api.deps",
    "server.app.api.v1.router",
    "server.app.api.v1.endpoints.probes",
    "server.app.db",
    "server.app.db.config",
)


@pytest.fixture
def app_client(monkeypatch):
    """Build a TestClient after setting env vars and reloading the app."""

    def _make(env_vars: dict | None = None):
        # Prevent real DB connections
        for key in ("AIO_DB_USERNAME", "AIO_DB_PASSWORD", "AIO_DB_DSN"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv("AIO_API_KEY", raising=False)
        monkeypatch.delenv("AIO_URL_PREFIX", raising=False)

        if env_vars:
            for key, value in env_vars.items():
                monkeypatch.setenv(key, value)

        for mod in MODULES_TO_RELOAD:
            sys.modules.pop(mod, None)

        main = importlib.import_module("server.app.main")
        return TestClient(main.app)

    return _make


class TestStatusAuth:
    """Tests for API key authentication on /v1/status."""

    def test_no_api_key_header_returns_403(self, app_client):
        """Request without X-API-Key header is rejected."""
        client = app_client({"AIO_API_KEY": "test-secret"})
        response = client.get("/v1/status")
        assert response.status_code == 403

    def test_wrong_api_key_returns_403(self, app_client):
        """Request with incorrect API key is rejected."""
        client = app_client({"AIO_API_KEY": "test-secret"})
        response = client.get("/v1/status", headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 403

    def test_correct_api_key_returns_200(self, app_client):
        """Request with correct API key succeeds."""
        client = app_client({"AIO_API_KEY": "test-secret"})
        response = client.get("/v1/status", headers={"X-API-Key": "test-secret"})
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert data["status"] == "ok"

    def test_generated_key_rejects_random_value(self, app_client):
        """When AIO_API_KEY is not set, a random key is generated; guessing won't work."""
        client = app_client()
        response = client.get("/v1/status", headers={"X-API-Key": "anything"})
        assert response.status_code == 403

    def test_generated_key_is_logged(self, app_client, caplog):
        """When AIO_API_KEY is not set, the generated key is logged at startup."""
        import logging
        client = app_client()
        with caplog.at_level(logging.WARNING, logger="server.app.main"):
            # Lifespan runs when entering the TestClient context
            with client:
                assert "AIO_API_KEY not set" in caplog.text
                # Extract the generated key from the log and verify it works
                for record in caplog.records:
                    if "generated key" in record.message:
                        generated_key = record.message.split(": ", 1)[1]
                        response = client.get(
                            "/v1/status",
                            headers={"X-API-Key": generated_key},
                        )
                        assert response.status_code == 200
                        return
                pytest.fail("Expected log message with generated key not found")

    def test_probes_remain_unauthenticated(self, app_client):
        """Probe endpoints should not require authentication."""
        client = app_client({"AIO_API_KEY": "test-secret"})
        response = client.get("/v1/liveness")
        assert response.status_code == 200
