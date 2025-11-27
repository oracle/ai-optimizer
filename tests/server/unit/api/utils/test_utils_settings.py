"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=protected-access import-error import-outside-toplevel

from unittest.mock import patch, MagicMock, mock_open
import os

import pytest

from server.api.utils import settings
from common.schema import Settings, Configuration, Database, Model, OracleCloudSettings


#####################################################
# Helper functions for test data
#####################################################
def make_default_settings():
    """Create default settings for tests"""
    return Settings(client="default")


def make_test_client_settings():
    """Create test client settings for tests"""
    return Settings(client="test_client")


def make_sample_config_data():
    """Create sample configuration data for tests"""
    return {
        "database_configs": [{"name": "test_db", "user": "user", "password": "pass", "dsn": "dsn"}],
        "model_configs": [{"id": "test-model", "provider": "openai", "type": "ll"}],
        "oci_configs": [{"auth_profile": "DEFAULT", "compartment_id": "ocid1.compartment.oc1..test"}],
        "prompt_overrides": {"optimizer_basic-default": "You are helpful"},
        "client_settings": {"client": "default", "max_tokens": 1000, "temperature": 0.7},
    }


#####################################################
# Client Settings Tests
#####################################################
class TestClientSettings:
    """Test client settings CRUD operations"""

    @patch("server.api.utils.settings.bootstrap")
    def test_create_client_success(self, mock_bootstrap):
        """Test successful client settings creation"""
        default_cfg = make_default_settings()
        settings_list = [default_cfg]
        mock_bootstrap.SETTINGS_OBJECTS = settings_list

        result = settings.create_client("new_client")

        assert result.client == "new_client"
        # Verify ll_model settings are copied from default
        result_ll_model = result.model_dump()["ll_model"]
        default_ll_model = default_cfg.model_dump()["ll_model"]
        assert result_ll_model["max_tokens"] == default_ll_model["max_tokens"]
        assert len(settings_list) == 2
        assert settings_list[-1].client == "new_client"

    @patch("server.api.utils.settings.bootstrap.SETTINGS_OBJECTS")
    def test_create_client_already_exists(self, mock_settings_objects):
        """Test creating client settings when client already exists"""
        test_cfg = make_test_client_settings()
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([test_cfg]))

        with pytest.raises(ValueError, match="client test_client already exists"):
            settings.create_client("test_client")

    @patch("server.api.utils.settings.bootstrap.SETTINGS_OBJECTS")
    def test_get_client_found(self, mock_settings_objects):
        """Test getting client settings when client exists"""
        test_cfg = make_test_client_settings()
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([test_cfg]))

        result = settings.get_client("test_client")

        assert result == test_cfg

    @patch("server.api.utils.settings.bootstrap.SETTINGS_OBJECTS")
    def test_get_client_not_found(self, mock_settings_objects):
        """Test getting client settings when client doesn't exist"""
        default_cfg = make_default_settings()
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([default_cfg]))

        with pytest.raises(ValueError, match="client nonexistent not found"):
            settings.get_client("nonexistent")

    @patch("server.api.utils.settings.bootstrap.SETTINGS_OBJECTS")
    @patch("server.api.utils.settings.get_client")
    def test_update_client(self, mock_get_settings, mock_settings_objects):
        """Test updating client settings"""
        test_cfg = make_test_client_settings()
        mock_get_settings.return_value = test_cfg
        mock_settings_objects.remove = MagicMock()
        mock_settings_objects.append = MagicMock()
        mock_settings_objects.__iter__ = MagicMock(return_value=iter([test_cfg]))

        new_settings = Settings(client="test_client", max_tokens=800, temperature=0.9)
        result = settings.update_client(new_settings, "test_client")

        assert result.client == "test_client"
        mock_settings_objects.remove.assert_called_once_with(test_cfg)
        mock_settings_objects.append.assert_called_once()


#####################################################
# Server Configuration Tests
#####################################################
class TestServerConfiguration:
    """Test server configuration operations"""

    @pytest.mark.asyncio
    @patch("server.api.utils.settings.get_mcp_prompts_with_overrides")
    @patch("server.api.utils.settings.bootstrap.DATABASE_OBJECTS")
    @patch("server.api.utils.settings.bootstrap.MODEL_OBJECTS")
    @patch("server.api.utils.settings.bootstrap.OCI_OBJECTS")
    async def test_get_server(self, mock_oci, mock_models, mock_databases, mock_get_prompts):
        """Test getting server configuration"""
        mock_databases.__iter__ = MagicMock(
            return_value=iter([Database(name="test", user="u", password="p", dsn="d")])
        )
        mock_models.__iter__ = MagicMock(return_value=iter([Model(id="test", provider="openai", type="ll")]))
        mock_oci.__iter__ = MagicMock(return_value=iter([OracleCloudSettings(auth_profile="DEFAULT")]))
        mock_get_prompts.return_value = []

        mock_mcp_engine = MagicMock()
        result = await settings.get_server(mock_mcp_engine)

        assert "database_configs" in result
        assert "model_configs" in result
        assert "oci_configs" in result
        assert "prompt_configs" in result

    @patch("server.api.utils.settings.bootstrap")
    def test_update_server(self, mock_bootstrap):
        """Test updating server configuration"""
        mock_bootstrap.DATABASE_OBJECTS = []
        mock_bootstrap.MODEL_OBJECTS = []
        mock_bootstrap.OCI_OBJECTS = []

        settings.update_server(make_sample_config_data())

        assert hasattr(mock_bootstrap, "DATABASE_OBJECTS")
        assert hasattr(mock_bootstrap, "MODEL_OBJECTS")

    @patch("server.api.utils.settings.bootstrap")
    def test_update_server_mutates_lists_not_replaces(self, mock_bootstrap):
        """Test that update_server mutates existing lists rather than replacing them.

        This is critical because other modules import these lists directly
        (e.g., `from server.bootstrap.bootstrap import DATABASE_OBJECTS`).
        If we replace the list, those modules would hold stale references.
        """
        original_db_list = []
        original_model_list = []
        original_oci_list = []

        mock_bootstrap.DATABASE_OBJECTS = original_db_list
        mock_bootstrap.MODEL_OBJECTS = original_model_list
        mock_bootstrap.OCI_OBJECTS = original_oci_list

        settings.update_server(make_sample_config_data())

        # Verify the lists are the SAME objects (mutated, not replaced)
        assert mock_bootstrap.DATABASE_OBJECTS is original_db_list, "DATABASE_OBJECTS was replaced instead of mutated"
        assert mock_bootstrap.MODEL_OBJECTS is original_model_list, "MODEL_OBJECTS was replaced instead of mutated"
        assert mock_bootstrap.OCI_OBJECTS is original_oci_list, "OCI_OBJECTS was replaced instead of mutated"

        # Verify the lists now contain the new data
        assert len(original_db_list) == 1
        assert original_db_list[0].name == "test_db"
        assert len(original_model_list) == 1
        assert original_model_list[0].id == "test-model"
        assert len(original_oci_list) == 1
        assert original_oci_list[0].auth_profile == "DEFAULT"


