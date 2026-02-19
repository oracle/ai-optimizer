"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the /v1/oci CRUD endpoints.
"""
# spell-checker: disable
# pylint: disable=redefined-outer-name import-outside-toplevel duplicate-code

import importlib
import sys
from contextlib import ExitStack

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
    """Build a TestClient after setting env vars and reloading the app."""

    stack = ExitStack()

    def _make(env_vars: dict | None = None):
        for key in ("AIO_DB_USERNAME", "AIO_DB_PASSWORD", "AIO_DB_DSN"):
            monkeypatch.setenv(key, "")
        monkeypatch.delenv("AIO_API_KEY", raising=False)
        monkeypatch.delenv("AIO_SERVER_URL_PREFIX", raising=False)

        env = {"AIO_API_KEY": API_KEY}
        if env_vars:
            env.update(env_vars)
        for key, value in env.items():
            monkeypatch.setenv(key, value)

        for mod in MODULES_TO_RELOAD:
            sys.modules.pop(mod, None)

        # Point OCI config to a nonexistent file so no real profiles load
        monkeypatch.setenv("OCI_CLI_CONFIG_FILE", "/nonexistent/oci/config")

        main = importlib.import_module("server.app.main")
        client = TestClient(main.app)
        stack.enter_context(client)
        return client

    yield _make

    stack.close()


class TestListOCIProfiles:
    """GET /v1/oci"""

    def test_list_empty(self, app_client):
        """Empty list when no OCI config file exists."""
        client = app_client()
        response = client.get("/v1/oci", headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == []

    def test_list_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.get("/v1/oci")
        assert response.status_code == 403


class TestCreateOCIProfile:
    """POST /v1/oci"""

    def test_create_new_profile(self, app_client):
        """Successfully create a new OCI profile."""
        client = app_client()
        payload = {
            "auth_profile": "TEST",
            "user": "ocid1.user.oc1..test",
            "tenancy": "ocid1.tenancy.oc1..test",
            "region": "us-ashburn-1",
            "fingerprint": "aa:bb:cc",
        }
        response = client.post("/v1/oci", json=payload, headers=HEADERS)
        assert response.status_code == 201
        data = response.json()
        assert data["auth_profile"] == "TEST"
        assert data["user"] == "ocid1.user.oc1..test"
        assert data["region"] == "us-ashburn-1"
        assert data["usable"] is True

    def test_create_duplicate_returns_409(self, app_client):
        """Cannot create the same profile name twice."""
        client = app_client()
        payload = {"auth_profile": "DUP", "region": "us-ashburn-1"}
        client.post("/v1/oci", json=payload, headers=HEADERS)
        response = client.post("/v1/oci", json=payload, headers=HEADERS)
        assert response.status_code == 409

    def test_create_invalid_name_returns_422(self, app_client):
        """Profile name must match allowed pattern."""
        client = app_client()
        response = client.post("/v1/oci", json={"auth_profile": "123bad"}, headers=HEADERS)
        assert response.status_code == 422

    def test_create_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.post("/v1/oci", json={"auth_profile": "test"})
        assert response.status_code == 403


class TestGetOCIProfile:
    """GET /v1/oci/{profile}"""

    def test_get_existing(self, app_client):
        """Retrieve a created profile."""
        client = app_client()
        client.post("/v1/oci", json={"auth_profile": "GET", "region": "us-phoenix-1"}, headers=HEADERS)
        response = client.get("/v1/oci/GET", headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["auth_profile"] == "GET"
        assert response.json()["region"] == "us-phoenix-1"

    def test_get_missing_returns_404(self, app_client):
        """Unknown profile returns 404."""
        client = app_client()
        response = client.get("/v1/oci/nonexistent", headers=HEADERS)
        assert response.status_code == 404

    def test_get_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.get("/v1/oci/TEST")
        assert response.status_code == 403


class TestUpdateOCIProfile:
    """PUT /v1/oci/{profile}"""

    def test_update_existing(self, app_client):
        """Successfully update an existing profile."""
        client = app_client()
        client.post("/v1/oci", json={"auth_profile": "UPD", "region": "us-ashburn-1"}, headers=HEADERS)
        response = client.put("/v1/oci/UPD", json={"region": "us-phoenix-1"}, headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["region"] == "us-phoenix-1"

    def test_update_missing_returns_404(self, app_client):
        """Unknown profile returns 404."""
        client = app_client()
        response = client.put("/v1/oci/nonexistent", json={"region": "x"}, headers=HEADERS)
        assert response.status_code == 404

    def test_update_partial(self, app_client):
        """Partial update preserves unset fields."""
        client = app_client()
        client.post(
            "/v1/oci",
            json={"auth_profile": "PARTIAL", "region": "us-ashburn-1", "tenancy": "ocid1.tenancy.oc1..x"},
            headers=HEADERS,
        )
        response = client.put("/v1/oci/PARTIAL", json={"region": "us-phoenix-1"}, headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["region"] == "us-phoenix-1"
        assert data["tenancy"] == "ocid1.tenancy.oc1..x"

    def test_update_null_non_nullable_fields_preserves_defaults(self, app_client):
        """Sending null for non-nullable fields (authentication, log_requests, etc.) must not crash."""
        client = app_client()
        client.post(
            "/v1/oci",
            json={"auth_profile": "NULLTEST", "authentication": "api_key", "log_requests": True},
            headers=HEADERS,
        )
        response = client.put(
            "/v1/oci/NULLTEST",
            json={"authentication": None, "log_requests": None, "additional_user_agent": None},
            headers=HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        # Non-nullable fields keep their previous values rather than becoming null
        assert data["authentication"] == "api_key"
        assert data["log_requests"] is True
        assert data["additional_user_agent"] == ""

    def test_update_null_nullable_fields_clears_them(self, app_client):
        """Sending null for nullable fields (region, tenancy, etc.) clears the value."""
        client = app_client()
        client.post(
            "/v1/oci",
            json={"auth_profile": "NULLCLEAR", "region": "us-ashburn-1", "tenancy": "ocid1.tenancy.oc1..x"},
            headers=HEADERS,
        )
        response = client.put(
            "/v1/oci/NULLCLEAR",
            json={"region": None, "tenancy": None},
            headers=HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["region"] is None
        assert data["tenancy"] is None

    def test_update_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.put("/v1/oci/TEST", json={"region": "x"})
        assert response.status_code == 403


class TestDeleteOCIProfile:
    """DELETE /v1/oci/{profile}"""

    def test_delete_existing_returns_204(self, app_client):
        """Successfully delete a profile."""
        client = app_client()
        client.post("/v1/oci", json={"auth_profile": "DEL"}, headers=HEADERS)
        response = client.delete("/v1/oci/DEL", headers=HEADERS)
        assert response.status_code == 204
        # Verify it's gone
        response = client.get("/v1/oci/DEL", headers=HEADERS)
        assert response.status_code == 404

    def test_delete_missing_returns_404(self, app_client):
        """Unknown profile returns 404."""
        client = app_client()
        response = client.delete("/v1/oci/nonexistent", headers=HEADERS)
        assert response.status_code == 404

    def test_delete_rejects_missing_api_key(self, app_client):
        """Request without API key returns 403."""
        client = app_client()
        response = client.delete("/v1/oci/TEST")
        assert response.status_code == 403


class TestSecretsNeverExposed:
    """Sensitive fields must never appear in any response body."""

    def test_list_no_secrets(self, app_client):
        """List endpoint excludes key and pass_phrase."""
        client = app_client()
        client.post(
            "/v1/oci",
            json={"auth_profile": "SECRET", "key": "pem-secret", "pass_phrase": "phrase-secret"},
            headers=HEADERS,
        )
        response = client.get("/v1/oci", headers=HEADERS)
        text = response.text
        assert "pem-secret" not in text
        assert "phrase-secret" not in text
        for profile in response.json():
            assert "key" not in profile
            assert "pass_phrase" not in profile

    def test_get_no_secrets(self, app_client):
        """Get endpoint excludes key and pass_phrase."""
        client = app_client()
        client.post(
            "/v1/oci",
            json={"auth_profile": "SECRET2", "key": "pem-secret", "pass_phrase": "phrase-secret"},
            headers=HEADERS,
        )
        response = client.get("/v1/oci/SECRET2", headers=HEADERS)
        data = response.json()
        assert "key" not in data
        assert "pass_phrase" not in data
        assert "pem-secret" not in response.text
        assert "phrase-secret" not in response.text
