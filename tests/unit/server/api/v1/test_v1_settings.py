"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/settings.py
Tests for client settings management endpoints.
"""

from unittest.mock import patch, MagicMock
from io import BytesIO
import json
import pytest
from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse

from server.api.v1 import settings


class TestSettingsGet:
    """Tests for the settings_get endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.get_client")
    async def test_settings_get_returns_client_settings(self, mock_get_client, make_settings):
        """settings_get should return client settings."""
        client_settings = make_settings(client="test_client")
        mock_get_client.return_value = client_settings

        mock_request = MagicMock()

        result = await settings.settings_get(
            request=mock_request, client="test_client", full_config=False, incl_sensitive=False, incl_readonly=False
        )

        assert result == client_settings
        mock_get_client.assert_called_once_with("test_client")

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.get_client")
    async def test_settings_get_raises_404_when_not_found(self, mock_get_client):
        """settings_get should raise 404 when client not found."""
        mock_get_client.side_effect = ValueError("Client not found")

        mock_request = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await settings.settings_get(
                request=mock_request,
                client="nonexistent",
                full_config=False,
                incl_sensitive=False,
                incl_readonly=False,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.get_client")
    @patch("server.api.v1.settings.utils_settings.get_server")
    async def test_settings_get_full_config(self, mock_get_server, mock_get_client, make_settings, mock_fastmcp):
        """settings_get should return full config when requested."""
        client_settings = make_settings(client="test_client")
        mock_get_client.return_value = client_settings
        mock_get_server.return_value = {
            "database_configs": [],
            "model_configs": [],
            "oci_configs": [],
            "prompt_configs": [],
        }

        mock_request = MagicMock()
        mock_request.app.state.fastmcp_app = mock_fastmcp

        result = await settings.settings_get(
            request=mock_request, client="test_client", full_config=True, incl_sensitive=False, incl_readonly=False
        )

        assert isinstance(result, JSONResponse)
        mock_get_server.assert_called_once()


class TestSettingsUpdate:
    """Tests for the settings_update endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.update_client")
    async def test_settings_update_success(self, mock_update_client, make_settings):
        """settings_update should update and return settings."""
        updated_settings = make_settings(client="test_client", temperature=0.9)
        mock_update_client.return_value = updated_settings

        payload = make_settings(client="test_client", temperature=0.9)

        result = await settings.settings_update(payload=payload, client="test_client")

        assert result == updated_settings
        mock_update_client.assert_called_once_with(payload, "test_client")

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.update_client")
    async def test_settings_update_raises_404_when_not_found(self, mock_update_client, make_settings):
        """settings_update should raise 404 when client not found."""
        mock_update_client.side_effect = ValueError("Client not found")

        payload = make_settings(client="nonexistent")

        with pytest.raises(HTTPException) as exc_info:
            await settings.settings_update(payload=payload, client="nonexistent")

        assert exc_info.value.status_code == 404


class TestSettingsCreate:
    """Tests for the settings_create endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.create_client")
    async def test_settings_create_success(self, mock_create_client, make_settings):
        """settings_create should create and return new settings."""
        new_settings = make_settings(client="new_client")
        mock_create_client.return_value = new_settings

        result = await settings.settings_create(client="new_client")

        assert result == new_settings
        mock_create_client.assert_called_once_with("new_client")

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.create_client")
    async def test_settings_create_raises_409_when_exists(self, mock_create_client):
        """settings_create should raise 409 when client already exists."""
        mock_create_client.side_effect = ValueError("Client already exists")

        with pytest.raises(HTTPException) as exc_info:
            await settings.settings_create(client="existing_client")

        assert exc_info.value.status_code == 409


class TestLoadSettingsFromFile:
    """Tests for the load_settings_from_file endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.create_client")
    @patch("server.api.v1.settings.utils_settings.load_config_from_json_data")
    async def test_load_settings_from_file_success(self, mock_load_config, mock_create_client):
        """load_settings_from_file should load config from JSON file."""
        mock_create_client.return_value = MagicMock()
        mock_load_config.return_value = None

        config_data = {"client_settings": {"client": "test"}, "database_configs": []}
        file_content = json.dumps(config_data).encode()
        mock_file = UploadFile(file=BytesIO(file_content), filename="config.json")

        result = await settings.load_settings_from_file(client="test_client", file=mock_file)

        assert result["message"] == "Configuration loaded successfully."
        mock_load_config.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.create_client")
    async def test_load_settings_from_file_wrong_extension(self, mock_create_client):
        """load_settings_from_file should raise error for non-JSON files.

        Note: Due to the generic exception handler in the source code,
        HTTPException(400) is caught and wrapped in HTTPException(500).
        """
        mock_create_client.return_value = MagicMock()

        mock_file = UploadFile(file=BytesIO(b"data"), filename="config.txt")

        with pytest.raises(HTTPException) as exc_info:
            await settings.load_settings_from_file(client="test_client", file=mock_file)

        # The 400 HTTPException gets caught by generic exception handler and wrapped in 500
        assert exc_info.value.status_code == 500
        assert "JSON" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.create_client")
    async def test_load_settings_from_file_invalid_json(self, mock_create_client):
        """load_settings_from_file should raise 400 for invalid JSON."""
        mock_create_client.return_value = MagicMock()

        mock_file = UploadFile(file=BytesIO(b"not valid json"), filename="config.json")

        with pytest.raises(HTTPException) as exc_info:
            await settings.load_settings_from_file(client="test_client", file=mock_file)

        assert exc_info.value.status_code == 400
        assert "Invalid JSON" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.create_client")
    @patch("server.api.v1.settings.utils_settings.load_config_from_json_data")
    async def test_load_settings_from_file_key_error(self, mock_load_config, mock_create_client):
        """load_settings_from_file should raise 400 on KeyError."""
        mock_create_client.return_value = MagicMock()
        mock_load_config.side_effect = KeyError("Missing required key")

        config_data = {"incomplete": "data"}
        file_content = json.dumps(config_data).encode()
        mock_file = UploadFile(file=BytesIO(file_content), filename="config.json")

        with pytest.raises(HTTPException) as exc_info:
            await settings.load_settings_from_file(client="test_client", file=mock_file)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.create_client")
    @patch("server.api.v1.settings.utils_settings.load_config_from_json_data")
    async def test_load_settings_from_file_handles_existing_client(self, mock_load_config, mock_create_client):
        """load_settings_from_file should continue if client already exists."""
        mock_create_client.side_effect = ValueError("Client already exists")
        mock_load_config.return_value = None

        config_data = {"client_settings": {"client": "test"}}
        file_content = json.dumps(config_data).encode()
        mock_file = UploadFile(file=BytesIO(file_content), filename="config.json")

        result = await settings.load_settings_from_file(client="test_client", file=mock_file)

        assert result["message"] == "Configuration loaded successfully."


class TestLoadSettingsFromJson:
    """Tests for the load_settings_from_json endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.create_client")
    @patch("server.api.v1.settings.utils_settings.load_config_from_json_data")
    async def test_load_settings_from_json_success(self, mock_load_config, mock_create_client, make_configuration):
        """load_settings_from_json should load config from JSON payload."""
        mock_create_client.return_value = MagicMock()
        mock_load_config.return_value = None

        payload = make_configuration(client="test_client")

        result = await settings.load_settings_from_json(client="test_client", payload=payload)

        assert result["message"] == "Configuration loaded successfully."
        mock_load_config.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.create_client")
    @patch("server.api.v1.settings.utils_settings.load_config_from_json_data")
    async def test_load_settings_from_json_key_error(self, mock_load_config, mock_create_client, make_configuration):
        """load_settings_from_json should raise 400 on KeyError."""
        mock_create_client.return_value = MagicMock()
        mock_load_config.side_effect = KeyError("Missing required key")

        payload = make_configuration(client="test_client")

        with pytest.raises(HTTPException) as exc_info:
            await settings.load_settings_from_json(client="test_client", payload=payload)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("server.api.v1.settings.utils_settings.create_client")
    @patch("server.api.v1.settings.utils_settings.load_config_from_json_data")
    async def test_load_settings_from_json_handles_existing_client(
        self, mock_load_config, mock_create_client, make_configuration
    ):
        """load_settings_from_json should continue if client already exists."""
        mock_create_client.side_effect = ValueError("Client already exists")
        mock_load_config.return_value = None

        payload = make_configuration(client="test_client")

        result = await settings.load_settings_from_json(client="test_client", payload=payload)

        assert result["message"] == "Configuration loaded successfully."


class TestIncludeParams:  # pylint: disable=protected-access
    """Tests for the include parameter dependencies."""

    def test_incl_sensitive_param_default(self):
        """_incl_sensitive_param should default to False."""
        result = settings._incl_sensitive_param(incl_sensitive=False)
        assert result is False

    def test_incl_sensitive_param_true(self):
        """_incl_sensitive_param should return True when set."""
        result = settings._incl_sensitive_param(incl_sensitive=True)
        assert result is True

    def test_incl_readonly_param_default(self):
        """_incl_readonly_param should default to False."""
        result = settings._incl_readonly_param(incl_readonly=False)
        assert result is False

    def test_incl_readonly_param_true(self):
        """_incl_readonly_param should return True when set."""
        result = settings._incl_readonly_param(incl_readonly=True)
        assert result is True
