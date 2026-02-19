"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/settings.py
Tests for settings utility functions.
"""

# pylint: disable=too-few-public-methods

import json
from unittest.mock import patch, MagicMock

import pytest

from server.api.utils import settings as utils_settings
from server.api.utils.settings import bootstrap


class TestCreateClient:
    """Tests for the create_client function."""

    @patch("server.api.utils.settings.bootstrap.SETTINGS_OBJECTS")
    def test_create_client_success(self, mock_settings, make_settings):
        """create_client should create new client from default settings."""
        default_settings = make_settings(client="default")
        # Return new iterator each time __iter__ is called (consumed twice: any() and next())
        mock_settings.__iter__ = lambda _: iter([default_settings])
        mock_settings.__bool__ = lambda _: True
        mock_settings.append = MagicMock()

        result = utils_settings.create_client("new_client")

        assert result.client == "new_client"
        mock_settings.append.assert_called_once()

    @patch("server.api.utils.settings.bootstrap.SETTINGS_OBJECTS")
    def test_create_client_raises_on_existing(self, mock_settings, make_settings):
        """create_client should raise ValueError if client exists."""
        existing_settings = make_settings(client="existing")
        mock_settings.__iter__ = lambda _: iter([existing_settings])

        with pytest.raises(ValueError) as exc_info:
            utils_settings.create_client("existing")

        assert "already exists" in str(exc_info.value)


class TestGetClient:
    """Tests for the get_client function."""

    @patch("server.api.utils.settings.bootstrap.SETTINGS_OBJECTS")
    def test_get_client_success(self, mock_settings, make_settings):
        """get_client should return client settings."""
        client_settings = make_settings(client="test_client")
        mock_settings.__iter__ = lambda _: iter([client_settings])

        result = utils_settings.get_client("test_client")

        assert result.client == "test_client"

    @patch("server.api.utils.settings.bootstrap.SETTINGS_OBJECTS")
    def test_get_client_raises_on_not_found(self, mock_settings):
        """get_client should raise ValueError if client not found."""
        mock_settings.__iter__ = lambda _: iter([])

        with pytest.raises(ValueError) as exc_info:
            utils_settings.get_client("nonexistent")

        assert "not found" in str(exc_info.value)


class TestUpdateClient:
    """Tests for the update_client function."""

    @patch("server.api.utils.settings.get_client")
    @patch("server.api.utils.settings.bootstrap.SETTINGS_OBJECTS")
    def test_update_client_success(self, mock_settings, mock_get_client, make_settings):
        """update_client should update and return client settings."""
        old_settings = make_settings(client="test_client")
        new_settings = make_settings(client="other")

        mock_get_client.side_effect = [old_settings, new_settings]
        mock_settings.remove = MagicMock()
        mock_settings.append = MagicMock()

        utils_settings.update_client(new_settings, "test_client")

        mock_settings.remove.assert_called_once_with(old_settings)
        mock_settings.append.assert_called_once()


class TestGetMcpPromptsWithOverrides:
    """Tests for the get_mcp_prompts_with_overrides function."""

    @pytest.mark.asyncio
    @patch("server.api.utils.settings.utils_mcp.list_prompts")
    @patch("server.api.utils.settings.defaults")
    @patch("server.api.utils.settings.cache.get_override")
    async def test_get_mcp_prompts_with_overrides_success(self, mock_get_override, mock_defaults, mock_list_prompts):
        """get_mcp_prompts_with_overrides should return list of MCPPrompt."""
        mock_prompt = MagicMock()
        mock_prompt.name = "optimizer_test-prompt"
        mock_prompt.title = "Test Prompt"
        mock_prompt.description = "Test description"
        mock_prompt.meta = {"_fastmcp": {"tags": ["rag", "chat"]}}

        mock_list_prompts.return_value = [mock_prompt]

        mock_default_func = MagicMock()
        mock_default_func.return_value.content.text = "Default text"
        mock_defaults.optimizer_test_prompt = mock_default_func

        mock_get_override.return_value = None

        mock_mcp_engine = MagicMock()

        result = await utils_settings.get_mcp_prompts_with_overrides(mock_mcp_engine)

        assert len(result) == 1
        assert result[0].name == "optimizer_test-prompt"
        assert result[0].text == "Default text"

    @pytest.mark.asyncio
    @patch("server.api.utils.settings.utils_mcp.list_prompts")
    @patch("server.api.utils.settings.defaults")
    @patch("server.api.utils.settings.cache.get_override")
    async def test_get_mcp_prompts_uses_override(self, mock_get_override, mock_defaults, mock_list_prompts):
        """get_mcp_prompts_with_overrides should use override text when available."""
        mock_prompt = MagicMock()
        mock_prompt.name = "optimizer_test-prompt"
        mock_prompt.title = None
        mock_prompt.description = None
        mock_prompt.meta = None

        mock_list_prompts.return_value = [mock_prompt]

        mock_default_func = MagicMock()
        mock_default_func.return_value.content.text = "Default text"
        mock_defaults.optimizer_test_prompt = mock_default_func

        mock_get_override.return_value = "Override text"

        mock_mcp_engine = MagicMock()

        result = await utils_settings.get_mcp_prompts_with_overrides(mock_mcp_engine)

        assert result[0].text == "Override text"

    @pytest.mark.asyncio
    @patch("server.api.utils.settings.utils_mcp.list_prompts")
    async def test_get_mcp_prompts_filters_non_optimizer(self, mock_list_prompts):
        """get_mcp_prompts_with_overrides should filter out non-optimizer prompts."""
        mock_prompt1 = MagicMock()
        mock_prompt1.name = "optimizer_test"
        mock_prompt1.title = None
        mock_prompt1.description = None
        mock_prompt1.meta = None

        mock_prompt2 = MagicMock()
        mock_prompt2.name = "other_prompt"

        mock_list_prompts.return_value = [mock_prompt1, mock_prompt2]

        mock_mcp_engine = MagicMock()

        with patch("server.api.utils.settings.defaults") as mock_defaults:
            mock_defaults.optimizer_test = None
            with patch("server.api.utils.settings.cache.get_override", return_value=None):
                result = await utils_settings.get_mcp_prompts_with_overrides(mock_mcp_engine)

        assert len(result) == 1
        assert result[0].name == "optimizer_test"


class TestGetServer:
    """Tests for the get_server function."""

    @pytest.mark.asyncio
    @patch("server.api.utils.settings.get_mcp_prompts_with_overrides")
    @patch("server.api.utils.settings.bootstrap.DATABASE_OBJECTS", [])
    @patch("server.api.utils.settings.bootstrap.MODEL_OBJECTS", [])
    @patch("server.api.utils.settings.bootstrap.OCI_OBJECTS", [])
    async def test_get_server_returns_config(self, mock_get_prompts):
        """get_server should return server configuration dict."""
        mock_get_prompts.return_value = []
        mock_mcp_engine = MagicMock()

        result = await utils_settings.get_server(mock_mcp_engine)

        assert "database_configs" in result
        assert "model_configs" in result
        assert "oci_configs" in result
        assert "prompt_configs" in result


class TestUpdateServer:
    """Tests for the update_server function."""

    @patch("server.api.utils.settings.bootstrap.DATABASE_OBJECTS", [])
    @patch("server.api.utils.settings.bootstrap.MODEL_OBJECTS", [])
    @patch("server.api.utils.settings.bootstrap.OCI_OBJECTS", [])
    def test_update_server_updates_databases(self, make_database, make_settings):
        """update_server should update database objects."""
        config_data = {
            "client_settings": make_settings().model_dump(),
            "database_configs": [make_database(name="NEW_DB").model_dump()],
        }

        utils_settings.update_server(config_data)

        assert len(bootstrap.DATABASE_OBJECTS) == 1

    @patch("server.api.utils.settings._load_prompt_configs")
    @patch("server.api.utils.settings.bootstrap.DATABASE_OBJECTS", [])
    @patch("server.api.utils.settings.bootstrap.MODEL_OBJECTS", [])
    @patch("server.api.utils.settings.bootstrap.OCI_OBJECTS", [])
    def test_update_server_loads_prompt_configs(self, mock_load_prompts, make_settings):
        """update_server should load prompt configs."""
        config_data = {
            "client_settings": make_settings().model_dump(),
            "prompt_configs": [{"name": "test", "title": "Test Title", "text": "Test text"}],
        }

        utils_settings.update_server(config_data)

        mock_load_prompts.assert_called_once_with(config_data)

    @patch("server.api.utils.settings.bootstrap")
    def test_update_server_mutates_lists_not_replaces(self, mock_bootstrap, make_settings):
        """update_server should mutate existing lists rather than replacing them.

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

        config_data = {
            "client_settings": make_settings().model_dump(),
            "database_configs": [{"name": "test_db", "user": "user", "password": "pass", "dsn": "dsn"}],
            "model_configs": [{"id": "test-model", "provider": "openai", "type": "ll"}],
            "oci_configs": [{"auth_profile": "DEFAULT", "compartment_id": "ocid1.compartment.oc1..test"}],
        }

        utils_settings.update_server(config_data)

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


