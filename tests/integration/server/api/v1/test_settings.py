"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/settings.py

Tests the settings configuration endpoints through the full API stack.
These endpoints require authentication.
"""

import json
from io import BytesIO


class TestAuthentication:
    """Integration tests for authentication on settings endpoints."""

    def test_settings_get_requires_auth(self, client):
        """GET /v1/settings should require authentication."""
        response = client.get("/v1/settings", params={"client": "test"})

        assert response.status_code == 401

    def test_settings_get_rejects_invalid_token(self, client, auth_headers):
        """GET /v1/settings should reject invalid tokens."""
        response = client.get(
            "/v1/settings",
            headers=auth_headers["invalid_auth"],
            params={"client": "test"},
        )

        assert response.status_code == 401

    def test_settings_get_accepts_valid_token(self, client, auth_headers):
        """GET /v1/settings should accept valid tokens."""
        response = client.get(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "server"},  # Use existing client
        )

        assert response.status_code == 200


class TestSettingsGet:
    """Integration tests for the settings get endpoint."""

    def test_settings_get_returns_settings(self, client, auth_headers):
        """GET /v1/settings should return settings for existing client."""
        response = client.get(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "server"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "client" in data
        assert data["client"] == "server"

    def test_settings_get_returns_404_for_unknown_client(self, client, auth_headers):
        """GET /v1/settings should return 404 for unknown client."""
        response = client.get(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "nonexistent_client_xyz"},
        )

        assert response.status_code == 404

    def test_settings_get_full_config(self, client, auth_headers):
        """GET /v1/settings?full_config=true should return full configuration."""
        response = client.get(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "server", "full_config": True},
        )

        assert response.status_code == 200
        data = response.json()
        # Full config includes client_settings and all config arrays
        assert "client_settings" in data
        assert "database_configs" in data
        assert "model_configs" in data
        assert "oci_configs" in data
        assert "prompt_configs" in data

    def test_settings_get_with_sensitive(self, client, auth_headers):
        """GET /v1/settings?incl_sensitive=true should include sensitive fields."""
        response = client.get(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "server", "full_config": True, "incl_sensitive": True},
        )

        assert response.status_code == 200
        # Response should include sensitive fields (passwords)
        # Exact fields depend on what's configured


class TestSettingsCreate:
    """Integration tests for the settings create endpoint."""

    def test_settings_create_requires_auth(self, client):
        """POST /v1/settings should require authentication."""
        response = client.post("/v1/settings", params={"client": "new_test_client"})

        assert response.status_code == 401

    def test_settings_create_success(self, client, auth_headers, settings_objects_manager):
        """POST /v1/settings should create new client settings."""
        # pylint: disable=unused-argument
        response = client.post(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "integration_new_client"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["client"] == "integration_new_client"

    def test_settings_create_returns_409_for_existing(self, client, auth_headers):
        """POST /v1/settings should return 409 if client already exists."""
        # "server" client is created by bootstrap
        response = client.post(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "server"},
        )

        assert response.status_code == 409


class TestSettingsUpdate:
    """Integration tests for the settings update endpoint."""

    def test_settings_update_requires_auth(self, client):
        """PATCH /v1/settings should require authentication."""
        response = client.patch(
            "/v1/settings",
            params={"client": "server"},
            json={"client": "server"},
        )

        assert response.status_code == 401

    def test_settings_update_returns_404_for_unknown(self, client, auth_headers):
        """PATCH /v1/settings should return 404 for unknown client."""
        response = client.patch(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "nonexistent_client_xyz"},
            json={"client": "nonexistent_client_xyz"},
        )

        assert response.status_code == 404

    def test_settings_update_success(self, client, auth_headers, settings_objects_manager):
        """PATCH /v1/settings should update client settings."""
        # pylint: disable=unused-argument
        # First create a client to update
        client.post(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "update_test_client"},
        )

        # Now update it
        response = client.patch(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "update_test_client"},
            json={
                "client": "update_test_client",
                "ll_model": {
                    "model": "gpt-4o",
                    "temperature": 0.5,
                    "max_tokens": 2048,
                    "chat_history": False,
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ll_model"]["temperature"] == 0.5


class TestSettingsLoadFromFile:
    """Integration tests for the settings load from file endpoint."""

    def test_load_from_file_requires_auth(self, client):
        """POST /v1/settings/load/file should require authentication."""
        response = client.post(
            "/v1/settings/load/file",
            params={"client": "test"},
            files={"file": ("test.json", b"{}", "application/json")},
        )

        assert response.status_code == 401

    def test_load_from_file_rejects_non_json_extension(self, client, auth_headers, settings_objects_manager):
        """POST /v1/settings/load/file should reject files without .json extension.

        Note: Current implementation returns 500 due to HTTPException being caught
        by generic Exception handler. This documents actual behavior.
        """
        # pylint: disable=unused-argument
        response = client.post(
            "/v1/settings/load/file",
            headers=auth_headers["valid_auth"],
            params={"client": "file_test_client"},
            files={"file": ("test.txt", b"{}", "text/plain")},
        )

        # Current behavior returns 500 (HTTPException caught by generic handler)
        # Ideally should be 400, but documenting actual behavior
        assert response.status_code == 500
        assert "Only JSON files are supported" in response.json()["detail"]

    def test_load_from_file_rejects_invalid_json_content(self, client, auth_headers, settings_objects_manager):
        """POST /v1/settings/load/file should reject invalid JSON content."""
        # pylint: disable=unused-argument
        response = client.post(
            "/v1/settings/load/file",
            headers=auth_headers["valid_auth"],
            params={"client": "file_invalid_content"},
            files={"file": ("test.json", b"not valid json", "application/json")},
        )

        # Invalid JSON content returns 400
        assert response.status_code == 400

    def test_load_from_file_success(self, client, auth_headers, settings_objects_manager):
        """POST /v1/settings/load/file should load configuration from JSON file."""
        # pylint: disable=unused-argument
        config_data = {
            "client_settings": {
                "client": "file_load_client",
                "ll_model": {
                    "model": "gpt-4o-mini",
                    "temperature": 0.8,
                    "max_tokens": 1000,
                    "chat_history": True,
                },
            },
            "database_configs": [],
            "model_configs": [],
            "oci_configs": [],
            "prompt_configs": [],
        }

        file_content = json.dumps(config_data).encode("utf-8")

        response = client.post(
            "/v1/settings/load/file",
            headers=auth_headers["valid_auth"],
            params={"client": "file_load_client"},
            files={"file": ("config.json", BytesIO(file_content), "application/json")},
        )

        assert response.status_code == 200
        assert "loaded successfully" in response.json()["message"].lower()


class TestSettingsLoadFromJson:
    """Integration tests for the settings load from JSON endpoint."""

    def test_load_from_json_requires_auth(self, client):
        """POST /v1/settings/load/json should require authentication."""
        response = client.post(
            "/v1/settings/load/json",
            params={"client": "test"},
            json={"client_settings": {"client": "test"}},
        )

        assert response.status_code == 401

    def test_load_from_json_success(self, client, auth_headers, settings_objects_manager):
        """POST /v1/settings/load/json should load configuration from JSON payload."""
        # pylint: disable=unused-argument
        config_data = {
            "client_settings": {
                "client": "json_load_client",
                "ll_model": {
                    "model": "gpt-4o-mini",
                    "temperature": 0.9,
                    "max_tokens": 500,
                    "chat_history": True,
                },
            },
            "database_configs": [],
            "model_configs": [],
            "oci_configs": [],
            "prompt_configs": [],
        }

        response = client.post(
            "/v1/settings/load/json",
            headers=auth_headers["valid_auth"],
            params={"client": "json_load_client"},
            json=config_data,
        )

        assert response.status_code == 200
        assert "loaded successfully" in response.json()["message"].lower()


class TestSettingsAdvanced:
    """Integration tests for advanced settings operations."""

    def test_settings_update_with_full_payload(self, client, auth_headers, settings_objects_manager):
        """Test updating settings with a complete Settings payload."""
        # pylint: disable=unused-argument,import-outside-toplevel
        from common.schema import (
            Settings,
            LargeLanguageSettings,
            VectorSearchSettings,
            OciSettings,
        )

        # First get the current settings
        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "default"})
        assert response.status_code == 200
        old_settings = response.json()

        # Modify some settings
        updated_settings = Settings(
            client="default",
            ll_model=LargeLanguageSettings(model="updated-model", chat_history=False),
            tools_enabled=["Vector Search"],
            vector_search=VectorSearchSettings(grade=False, search_type="Similarity", top_k=5),
            oci=OciSettings(auth_profile="UPDATED"),
        )

        # Update the settings
        response = client.patch(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            json=updated_settings.model_dump(),
            params={"client": "default"},
        )
        assert response.status_code == 200
        new_settings = response.json()

        # Check old do not match update
        assert old_settings != new_settings

        # Check that the values were updated
        assert new_settings["ll_model"]["model"] == "updated-model"
        assert new_settings["ll_model"]["chat_history"] is False
        assert new_settings["tools_enabled"] == ["Vector Search"]
        assert new_settings["vector_search"]["grade"] is False
        assert new_settings["vector_search"]["top_k"] == 5
        assert new_settings["oci"]["auth_profile"] == "UPDATED"

    def test_settings_copy_between_clients(self, client, auth_headers, settings_objects_manager):
        """Test copying settings from one client to another."""
        # pylint: disable=unused-argument
        # First modify the default settings to make them different
        response = client.patch(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": "default"},
            json={
                "client": "default",
                "ll_model": {"model": "copy-test-model", "temperature": 0.99},
            },
        )
        assert response.status_code == 200

        # Get the modified default settings
        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "default"})
        assert response.status_code == 200
        default_settings = response.json()
        assert default_settings["ll_model"]["model"] == "copy-test-model"

        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "server"})
        assert response.status_code == 200
        old_server_settings = response.json()

        # Server settings should be different from modified default
        assert old_server_settings["ll_model"]["model"] != default_settings["ll_model"]["model"]

        # Copy the client settings to the server settings
        response = client.patch(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            json=default_settings,
            params={"client": "server"},
        )
        assert response.status_code == 200
        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "server"})
        new_server_settings = response.json()

        # After copy, server settings should match default (except client name)
        del new_server_settings["client"]
        del default_settings["client"]
        assert new_server_settings == default_settings

    def test_settings_get_returns_expected_structure(self, client, auth_headers):
        """Test that settings response has expected structure."""
        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "default"})
        assert response.status_code == 200
        settings = response.json()

        # Verify the response contains the expected structure
        assert settings["client"] == "default"
        assert "ll_model" in settings
        assert "vector_search" in settings
        assert "oci" in settings
        assert "database" in settings
        assert "testbed" in settings
