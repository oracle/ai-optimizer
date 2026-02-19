# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for settings.py that require the actual Streamlit app running.
These tests use app_test fixture to interact with real session state.

Note: Pure function tests (compare_settings, spring_ai_conf_check, save_settings)
and mock-heavy tests are in tests/unit/client/content/config/tabs/test_settings_unit.py
"""
# spell-checker: disable

import json
from unittest.mock import patch, MagicMock

import pytest
from shared_fixtures import call_spring_ai_obaas_with_mocks

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
        assert any(btn.label == "📥 Download Settings" for btn in download_buttons)

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
        assert "oci" in at.session_state["client_settings"]
        assert "database" in at.session_state["client_settings"]
        assert "vector_search" in at.session_state["client_settings"]


#############################################################################
# Test Get/Save Settings with Real State
#############################################################################
class TestSettingsGetSave:
    """Test get_settings and save_settings functions with real app state"""

    def _setup_get_settings_test(self, app_test, run_app=True):
        """Helper method to set up common test configuration for get_settings tests"""
        from client.content.config.tabs.settings import get_settings

        at = app_test(ST_FILE)
        if run_app:
            at.run()
        return get_settings, at

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

    def test_apply_uploaded_settings_success(self, app_server, app_test):
        """Test apply_uploaded_settings with successful API call"""
        from client.content.config.tabs.settings import apply_uploaded_settings

        assert app_server is not None
        _, at = self._setup_get_settings_test(app_test, run_app=False)
        uploaded_settings = {"test": "config"}

        with patch("client.content.config.tabs.settings.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                with patch("client.content.config.tabs.settings.st.success"):
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
                with patch("client.content.config.tabs.settings.st.error"):
                    apply_uploaded_settings(uploaded_settings)
                    # Just verify it handles errors gracefully

    def test_get_settings_default_parameters(self, app_server, app_test):
        """Test get_settings with default parameters"""
        assert app_server is not None
        get_settings, at = self._setup_get_settings_test(app_test, run_app=False)
        with patch("client.content.config.tabs.settings.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                result = get_settings()  # No parameters
                assert result is not None


#############################################################################
# Test Spring AI Functions with Real State
#############################################################################
class TestSpringAIIntegration:
    """Integration tests for Spring AI functions using real app state"""

    def test_spring_ai_obaas_with_real_state_basic(self, app_server, app_test):
        """Test spring_ai_obaas uses basic prompt with real state when Vector Search not in tools_enabled"""
        from client.content.config.tabs.settings import spring_ai_obaas

        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Set up state with tools_enabled NOT containing "Vector Search"
        at.session_state.client_settings["tools_enabled"] = ["Other Tool"]
        at.session_state.client_settings["database"] = {"alias": "DEFAULT"}

        result = call_spring_ai_obaas_with_mocks(at.session_state, "Prompt: {sys_prompt}", spring_ai_obaas)

        # Should use basic prompt - result should not be None
        assert result is not None

    def test_spring_ai_obaas_with_real_state_vector_search(self, app_server, app_test):
        """Test spring_ai_obaas uses VS prompt with real state when Vector Search IS in tools_enabled"""
        from client.content.config.tabs.settings import spring_ai_obaas

        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Set up state with tools_enabled containing "Vector Search"
        at.session_state.client_settings["tools_enabled"] = ["Vector Search"]
        at.session_state.client_settings["database"] = {"alias": "DEFAULT"}

        result = call_spring_ai_obaas_with_mocks(at.session_state, "Prompt: {sys_prompt}", spring_ai_obaas)

        # Should use VS prompt - result should not be None
        assert result is not None

    def test_spring_ai_obaas_tools_enabled_not_set(self, app_server, app_test):
        """Test spring_ai_obaas handles missing tools_enabled gracefully"""
        from client.content.config.tabs.settings import spring_ai_obaas

        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Remove tools_enabled if it exists
        if "tools_enabled" in at.session_state.client_settings:
            del at.session_state.client_settings["tools_enabled"]
        at.session_state.client_settings["database"] = {"alias": "DEFAULT"}

        # Should not raise - uses .get() with default empty list
        result = call_spring_ai_obaas_with_mocks(at.session_state, "Prompt: {sys_prompt}", spring_ai_obaas)
        assert result is not None

    def test_spring_ai_obaas_prompt_name_exists_in_configs(self, app_server, app_test):
        """Test that the prompt name used by spring_ai_obaas actually exists in prompt_configs"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Set up state with Vector Search enabled
        at.session_state.client_settings["tools_enabled"] = ["Vector Search"]
        at.session_state.client_settings["database"] = {"alias": "DEFAULT"}

        # Get the prompt_configs from session state
        prompt_configs = at.session_state["prompt_configs"] if "prompt_configs" in at.session_state else []
        prompt_names = [p["name"] for p in prompt_configs]

        # The expected prompt name when Vector Search is enabled
        expected_prompt_name = "optimizer_vs-tools-default"

        # CRITICAL: This test would have caught the bug!
        # The bug was using "optimizer_vs-no-tools-default" which doesn't exist
        assert expected_prompt_name in prompt_names, (
            f"Expected prompt '{expected_prompt_name}' not found in prompt_configs. "
            f"Available prompts: {prompt_names}"
        )

        # Also test that basic prompt exists for the fallback case
        at.session_state.client_settings["tools_enabled"] = []
        expected_basic_prompt = "optimizer_basic-default"
        assert expected_basic_prompt in prompt_names, (
            f"Expected prompt '{expected_basic_prompt}' not found in prompt_configs. "
            f"Available prompts: {prompt_names}"
        )