class TestLoadPromptOverride:  # pylint: disable=protected-access
    """Tests for the _load_prompt_override function."""

    @patch("server.api.utils.settings.cache.set_override")
    def test_load_prompt_override_with_text(self, mock_set_override):
        """_load_prompt_override should set cache with text."""
        prompt = {"name": "test_prompt", "text": "Test text"}

        result = utils_settings._load_prompt_override(prompt)

        assert result is True
        mock_set_override.assert_called_once_with("test_prompt", "Test text")

    @patch("server.api.utils.settings.cache.set_override")
    def test_load_prompt_override_without_text(self, mock_set_override):
        """_load_prompt_override should return False without text."""
        prompt = {"name": "test_prompt"}

        result = utils_settings._load_prompt_override(prompt)

        assert result is False
        mock_set_override.assert_not_called()

    @patch("server.api.utils.settings.cache.set_override")
    def test_load_prompt_override_with_empty_text(self, mock_set_override):
        """_load_prompt_override should return False when text is empty string."""
        prompt = {"name": "test_prompt", "text": ""}

        result = utils_settings._load_prompt_override(prompt)

        assert result is False
        mock_set_override.assert_not_called()


class TestLoadPromptConfigs:  # pylint: disable=protected-access
    """Tests for the _load_prompt_configs function."""

    @patch("server.api.utils.settings._load_prompt_override")
    def test_load_prompt_configs_with_prompts(self, mock_load_override):
        """_load_prompt_configs should load all prompts."""
        mock_load_override.return_value = True
        config_data = {"prompt_configs": [{"name": "p1", "text": "t1"}, {"name": "p2", "text": "t2"}]}

        utils_settings._load_prompt_configs(config_data)

        assert mock_load_override.call_count == 2

    @patch("server.api.utils.settings._load_prompt_override")
    def test_load_prompt_configs_without_key(self, mock_load_override):
        """_load_prompt_configs should handle missing prompt_configs key."""
        config_data = {}

        utils_settings._load_prompt_configs(config_data)

        mock_load_override.assert_not_called()

    @patch("server.api.utils.settings._load_prompt_override")
    def test_load_prompt_configs_empty_list(self, mock_load_override):
        """_load_prompt_configs should handle empty prompt_configs."""
        config_data = {"prompt_configs": []}

        utils_settings._load_prompt_configs(config_data)

        mock_load_override.assert_not_called()


