"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

import pytest
from common.schema import (
    Settings,
    LargeLanguageSettings,
    PromptSettings,
    VectorSearchSettings,
    SelectAISettings,
    OciSettings,
)


#############################################################################
# Test AuthN required and Valid
#############################################################################
class TestInvalidAuthEndpoints:
    """Test endpoints without Headers and Invalid AuthN"""

    @pytest.mark.parametrize(
        "auth_type, status_code",
        [
            pytest.param("no_auth", 403, id="no_auth"),
            pytest.param("invalid_auth", 401, id="invalid_auth"),
        ],
    )
    @pytest.mark.parametrize(
        "endpoint, api_method",
        [
            pytest.param("/v1/settings", "get", id="settings_get"),
            pytest.param("/v1/settings", "patch", id="settings_update"),
            pytest.param("/v1/settings", "post", id="settings_create"),
        ],
    )
    def test_endpoints(self, client, auth_headers, endpoint, api_method, auth_type, status_code):
        """Test endpoints require valide authentication"""
        response = getattr(client, api_method)(endpoint, headers=auth_headers[auth_type])
        assert response.status_code == status_code


#############################################################################
# Endpoints Test
#############################################################################
class TestEndpoints:
    """Test Endpoints"""

    def test_settings_get(self, client, auth_headers):
        """Test getting settings for a client"""
        # Test getting settings for the test client
        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "default"})
        assert response.status_code == 200
        settings = response.json()

        # Verify the response contains the expected structure
        assert settings["client"] == "default"
        assert "ll_model" in settings
        assert "prompts" in settings
        assert "vector_search" in settings
        assert "selectai" in settings
        assert "oci" in settings

    def test_settings_get_nonexistent_client(self, client, auth_headers):
        """Test getting settings for a non-existent client"""
        response = client.get(
            "/v1/settings", headers=auth_headers["valid_auth"], params={"client": "non_existant_client"}
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_settings_create(self, client, auth_headers):
        """Test creating settings for a new client"""
        new_client = "new_test_client"

        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "default"})
        assert response.status_code == 200
        default_settings = response.json()

        # Create new client settings
        response = client.post("/v1/settings", headers=auth_headers["valid_auth"], params={"client": new_client})
        assert response.status_code == 200

        # Verify we can retrieve the settings
        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": new_client})
        assert response.status_code == 200
        new_client_settings = response.json()
        assert new_client_settings["client"] == new_client

        # Remove the client key to compare the rest
        del default_settings["client"]
        del new_client_settings["client"]
        assert default_settings == new_client_settings

    def test_settings_create_existing_client(self, client, auth_headers) -> None:
        """Test creating settings for an existing client"""
        response = client.post("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "default"})
        assert response.status_code == 409
        assert response.json() == {"detail": "Settings: client default already exists."}

    def test_settings_update(self, client, auth_headers):
        """Test updating settings for a client"""
        # First get the current settings
        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "default"})
        assert response.status_code == 200
        old_settings = response.json()

        # Modify some settings
        updated_settings = Settings(
            client="default",
            ll_model=LargeLanguageSettings(model="updated-model", chat_history=False),
            prompts=PromptSettings(ctx="Updated Context", sys="Updated System"),
            vector_search=VectorSearchSettings(enabled=True, grading=False, search_type="Similarity", top_k=5),
            selectai=SelectAISettings(enabled=True),
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
        assert new_settings["prompts"]["ctx"] == "Updated Context"
        assert new_settings["prompts"]["sys"] == "Updated System"
        assert new_settings["vector_search"]["enabled"] is True
        assert new_settings["vector_search"]["grading"] is False
        assert new_settings["vector_search"]["top_k"] == 5
        assert new_settings["selectai"]["enabled"] is True
        assert new_settings["oci"]["auth_profile"] == "UPDATED"

    def test_settings_copy(self, client, auth_headers):
        """Test copying settings for a client"""
        # First get the current settings for the client
        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "default"})
        assert response.status_code == 200
        default_settings = response.json()

        response = client.get("/v1/settings", headers=auth_headers["valid_auth"], params={"client": "server"})
        assert response.status_code == 200
        old_server_settings = response.json()

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
        assert old_server_settings != new_server_settings

        del new_server_settings["client"]
        del default_settings["client"]
        assert new_server_settings == default_settings

    def test_settings_update_nonexistent_client(self, client, auth_headers):
        """Test updating settings for a non-existent client"""
        updated_settings = Settings(client="nonexistent_client", ll_model=LargeLanguageSettings(model="test-model"))

        response = client.patch(
            "/v1/settings",
            headers=auth_headers["valid_auth"],
            json=updated_settings.model_dump(),
            params={"client": "nonexistent_client"},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Settings: client nonexistent_client not found."}

    @pytest.mark.parametrize("app_server", ["/tmp/settings.json"], indirect=True)
    def test_user_supplied_settings(self, app_server):
        """Test the copy_user_settings function with a successful API call"""
        assert app_server is not None

        # Test Logic
