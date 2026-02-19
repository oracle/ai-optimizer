# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for settings.py functions that don't require server integration.
These tests use mocks to isolate the functions under test.
"""
# spell-checker: disable

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, mock_open

import pytest
from shared_fixtures import call_spring_ai_obaas_with_mocks


#############################################################################
# Test Spring AI Configuration Check Function
#############################################################################
class TestSpringAIConfCheck:
    """Test spring_ai_conf_check function - pure function tests"""

    def test_spring_ai_conf_check_openai(self):
        """Test spring_ai_conf_check with OpenAI models"""
        from client.content.config.tabs.settings import spring_ai_conf_check

        ll_model = {"provider": "openai"}
        embed_model = {"provider": "openai"}

        result = spring_ai_conf_check(ll_model, embed_model)
        assert result == "openai"

    def test_spring_ai_conf_check_ollama(self):
        """Test spring_ai_conf_check with Ollama models"""
        from client.content.config.tabs.settings import spring_ai_conf_check

        ll_model = {"provider": "ollama"}
        embed_model = {"provider": "ollama"}

        result = spring_ai_conf_check(ll_model, embed_model)
        assert result == "ollama"

    def test_spring_ai_conf_check_hosted_vllm(self):
        """Test spring_ai_conf_check with hosted vLLM models"""
        from client.content.config.tabs.settings import spring_ai_conf_check

        ll_model = {"provider": "hosted_vllm"}
        embed_model = {"provider": "hosted_vllm"}

        result = spring_ai_conf_check(ll_model, embed_model)
        assert result == "hosted_vllm"

    def test_spring_ai_conf_check_hybrid(self):
        """Test spring_ai_conf_check with mixed providers"""
        from client.content.config.tabs.settings import spring_ai_conf_check

        ll_model = {"provider": "openai"}
        embed_model = {"provider": "ollama"}

        result = spring_ai_conf_check(ll_model, embed_model)
        assert result == "hybrid"

    def test_spring_ai_conf_check_empty_models(self):
        """Test spring_ai_conf_check with empty models"""
        from client.content.config.tabs.settings import spring_ai_conf_check

        result = spring_ai_conf_check(None, None)
        assert result == "hybrid"

        result = spring_ai_conf_check({}, {})
        assert result == "hybrid"


#############################################################################
# Test Spring AI OBaaS Function
#############################################################################
class TestSpringAIObaas:
    """Test spring_ai_obaas function with mocked state"""

    def _create_mock_session_state(self, tools_enabled=None):
        """Helper method to create mock session state for spring_ai tests"""
        client_settings = {
            "client": "test-client",
            "database": {"alias": "DEFAULT"},
            "vector_search": {"enabled": False},
        }
        if tools_enabled is not None:
            client_settings["tools_enabled"] = tools_enabled

        return SimpleNamespace(
            client_settings=client_settings,
            prompt_configs=[
                {
                    "name": "optimizer_basic-default",
                    "title": "Basic Example",
                    "description": "Basic default prompt",
                    "tags": [],
                    "text": "You are a helpful assistant.",
                },
                {
                    "name": "optimizer_vs-tools-default",
                    "title": "VS Tools",
                    "description": "Vector search prompt with tools",
                    "tags": [],
                    "text": "You are a vector search assistant.",
                },
            ],
            database_configs=[{"name": "DEFAULT", "user": "test_user", "password": "test_pass"}],
        )

    def test_spring_ai_obaas_shell_template(self):
        """Test spring_ai_obaas function with shell template"""
        from client.content.config.tabs.settings import spring_ai_obaas

        mock_session_state = self._create_mock_session_state()
        template = (
            "Provider: {provider}\nPrompt: {sys_prompt}\nLLM: {ll_model}\n"
            "Embed: {vector_search}\nDB: {database_config}"
        )

        result = call_spring_ai_obaas_with_mocks(mock_session_state, template, spring_ai_obaas)

        assert "Provider: openai" in result
        assert "You are a helpful assistant." in result
        assert "{'model': 'gpt-4'}" in result

    def test_spring_ai_obaas_with_vector_search_tool_enabled(self):
        """Test spring_ai_obaas uses vs-tools-default prompt when Vector Search is in tools_enabled"""
        from client.content.config.tabs.settings import spring_ai_obaas

        mock_state = self._create_mock_session_state(tools_enabled=["Vector Search"])

        result = call_spring_ai_obaas_with_mocks(mock_state, "Prompt: {sys_prompt}", spring_ai_obaas)

        # Should use the vector search prompt when "Vector Search" is in tools_enabled
        assert "You are a vector search assistant." in result

    def test_spring_ai_obaas_without_vector_search_tool(self):
        """Test spring_ai_obaas uses basic-default prompt when Vector Search is NOT in tools_enabled"""
        from client.content.config.tabs.settings import spring_ai_obaas

        mock_state = self._create_mock_session_state(tools_enabled=["Other Tool"])

        result = call_spring_ai_obaas_with_mocks(mock_state, "Prompt: {sys_prompt}", spring_ai_obaas)

        # Should use the basic prompt when "Vector Search" is NOT in tools_enabled
        assert "You are a helpful assistant." in result

    def test_spring_ai_obaas_with_empty_tools_enabled(self):
        """Test spring_ai_obaas uses basic-default prompt when tools_enabled is empty"""
        from client.content.config.tabs.settings import spring_ai_obaas

        mock_state = self._create_mock_session_state(tools_enabled=[])

        result = call_spring_ai_obaas_with_mocks(mock_state, "Prompt: {sys_prompt}", spring_ai_obaas)

        # Should use the basic prompt when tools_enabled is empty
        assert "You are a helpful assistant." in result

    def test_spring_ai_obaas_error_handling(self):
        """Test spring_ai_obaas function error handling"""
        from client.content.config.tabs.settings import spring_ai_obaas

        mock_session_state = self._create_mock_session_state()
        with patch("client.content.config.tabs.settings.state", mock_session_state):
            with patch("client.content.config.tabs.settings.st_common.state_configs_lookup") as mock_lookup:
                mock_lookup.return_value = {"DEFAULT": {"user": "test_user"}}

                # Test file not found
                with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
                    with pytest.raises(FileNotFoundError):
                        spring_ai_obaas(
                            Path("/test/path"),
                            "missing.sh",
                            "openai",
                            {"model": "gpt-4"},
                            {"model": "text-embedding-ada-002"},
                        )

    def test_spring_ai_obaas_yaml_parsing_error(self):
        """Test spring_ai_obaas YAML parsing error handling"""
        from client.content.config.tabs.settings import spring_ai_obaas

        mock_session_state = self._create_mock_session_state()
        invalid_yaml = "invalid: yaml: content: ["

        with patch("client.content.config.tabs.settings.state", mock_session_state):
            with patch("client.content.config.tabs.settings.st_common.state_configs_lookup") as mock_lookup:
                with patch("builtins.open", mock_open(read_data=invalid_yaml)):
                    mock_lookup.return_value = {"DEFAULT": {"user": "test_user"}}

                    # Should handle YAML parsing errors gracefully
                    with pytest.raises(Exception):  # Could be yaml.YAMLError or similar
                        spring_ai_obaas(
                            Path("/test/path"),
                            "invalid.yaml",
                            "openai",
                            {"model": "gpt-4"},
                            {"model": "text-embedding-ada-002"},
                        )


#############################################################################
# Test Spring AI ZIP Creation
#############################################################################
class TestSpringAIZip:
    """Test spring_ai_zip and langchain_mcp_zip functions"""

    def _create_mock_session_state(self):
        """Helper method to create mock session state"""
        return SimpleNamespace(
            client_settings={
                "client": "test-client",
                "database": {"alias": "DEFAULT"},
                "vector_search": {"enabled": False},
            },
            prompt_configs=[
                {
                    "name": "optimizer_basic-default",
                    "title": "Basic Example",
                    "description": "Basic default prompt",
                    "tags": [],
                    "text": "You are a helpful assistant.",
                }
            ],
            database_configs=[{"name": "DEFAULT", "user": "test_user", "password": "test_pass"}],
        )

    def test_spring_ai_zip_creation(self):
        """Test spring_ai_zip function creates proper ZIP file"""
        from client.content.config.tabs.settings import spring_ai_zip

        mock_session_state = self._create_mock_session_state()
        with patch("client.content.config.tabs.settings.state", mock_session_state):
            with patch("client.content.config.tabs.settings.st_common.state_configs_lookup") as mock_lookup:
                with patch("client.content.config.tabs.settings.shutil.copytree"):
                    with patch("client.content.config.tabs.settings.shutil.copy"):
                        with patch("client.content.config.tabs.settings.spring_ai_obaas") as mock_obaas:
                            mock_lookup.return_value = {"DEFAULT": {"user": "test_user"}}
                            mock_obaas.return_value = "mock content"

                            result = spring_ai_zip("openai", {"model": "gpt-4"}, {"model": "text-embedding-ada-002"})

                            # Verify it's a valid BytesIO object
                            assert hasattr(result, "read")
                            assert hasattr(result, "seek")

                            # Verify ZIP content
                            result.seek(0)
                            with zipfile.ZipFile(result, "r") as zip_file:
                                files = zip_file.namelist()
                                assert "start.sh" in files
                                assert "src/main/resources/application-obaas.yml" in files

    def test_langchain_mcp_zip_creation(self):
        """Test langchain_mcp_zip function creates proper ZIP file"""
        from client.content.config.tabs.settings import langchain_mcp_zip

        test_settings = {"test": "config"}

        with patch("client.content.config.tabs.settings.shutil.copytree"):
            with patch("client.content.config.tabs.settings.save_settings") as mock_save:
                with patch("builtins.open", mock_open()):
                    mock_save.return_value = '{"test": "config"}'

                    result = langchain_mcp_zip(test_settings)

                    # Verify it's a valid BytesIO object
                    assert hasattr(result, "read")
                    assert hasattr(result, "seek")

                    # Verify save_settings was called
                    mock_save.assert_called_once_with(test_settings)


#############################################################################
# Test Save Settings Function
#############################################################################
class TestSaveSettings:
    """Test save_settings function - pure function tests"""

    def test_save_settings(self):
        """Test save_settings function"""
        from client.content.config.tabs.settings import save_settings

        test_settings = {"client_settings": {"client": "old-client"}, "other": "data"}

        with patch("client.content.config.tabs.settings.datetime") as mock_datetime:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "25-SEP-2024T1430"
            mock_datetime.now.return_value = mock_now

            result = save_settings(test_settings)
            result_dict = json.loads(result)

            assert result_dict["client_settings"]["client"] == "25-SEP-2024T1430"
            assert result_dict["other"] == "data"

    def test_save_settings_no_client_settings(self):
        """Test save_settings with no client_settings"""
        from client.content.config.tabs.settings import save_settings

        test_settings = {"other": "data"}
        result = save_settings(test_settings)
        result_dict = json.loads(result)

        assert result_dict == {"other": "data"}

    def test_save_settings_with_nested_client_settings(self):
        """Test save_settings with nested client_settings structure"""
        from client.content.config.tabs.settings import save_settings

        test_settings = {
            "client_settings": {"client": "old-client", "nested": {"value": "test"}},
            "other_settings": {"value": "unchanged"},
        }

        with patch("client.content.config.tabs.settings.datetime") as mock_datetime:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "26-SEP-2024T0900"
            mock_datetime.now.return_value = mock_now

            result = save_settings(test_settings)
            result_dict = json.loads(result)

            # Client should be updated
            assert result_dict["client_settings"]["client"] == "26-SEP-2024T0900"
            # Nested values should be preserved
            assert result_dict["client_settings"]["nested"]["value"] == "test"
            # Other settings should be unchanged
            assert result_dict["other_settings"]["value"] == "unchanged"


#############################################################################
# Test Compare Settings Function
#############################################################################
class TestCompareSettings:
    """Test compare_settings function - pure function tests"""

    def test_compare_settings_comprehensive(self):
        """Test compare_settings function with comprehensive scenarios"""
        from client.content.config.tabs.settings import compare_settings

        current = {
            "shared": {"value": "same"},
            "current_only": {"value": "current"},
            "different": {"value": "current_val"},
            "api_key": "current_key",
            "nested": {"shared": "same", "different": "current_nested"},
            "list_field": ["a", "b", "c"],
        }

        uploaded = {
            "shared": {"value": "same"},
            "uploaded_only": {"value": "uploaded"},
            "different": {"value": "uploaded_val"},
            "api_key": "uploaded_key",
            "password": "uploaded_pass",
            "nested": {"shared": "same", "different": "uploaded_nested", "new_field": "new"},
            "list_field": ["a", "b", "d", "e"],
        }

        differences = compare_settings(current, uploaded)

        # Check value mismatches
        assert "different.value" in differences["Value Mismatch"]
        assert "nested.different" in differences["Value Mismatch"]
        assert "api_key" in differences["Value Mismatch"]

        # Check missing fields
        assert "current_only" in differences["Missing in Uploaded"]
        assert "nested.new_field" in differences["Missing in Current"]

        # Check sensitive key handling
        assert "password" in differences["Override on Upload"]

        # Check list handling
        assert "list_field[2]" in differences["Value Mismatch"]
        assert "list_field[3]" in differences["Missing in Current"]

    def test_compare_settings_client_skip(self):
        """Test compare_settings skips client_settings.client path"""
        from client.content.config.tabs.settings import compare_settings

        current = {"client_settings": {"client": "current_client"}}
        uploaded = {"client_settings": {"client": "uploaded_client"}}

        differences = compare_settings(current, uploaded)

        # Should be empty since client_settings.client is skipped
        assert all(not diff_dict for diff_dict in differences.values())

    def test_compare_settings_sensitive_key_handling(self):
        """Test compare_settings handles sensitive keys correctly"""
        from client.content.config.tabs.settings import compare_settings

        current = {"api_key": "current_key", "password": "current_pass", "normal_field": "current_val"}

        uploaded = {"api_key": "uploaded_key", "wallet_password": "uploaded_wallet", "normal_field": "uploaded_val"}

        differences = compare_settings(current, uploaded)

        # Sensitive keys should be in Value Mismatch
        assert "api_key" in differences["Value Mismatch"]

        # New sensitive keys should be in Override on Upload
        assert "wallet_password" in differences["Override on Upload"]

        # Normal fields should be in Value Mismatch
        assert "normal_field" in differences["Value Mismatch"]

        # Current-only sensitive key should be silently updated (not in Missing in Uploaded)
        assert "password" not in differences["Missing in Uploaded"]

    def test_compare_settings_with_none_values(self):
        """Test compare_settings with None values"""
        from client.content.config.tabs.settings import compare_settings

        current = {"field1": None, "field2": "value"}
        uploaded = {"field1": "value", "field2": None}

        differences = compare_settings(current, uploaded)

        assert "field1" in differences["Value Mismatch"]
        assert "field2" in differences["Value Mismatch"]

    def test_compare_settings_empty_structures(self):
        """Test compare_settings with empty structures"""
        from client.content.config.tabs.settings import compare_settings

        # Test empty dictionaries
        differences = compare_settings({}, {})
        assert all(not diff_dict for diff_dict in differences.values())

        # Test empty lists
        differences = compare_settings([], [])
        assert all(not diff_dict for diff_dict in differences.values())

        # Test mixed empty structures
        current = {"empty_dict": {}, "empty_list": []}
        uploaded = {"empty_dict": {}, "empty_list": []}
        differences = compare_settings(current, uploaded)
        assert all(not diff_dict for diff_dict in differences.values())

    def test_compare_settings_ignores_created_timestamps(self):
        """Test compare_settings ignores 'created' timestamp fields"""
        from client.content.config.tabs.settings import compare_settings

        current = {
            "model_configs": [
                {"id": "gpt-4", "created": 1758808962, "model": "gpt-4"},
                {"id": "gpt-3.5", "created": 1758808962, "model": "gpt-3.5-turbo"},
            ],
            "client_settings": {"ll_model": {"model": "openai/gpt-4o-mini"}},
        }

        uploaded = {
            "model_configs": [
                {"id": "gpt-4", "created": 1758808458, "model": "gpt-4"},
                {"id": "gpt-3.5", "created": 1758808458, "model": "gpt-3.5-turbo"},
            ],
            "client_settings": {"ll_model": {"model": None}},
        }

        differences = compare_settings(current, uploaded)

        # 'created' fields should not appear in differences
        assert "model_configs[0].created" not in differences["Value Mismatch"]
        assert "model_configs[1].created" not in differences["Value Mismatch"]

        # But other fields should still be compared
        assert "client_settings.ll_model.model" in differences["Value Mismatch"]

    def test_compare_settings_ignores_nested_created_fields(self):
        """Test compare_settings ignores deeply nested 'created' fields"""
        from client.content.config.tabs.settings import compare_settings

        current = {
            "nested": {
                "config": {"created": 123456789, "value": "current"},
                "another": {"created": 987654321, "setting": "test"},
            }
        }

        uploaded = {
            "nested": {
                "config": {"created": 111111111, "value": "current"},
                "another": {"created": 222222222, "setting": "changed"},
            }
        }

        differences = compare_settings(current, uploaded)

        # 'created' fields should be ignored
        assert "nested.config.created" not in differences["Value Mismatch"]
        assert "nested.another.created" not in differences["Value Mismatch"]

        # But actual value differences should be detected
        assert "nested.another.setting" in differences["Value Mismatch"]
        assert differences["Value Mismatch"]["nested.another.setting"]["current"] == "test"
        assert differences["Value Mismatch"]["nested.another.setting"]["uploaded"] == "changed"

    def test_compare_settings_ignores_created_in_lists(self):
        """Test compare_settings ignores 'created' fields within list items"""
        from client.content.config.tabs.settings import compare_settings

        current = {
            "items": [
                {"name": "item1", "created": 1111, "enabled": True},
                {"name": "item2", "created": 2222, "enabled": False},
            ]
        }

        uploaded = {
            "items": [
                {"name": "item1", "created": 9999, "enabled": True},
                {"name": "item2", "created": 8888, "enabled": True},
            ]
        }

        differences = compare_settings(current, uploaded)

        # 'created' fields should be ignored
        assert "items[0].created" not in differences["Value Mismatch"]
        assert "items[1].created" not in differences["Value Mismatch"]

        # But other field differences should be detected
        assert "items[1].enabled" in differences["Value Mismatch"]
        assert differences["Value Mismatch"]["items[1].enabled"]["current"] is False
        assert differences["Value Mismatch"]["items[1].enabled"]["uploaded"] is True

    def test_compare_settings_mixed_created_and_regular_fields(self):
        """Test compare_settings with a mix of 'created' and regular fields"""
        from client.content.config.tabs.settings import compare_settings

        current = {
            "config": {
                "created": 123456,
                "modified": 789012,
                "name": "current_config",
                "settings": {"created": 345678, "value": "old_value"},
            }
        }

        uploaded = {
            "config": {
                "created": 999999,  # Different created - should be ignored
                "modified": 888888,  # Different modified - should be detected
                "name": "current_config",  # Same name - no difference
                "settings": {
                    "created": 777777,  # Different created - should be ignored
                    "value": "new_value",  # Different value - should be detected
                },
            }
        }

        differences = compare_settings(current, uploaded)

        # 'created' fields should be ignored
        assert "config.created" not in differences["Value Mismatch"]
        assert "config.settings.created" not in differences["Value Mismatch"]

        # Regular field differences should be detected
        assert "config.modified" in differences["Value Mismatch"]
        assert "config.settings.value" in differences["Value Mismatch"]

        # Same values should not appear in differences
        assert "config.name" not in differences["Value Mismatch"]