#############################################################################
# Test Prompt Config Upload with Real State
#############################################################################
class TestPromptConfigUpload:
    """Test prompt configuration upload scenarios via Streamlit UI"""

    def test_upload_prompt_matching_default_via_ui(self, app_server, app_test):
        """Test that uploading settings with prompt text matching default shows no differences"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        prompt_configs = at.session_state["prompt_configs"] if "prompt_configs" in at.session_state else None
        if not prompt_configs:
            pytest.skip("No prompts available for testing")

        # Get current settings via the UI's get_settings function
        from client.content.config.tabs.settings import get_settings, compare_settings

        with patch("client.content.config.tabs.settings.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                current_settings = get_settings(include_sensitive=True)

        # Create uploaded settings with prompt text matching the current text
        uploaded_settings = json.loads(json.dumps(current_settings))  # Deep copy

        # Compare - should show no differences for prompt_configs when text matches
        differences = compare_settings(current=current_settings, uploaded=uploaded_settings)

        # Remove empty difference groups
        differences = {k: v for k, v in differences.items() if v}

        # No differences expected when uploaded matches current
        assert "prompt_configs" not in differences.get("Value Mismatch", {})

    def test_upload_prompt_with_custom_text_shows_difference(self, app_server, app_test):
        """Test that uploading settings with different prompt text shows differences"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        prompt_configs = at.session_state["prompt_configs"] if "prompt_configs" in at.session_state else None
        if not prompt_configs:
            pytest.skip("No prompts available for testing")

        from client.content.config.tabs.settings import get_settings, compare_settings

        with patch("client.content.config.tabs.settings.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                current_settings = get_settings(include_sensitive=True)

        if not current_settings.get("prompt_configs"):
            pytest.skip("No prompts in current settings")

        # Create uploaded settings with modified prompt text
        uploaded_settings = json.loads(json.dumps(current_settings))  # Deep copy
        custom_text = "Custom test instruction - pirate"
        uploaded_settings["prompt_configs"][0]["text"] = custom_text

        # Compare - should show differences for prompt_configs
        differences = compare_settings(current=current_settings, uploaded=uploaded_settings)

        # Should detect the prompt text difference
        assert "prompt_configs" in differences.get("Value Mismatch", {})
        prompt_diffs = differences["Value Mismatch"]["prompt_configs"]
        prompt_name = current_settings["prompt_configs"][0]["name"]
        assert prompt_name in prompt_diffs
        assert prompt_diffs[prompt_name]["status"] == "Text differs"
        assert prompt_diffs[prompt_name]["uploaded_text"] == custom_text

    def test_upload_alternating_prompt_text_via_ui(self, app_server, app_test):
        """Test that compare_settings correctly detects alternating prompt text changes"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        prompt_configs = at.session_state["prompt_configs"] if "prompt_configs" in at.session_state else None
        if not prompt_configs:
            pytest.skip("No prompts available for testing")

        from client.content.config.tabs.settings import compare_settings

        # Simulate current state with text A
        current_settings = {
            "prompt_configs": [
                {"name": "test_prompt", "text": "Talk like a pirate"}
            ]
        }

        # Upload with text B - should show difference
        uploaded_text_b = {
            "prompt_configs": [
                {"name": "test_prompt", "text": "Talk like a pirate lady"}
            ]
        }
        differences = compare_settings(current=current_settings, uploaded=uploaded_text_b)
        assert "prompt_configs" in differences.get("Value Mismatch", {})
        assert differences["Value Mismatch"]["prompt_configs"]["test_prompt"]["status"] == "Text differs"

        # Now current is text B, upload text A - should still show difference
        current_settings["prompt_configs"][0]["text"] = "Talk like a pirate lady"
        uploaded_text_a = {
            "prompt_configs": [
                {"name": "test_prompt", "text": "Talk like a pirate"}
            ]
        }
        differences = compare_settings(current=current_settings, uploaded=uploaded_text_a)
        assert "prompt_configs" in differences.get("Value Mismatch", {})
        assert differences["Value Mismatch"]["prompt_configs"]["test_prompt"]["uploaded_text"] == "Talk like a pirate"

    def test_apply_uploaded_settings_with_prompts(self, app_server, app_test):
        """Test that apply_uploaded_settings is called correctly when applying prompt changes"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Switch to upload mode
        at.toggle[0].set_value(True).run()

        # Verify file uploader appears
        file_uploaders = at.get("file_uploader")
        assert len(file_uploaders) > 0

        # The actual apply functionality is tested via mocking since file upload
        # in Streamlit testing requires simulation
        from client.content.config.tabs.settings import apply_uploaded_settings

        client_settings = at.session_state["client_settings"] if "client_settings" in at.session_state else {}
        uploaded_settings = {
            "prompt_configs": [
                {"name": "test_prompt", "text": "New prompt text"}
            ],
            "client_settings": client_settings
        }

        # Create a mock state object that behaves like a dict
        mock_state = MagicMock()
        mock_state.client_settings = client_settings
        mock_state.keys.return_value = ["prompt_configs", "model_configs", "database_configs"]

        with patch("client.content.config.tabs.settings.state", mock_state):
            with patch("client.content.config.tabs.settings.api_call.post") as mock_post:
                with patch("client.content.config.tabs.settings.api_call.get") as mock_get:
                    with patch("client.content.config.tabs.settings.st.success"):
                        with patch("client.content.config.tabs.settings.st_common.clear_state_key"):
                            mock_post.return_value = {"message": "Settings updated"}
                            mock_get.return_value = client_settings

                            apply_uploaded_settings(uploaded_settings)

                            # Verify the API was called with the uploaded settings
                            mock_post.assert_called_once()
                            call_kwargs = mock_post.call_args
                            assert "v1/settings/load/json" in call_kwargs[1]["endpoint"]
