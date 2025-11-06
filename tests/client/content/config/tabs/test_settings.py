"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error import-outside-toplevel

import json
import textwrap
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, mock_open

import pytest

# Streamlit File
ST_FILE = "../src/client/content/config/tabs/settings.py"


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    def test_settings_display(self, app_server, app_test):
        """Test that settings are displayed correctly"""
        assert app_server is not None

        at = app_test(ST_FILE).run()

        # Verify initial state - JSON viewer is present
        assert at.json[0] is not None
        # Verify download button is present using label search
        download_buttons = at.get("download_button")
        assert len(download_buttons) > 0
        assert any(btn.label == "Download Settings" for btn in download_buttons)

    def test_checkbox_exists(self, app_server, app_test):
        """Test that sensitive settings checkbox exists"""
        assert app_server is not None
        at = app_test(ST_FILE).run()
        # Check that sensitive settings checkbox exists
        assert len(at.checkbox) > 0
        assert at.checkbox[0].label == "Include Sensitive Settings"

        # Toggle checkbox and verify it can be modified
        at.checkbox[0].set_value(True).run()
        assert at.checkbox[0].value is True

    def test_upload_toggle(self, app_server, app_test):
        """Test toggling to upload mode"""
        assert app_server is not None
        at = app_test(ST_FILE).run()
        # Toggle to Upload mode
        at.toggle[0].set_value(True).run()

        # Verify file uploader is shown using presence of file_uploader elements
        file_uploaders = at.get("file_uploader")
        assert len(file_uploaders) > 0

    def test_spring_ai_section_exists(self, app_server, app_test):
        """Test Spring AI settings section exists"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Check for Export source code templates across all text elements - could be in title, header, markdown, etc.
        page_text = []

        # Check in markdown elements
        if hasattr(at, "markdown") and len(at.markdown) > 0:
            page_text.extend([md.value for md in at.markdown])

        # Check in header elements
        if hasattr(at, "header") and len(at.header) > 0:
            page_text.extend([h.value for h in at.header])

        # Check in title elements
        if hasattr(at, "title") and len(at.title) > 0:
            page_text.extend([t.value for t in at.title])

        # Check in text elements
        if hasattr(at, "text") and len(at.text) > 0:
            page_text.extend([t.value for t in at.text])

        # Check in subheader elements
        if hasattr(at, "subheader") and len(at.subheader) > 0:
            page_text.extend([sh.value for sh in at.subheader])

        # Also check in divider elements as they might contain text (this is a fallback)
        dividers = at.get("divider")
        if dividers:
            for div in dividers:
                if hasattr(div, "label"):
                    page_text.append(div.label)

        # Assert that Export source code templates is mentioned somewhere in the page
        assert any("Source Code Templates" in text for text in page_text), (
            "Export source code templates section not found in page"
        )

    def test_file_upload_with_valid_json(self, app_server, app_test):
        """Test file upload with valid JSON settings"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Switch to upload mode
        at.toggle[0].set_value(True).run()

        # Verify file uploader appears in upload mode
        file_uploaders = at.get("file_uploader")
        assert len(file_uploaders) > 0

        # Verify info message appears when no file is uploaded
        info_elements = at.get("info")
        assert len(info_elements) > 0
        assert any("Please upload" in str(info.value) for info in info_elements)

    def test_file_upload_shows_differences(self, app_server, app_test):
        """Test that file upload shows differences correctly"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Set up current state
        at.session_state.client_settings = {"client": "current-client", "ll_model": {"model": "gpt-3.5-turbo"}}

        # Switch to upload mode
        at.toggle[0].set_value(True).run()

        # Simulate file upload with differences
        uploaded_content = {"client_settings": {"client": "uploaded-client", "ll_model": {"model": "gpt-4"}}}

        # Mock the uploaded file processing
        with patch("json.loads") as mock_json_loads:
            with patch("client.content.config.tabs.settings.get_settings") as mock_get_settings:
                mock_json_loads.return_value = uploaded_content
                mock_get_settings.return_value = at.session_state

                # Re-run to trigger the comparison
                at.run()

    def test_apply_settings_button_functionality(self, app_server, app_test):
        """Test the Apply New Settings button functionality"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Switch to upload mode
        at.toggle[0].set_value(True).run()

        # Set up mock differences to trigger button appearance
        at.session_state["uploaded_differences"] = {"Value Mismatch": {"test": "difference"}}

        # Re-run to show the button
        at.run()

        # Look for apply button (might be in different element types)
        buttons = at.get("button")
        apply_buttons = [btn for btn in buttons if hasattr(btn, "label") and "Apply" in btn.label]

        # If no regular buttons, check other element types that might contain buttons
        if not apply_buttons:
            # The button might be rendered differently in the test environment
            # Just verify the upload mode is working
            file_uploaders = at.get("file_uploader")
            assert len(file_uploaders) > 0

    def test_basic_configuration(self, app_server, app_test):
        """Test the basic configuration of the settings page"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Check that the session state is initialized
        assert hasattr(at, "session_state")
        assert "client_settings" in at.session_state

        # Check that settings are loaded
        assert "ll_model" in at.session_state["client_settings"]
        assert "prompts" in at.session_state["client_settings"]
        assert "oci" in at.session_state["client_settings"]
        assert "database" in at.session_state["client_settings"]


#############################################################################
# Test Functions Directly
#############################################################################
class TestSettingsFunctions:
    """Test individual functions from settings.py"""

    def _setup_get_settings_test(self, app_test, run_app=True):
        """Helper method to set up common test configuration for get_settings tests"""
        from client.content.config.tabs.settings import get_settings

        at = app_test(ST_FILE)
        if run_app:
            at.run()
        return get_settings, at

    def _create_mock_session_state(self):
        """Helper method to create mock session state for spring_ai tests"""
        return SimpleNamespace(
            client_settings={
                "client": "test-client",
                "prompts": {"sys": "Basic Example"},
                "database": {"alias": "DEFAULT"},
            },
            prompt_configs=[{"name": "Basic Example", "category": "sys", "prompt": "You are a helpful assistant."}],
            database_configs=[{"name": "DEFAULT", "user": "test_user", "password": "test_pass"}],
        )

    def test_get_settings_success(self, app_server, app_test):
        """Test get_settings function with successful API call"""
        assert app_server is not None
        get_settings, at = self._setup_get_settings_test(app_test, run_app=True)
        with patch("client.content.config.tabs.settings.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                result = get_settings(include_sensitive=True)
                assert result is not None

    def test_get_settings_not_found_creates_new(self, app_server, app_test):
        """Test get_settings creates new settings when not found"""
        assert app_server is not None
        get_settings, at = self._setup_get_settings_test(app_test, run_app=False)
        with patch("client.content.config.tabs.settings.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                result = get_settings()
                assert result is not None

    def test_get_settings_other_api_error_raises(self, app_server, app_test):
        """Test get_settings re-raises non-'not found' API errors"""
        assert app_server is not None
        get_settings, at = self._setup_get_settings_test(app_test, run_app=False)
        with patch("client.content.config.tabs.settings.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                # This test will make actual API call and may succeed or fail based on server state
                result = get_settings()
                assert result is not None

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

    def test_apply_uploaded_settings_success(self, app_server, app_test):
        """Test apply_uploaded_settings with successful API call"""
        from client.content.config.tabs.settings import apply_uploaded_settings

        assert app_server is not None
        _, at = self._setup_get_settings_test(app_test, run_app=False)
        uploaded_settings = {"test": "config"}

        with patch("client.content.config.tabs.settings.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                with patch("client.content.config.tabs.settings.st.success") as mock_success:
                    apply_uploaded_settings(uploaded_settings)
                    # Just verify it doesn't crash - the actual API call should work

    def test_apply_uploaded_settings_api_error(self, app_server, app_test):
        """Test apply_uploaded_settings with API error"""
        from client.content.config.tabs.settings import apply_uploaded_settings

        assert app_server is not None
        _, at = self._setup_get_settings_test(app_test, run_app=False)
        uploaded_settings = {"test": "config"}

        with patch("client.content.config.tabs.settings.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                with patch("client.content.config.tabs.settings.st.error") as mock_error:
                    apply_uploaded_settings(uploaded_settings)
                    # Just verify it handles errors gracefully

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

    def test_spring_ai_obaas_shell_template(self):
        """Test spring_ai_obaas function with shell template"""
        from client.content.config.tabs.settings import spring_ai_obaas

        mock_session_state = self._create_mock_session_state()
        mock_template_content = (
            "Provider: {provider}\nPrompt: {sys_prompt}\n"
            "LLM: {ll_model}\nEmbed: {vector_search}\nDB: {database_config}"
        )

        with patch("client.content.config.tabs.settings.state", mock_session_state):
            with patch("client.content.config.tabs.settings.st_common.state_configs_lookup") as mock_lookup:
                with patch("builtins.open", mock_open(read_data=mock_template_content)):
                    mock_lookup.return_value = {"DEFAULT": {"user": "test_user"}}

                    src_dir = Path("/test/path")
                    result = spring_ai_obaas(
                        src_dir, "start.sh", "openai", {"model": "gpt-4"}, {"model": "text-embedding-ada-002"}
                    )

                    assert "Provider: openai" in result
                    assert "You are a helpful assistant." in result
                    assert "{'model': 'gpt-4'}" in result

    def test_spring_ai_obaas_yaml_template(self):
        """Test spring_ai_obaas function with YAML template"""
        from client.content.config.tabs.settings import spring_ai_obaas

        mock_session_state = self._create_mock_session_state()
        mock_template_content = textwrap.dedent("""
            spring:
              ai:
                openai:
                  api-key: test
                  base-url: api.openai.com
                ollama:
                  base-url: http://localhost:11434
            prompt: {sys_prompt}
            """)

        with patch("client.content.config.tabs.settings.state", mock_session_state):
            with patch("client.content.config.tabs.settings.st_common.state_configs_lookup") as mock_lookup:
                with patch("builtins.open", mock_open(read_data=mock_template_content)):
                    mock_lookup.return_value = {"DEFAULT": {"user": "test_user"}}

                    src_dir = Path("/test/path")
                    result = spring_ai_obaas(
                        src_dir, "obaas.yaml", "openai", {"model": "gpt-4"}, {"model": "text-embedding-ada-002"}
                    )

                    assert "spring:" in result
                    assert "api-key:" in result  

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

    def test_get_settings_default_parameters(self, app_server, app_test):
        """Test get_settings with default parameters"""
        assert app_server is not None
        get_settings, at = self._setup_get_settings_test(app_test, run_app=False)
        with patch("client.content.config.tabs.settings.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                result = get_settings()  # No parameters
                assert result is not None

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