class TestLoadConfigFromJsonData:
    """Tests for the load_config_from_json_data function."""

    @patch("server.api.utils.settings.update_server")
    @patch("server.api.utils.settings.update_client")
    def test_load_config_from_json_data_with_client(self, mock_update_client, mock_update_server, make_settings):
        """load_config_from_json_data should update specific client."""
        config_data = {"client_settings": make_settings().model_dump()}

        utils_settings.load_config_from_json_data(config_data, client="test_client")

        mock_update_server.assert_called_once()
        mock_update_client.assert_called_once()

    @patch("server.api.utils.settings.update_server")
    @patch("server.api.utils.settings.update_client")
    def test_load_config_from_json_data_without_client(self, mock_update_client, mock_update_server, make_settings):
        """load_config_from_json_data should update server and default when no client."""
        config_data = {"client_settings": make_settings().model_dump()}

        utils_settings.load_config_from_json_data(config_data, client=None)

        mock_update_server.assert_called_once()
        assert mock_update_client.call_count == 2  # "server" and "default"

    @patch("server.api.utils.settings.update_server")
    def test_load_config_from_json_data_raises_missing_settings(self, _mock_update_server):
        """load_config_from_json_data should raise KeyError if missing client_settings."""
        config_data = {}

        with pytest.raises(KeyError) as exc_info:
            utils_settings.load_config_from_json_data(config_data)

        assert "client_settings" in str(exc_info.value)


class TestReadConfigFromJsonFile:
    """Tests for the read_config_from_json_file function."""

    @patch.dict("os.environ", {"CONFIG_FILE": "/path/to/config.json"})
    @patch("os.path.isfile", return_value=True)
    @patch("os.access", return_value=True)
    @patch("builtins.open")
    def test_read_config_from_json_file_success(self, mock_open, mock_access, mock_isfile, make_settings):
        """read_config_from_json_file should return Configuration."""
        _ = (mock_access, mock_isfile)  # Used to suppress unused argument warning

        config_data = {"client_settings": make_settings().model_dump()}
        mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(config_data)

        # Mock json.load
        with patch("json.load", return_value=config_data):
            result = utils_settings.read_config_from_json_file()

        assert result is not None