#####################################################
# Config Loading Tests
#####################################################
class TestConfigLoading:
    """Test configuration loading operations"""

    @patch("server.api.utils.settings.update_server")
    @patch("server.api.utils.settings.update_client")
    def test_load_config_from_json_data_with_client(self, mock_update_client, mock_update_server):
        """Test loading config from JSON data with specific client"""
        config_data = make_sample_config_data()
        settings.load_config_from_json_data(config_data, client="test_client")

        mock_update_server.assert_called_once_with(config_data)
        mock_update_client.assert_called_once()

    @patch("server.api.utils.settings.update_server")
    @patch("server.api.utils.settings.update_client")
    def test_load_config_from_json_data_without_client(self, mock_update_client, mock_update_server):
        """Test loading config from JSON data without specific client"""
        config_data = make_sample_config_data()
        settings.load_config_from_json_data(config_data)

        mock_update_server.assert_called_once_with(config_data)
        assert mock_update_client.call_count == 2

    @patch("server.api.utils.settings.update_server")
    def test_load_config_from_json_data_missing_client_settings(self, _mock_update_server):
        """Test loading config from JSON data without client_settings"""
        invalid_config = {"database_configs": [], "model_configs": [], "oci_configs": [], "prompt_configs": []}

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
        mock_json_load.return_value = make_sample_config_data()

        result = settings.read_config_from_json_file()

        assert isinstance(result, Configuration)
        mock_json_load.assert_called_once()

    @patch.dict(os.environ, {"CONFIG_FILE": "/path/to/nonexistent.json"})
    @patch("os.path.isfile")
    def test_read_config_from_json_file_not_exists(self, mock_isfile):
        """Test reading config file that doesn't exist"""
        mock_isfile.return_value = False

    @patch.dict(os.environ, {"CONFIG_FILE": "/path/to/config.txt"})
    def test_read_config_from_json_file_wrong_extension(self):
        """Test reading config file with wrong extension"""

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(settings, "logger")
        assert settings.logger.name == "api.core.settings"


#####################################################
# Prompt Override Tests
#####################################################
class TestPromptOverrides:
    """Test prompt override operations"""

    @patch("server.api.utils.settings.cache")
    def test_load_prompt_override_with_text(self, mock_cache):
        """Test loading prompt override when text is provided"""
        prompt = {"name": "optimizer_test-prompt", "text": "You are a test assistant"}

        result = settings._load_prompt_override(prompt)

        assert result is True
        mock_cache.set_override.assert_called_once_with("optimizer_test-prompt", "You are a test assistant")

    @patch("server.api.utils.settings.cache")
    def test_load_prompt_override_without_text(self, mock_cache):
        """Test loading prompt override when text is not provided"""
        prompt = {"name": "optimizer_test-prompt"}

        result = settings._load_prompt_override(prompt)

        assert result is False
        mock_cache.set_override.assert_not_called()

    @patch("server.api.utils.settings.cache")
    def test_load_prompt_override_empty_text(self, mock_cache):
        """Test loading prompt override when text is empty string"""
        prompt = {"name": "optimizer_test-prompt", "text": ""}

        result = settings._load_prompt_override(prompt)

        assert result is False
        mock_cache.set_override.assert_not_called()

    @patch("server.api.utils.settings._load_prompt_override")
    def test_load_prompt_configs_success(self, mock_load_override):
        """Test loading prompt configs successfully"""
        mock_load_override.side_effect = [True, True, False]
        config_data = {
            "prompt_configs": [
                {"name": "prompt1", "text": "text1"},
                {"name": "prompt2", "text": "text2"},
                {"name": "prompt3", "text": "text3"},
            ]
        }

        settings._load_prompt_configs(config_data)

        assert mock_load_override.call_count == 3

    @patch("server.api.utils.settings._load_prompt_override")
    def test_load_prompt_configs_no_prompts_key(self, mock_load_override):
        """Test loading prompt configs when key is missing"""
        config_data = {"other_configs": []}

        settings._load_prompt_configs(config_data)

        mock_load_override.assert_not_called()

    @patch("server.api.utils.settings._load_prompt_override")
    def test_load_prompt_configs_empty_list(self, mock_load_override):
        """Test loading prompt configs with empty list"""
        config_data = {"prompt_configs": []}

        settings._load_prompt_configs(config_data)

        mock_load_override.assert_not_called()
