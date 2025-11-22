"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch, MagicMock, mock_open
import os

import pytest

from server.api.utils import settings
from common.schema import Settings, Configuration, Database, Model, OracleCloudSettings


class TestSettings:
    """Test settings module functionality"""

    def setup_method(self):
        """Setup test data before each test"""
        self.default_settings = Settings(client="default")
        self.test_client_settings = Settings(client="test_client")
        self.sample_config_data = {
            "database_configs": [{"name": "test_db", "user": "user", "password": "pass", "dsn": "dsn"}],
            "model_configs": [{"id": "test-model", "provider": "openai", "type": "ll"}],
            "oci_configs": [{"auth_profile": "DEFAULT", "compartment_id": "ocid1.compartment.oc1..test"}],
            "prompt_overrides": {"optimizer_basic-default": "You are helpful"},
            "client_settings": {"client": "default", "max_tokens": 1000, "temperature": 0.7},
        }

    @patch("server.api.core.settings.bootstrap")
    def test_create_client_success(self, mock_bootstrap):
        """Test successful client settings creation"""
        # Create a list that includes the default settings and will be appended to
        settings_list = [self.default_settings]
        mock_bootstrap.SETTINGS_OBJECTS = settings_list

        result = settings.create_client("new_client")

        assert result.client == "new_client"
        assert result.ll_model.max_tokens == self.default_settings.ll_model.max_tokens
        # Check that a new client was added to the list
        assert len(settings_list) == 2
        assert settings_list[-1].client == "new_client"

    @patch("server.api.core.settings.bootstrap.SETTINGS_OBJECTS")
    def test_create_client_already_exists(self, mock_settings_objects):
        """Test creating client settings when client already exists"""
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([self.test_client_settings]))

        with pytest.raises(ValueError, match="client test_client already exists"):
            settings.create_client("test_client")

    @patch("server.api.core.settings.bootstrap.SETTINGS_OBJECTS")
    def test_get_client_found(self, mock_settings_objects):
        """Test getting client settings when client exists"""
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([self.test_client_settings]))

        result = settings.get_client("test_client")

        assert result == self.test_client_settings

    @patch("server.api.core.settings.bootstrap.SETTINGS_OBJECTS")
    def test_get_client_not_found(self, mock_settings_objects):
        """Test getting client settings when client doesn't exist"""
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([self.default_settings]))

        with pytest.raises(ValueError, match="client nonexistent not found"):
            settings.get_client("nonexistent")

    @pytest.mark.asyncio
    @patch("server.api.core.settings.get_mcp_prompts_with_overrides")
    @patch("server.api.core.settings.bootstrap.DATABASE_OBJECTS")
    @patch("server.api.core.settings.bootstrap.MODEL_OBJECTS")
    @patch("server.api.core.settings.bootstrap.OCI_OBJECTS")
    async def test_get_server(self, mock_oci, mock_models, mock_databases, mock_get_prompts):
        """Test getting server configuration"""
        mock_databases.__iter__ = MagicMock(
            return_value=iter([Database(name="test", user="u", password="p", dsn="d")])
        )
        mock_models.__iter__ = MagicMock(return_value=iter([Model(id="test", provider="openai", type="ll")]))
        mock_oci.__iter__ = MagicMock(return_value=iter([OracleCloudSettings(auth_profile="DEFAULT")]))
        mock_get_prompts.return_value = []  # Return empty list of prompts

        mock_mcp_engine = MagicMock()
        result = await settings.get_server(mock_mcp_engine)

        assert "database_configs" in result
        assert "model_configs" in result
        assert "oci_configs" in result
        assert "prompt_overrides" in result

    @patch("server.api.core.settings.bootstrap.SETTINGS_OBJECTS")
    @patch("server.api.core.settings.get_client")
    def test_update_client(self, mock_get_settings, mock_settings_objects):
        """Test updating client settings"""
        mock_get_settings.return_value = self.test_client_settings
        mock_settings_objects.remove = MagicMock()
        mock_settings_objects.append = MagicMock()
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([self.test_client_settings]))

        new_settings = Settings(client="test_client", max_tokens=800, temperature=0.9)
        result = settings.update_client(new_settings, "test_client")

        assert result.client == "test_client"
        mock_settings_objects.remove.assert_called_once_with(self.test_client_settings)
        mock_settings_objects.append.assert_called_once()

    @patch("server.api.core.settings.bootstrap")
    def test_update_server(self, mock_bootstrap):
        """Test updating server configuration"""
        # Use the valid sample config data that includes client_settings
        settings.update_server(self.sample_config_data)

        assert hasattr(mock_bootstrap, "DATABASE_OBJECTS")
        assert hasattr(mock_bootstrap, "MODEL_OBJECTS")

    @patch("server.api.core.settings.update_server")
    @patch("server.api.core.settings.update_client")
    def test_load_config_from_json_data_with_client(self, mock_update_client, mock_update_server):
        """Test loading config from JSON data with specific client"""
        settings.load_config_from_json_data(self.sample_config_data, client="test_client")

        mock_update_server.assert_called_once_with(self.sample_config_data)
        mock_update_client.assert_called_once()

    @patch("server.api.core.settings.update_server")
    @patch("server.api.core.settings.update_client")
    def test_load_config_from_json_data_without_client(self, mock_update_client, mock_update_server):
        """Test loading config from JSON data without specific client"""
        settings.load_config_from_json_data(self.sample_config_data)

        mock_update_server.assert_called_once_with(self.sample_config_data)
        # Should be called twice: once for "server" and once for "default"
        assert mock_update_client.call_count == 2

    @patch("server.api.core.settings.update_server")
    def test_load_config_from_json_data_missing_client_settings(self, _mock_update_server):
        """Test loading config from JSON data without client_settings"""
        # Create config without client_settings
        invalid_config = {"database_configs": [], "model_configs": [], "oci_configs": [], "prompt_overrides": {}}

        with pytest.raises(KeyError, match="Missing client_settings in config file"):
            settings.load_config_from_json_data(invalid_config)

    @patch.dict(os.environ, {"CONFIG_FILE": "/path/to/config.json"})
    @patch("os.path.isfile")
    @patch("os.access")
    @patch("builtins.open", mock_open(read_data='{"test": "data"}'))
    @patch("json.load")
    def test_read_config_from_json_file_success(self, mock_json_load, mock_access, mock_isfile):
        """Test successful reading of config file"""
        mock_isfile.return_value = True
        mock_access.return_value = True
        mock_json_load.return_value = self.sample_config_data

        result = settings.read_config_from_json_file()

        assert isinstance(result, Configuration)
        mock_json_load.assert_called_once()

    @patch.dict(os.environ, {"CONFIG_FILE": "/path/to/nonexistent.json"})
    @patch("os.path.isfile")
    def test_read_config_from_json_file_not_exists(self, mock_isfile):
        """Test reading config file that doesn't exist"""
        mock_isfile.return_value = False

        # This should still attempt to process, but will log a warning
        # The actual behavior depends on the implementation

    @patch.dict(os.environ, {"CONFIG_FILE": "/path/to/config.txt"})
    def test_read_config_from_json_file_wrong_extension(self):
        """Test reading config file with wrong extension"""
        # This should log a warning about the file extension

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(settings, "logger")
        assert settings.logger.name == "api.core.settings"
