"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the GET /settings endpoint.
"""
# spell-checker: disable
# pylint: disable=redefined-outer-name

API_KEY = "test-secret"
HEADERS = {"X-API-Key": API_KEY}


class TestGetSettings:
    """Tests for GET /v1/settings."""

    def test_requires_auth(self, app_client):
        """Request without API key is rejected."""
        client = app_client({"AIO_API_KEY": API_KEY})
        response = client.get("/v1/settings")
        assert response.status_code == 403

    def test_returns_settings(self, app_client):
        """Returns non-secret settings by default."""
        client = app_client({"AIO_API_KEY": API_KEY, "AIO_LOG_LEVEL": "DEBUG"})
        response = client.get("/v1/settings", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["log_level"] == "DEBUG"
        assert data["server_port"] == 8000
        # Secrets omitted by default
        assert "api_key" not in data or data["api_key"] is None
        assert "db_password" not in data or data["db_password"] is None
        assert "db_wallet_password" not in data or data["db_wallet_password"] is None

    def test_include_secrets(self, app_client):
        """With include_secrets=true, secret fields are present."""
        client = app_client({"AIO_API_KEY": API_KEY, "AIO_DB_PASSWORD": "s3cret"})
        response = client.get(
            "/v1/settings", headers=HEADERS, params={"include_secrets": True}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["api_key"] == API_KEY
        assert data["db_password"] == "s3cret"

    def test_non_secret_fields_always_present(self, app_client):
        """Non-secret fields are always returned regardless of include_secrets."""
        client = app_client({"AIO_API_KEY": API_KEY, "AIO_DB_DSN": "localhost/orcl"})
        response = client.get("/v1/settings", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["env"] == "dev"
        assert data["db_dsn"] == "localhost/orcl"
        assert "db_username" in data
        assert "db_wallet_location" in data
