"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    # Streamlit File
    ST_FILE = "../src/client/content/config/settings.py"

    def test_settings_display(self, app_server, app_test):
        """Test that settings are displayed correctly"""
        assert app_server is not None

        at = app_test(self.ST_FILE).run()
        # Verify initial state - JSON viewer is present
        assert at.json[0] is not None
        # Verify download button is present using label search
        download_buttons = at.get("download_button")
        assert len(download_buttons) > 0
        assert any(btn.label == "Download Settings" for btn in download_buttons)

    def test_checkbox_exists(self, app_server, app_test):
        """Test that sensitive settings checkbox exists"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        # Check that sensitive settings checkbox exists
        assert len(at.checkbox) > 0
        assert at.checkbox[0].label == "Include Sensitive Settings"

        # Toggle checkbox and verify it can be modified
        at.checkbox[0].set_value(True).run()
        assert at.checkbox[0].value is True

    def test_upload_toggle(self, app_server, app_test):
        """Test toggling to upload mode"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        # Toggle to Upload mode
        at.toggle[0].set_value(True).run()

        # Verify file uploader is shown using presence of file_uploader elements
        file_uploaders = at.get("file_uploader")
        assert len(file_uploaders) > 0

    def test_spring_ai_section_exists(self, app_server, app_test):
        """Test Spring AI settings section exists"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()

        # Check for SpringAI across all text elements - could be in title, header, markdown, etc.
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

        # Assert that SpringAI is mentioned somewhere in the page
        assert any("SpringAI" in text for text in page_text), "SpringAI section not found in page"

    def test_compare_with_uploaded_json(self, app_server, app_test):
        """Test the compare_with_uploaded_json function for finding differences in settings"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()

        # Set up current session state
        at.session_state.user_settings = {
            "ll_model": {"model": "gpt-3.5-turbo"},
            "vector_search": {"database": "DEFAULT", "model": "text-embedding-ada-002"},
        }
        at.session_state.database_config = {
            "DEFAULT": {"name": "DEFAULT", "user": "test_user", "password": "test_pass"}
        }

        # Create uploaded settings with differences
        uploaded_settings = {
            "user_settings": {
                "ll_model": {"model": "gpt-4"},  # Different model
                "vector_search": {"database": "DEFAULT", "model": "text-embedding-ada-002"},
            },
            "database_config": {
                "DEFAULT": {"name": "DEFAULT", "user": "new_user", "password": ""}  # Different user, empty password
            },
        }

        # Import the original function to test directly
        from client.content.config.settings import compare_with_uploaded_json

        # Call the function directly
        differences = compare_with_uploaded_json(at.session_state, uploaded_settings)

        # Verify that differences are detected (simplified checks)
        assert "user_settings" in differences
        assert "ll_model" in differences["user_settings"]
        assert differences["user_settings"]["ll_model"] is not None

        assert "database_config" in differences
        assert "DEFAULT" in differences["database_config"]
        assert "user" in differences["database_config"]["DEFAULT"]

        # Empty strings should be ignored
        assert "password" not in differences["database_config"]["DEFAULT"]

    def test_basic_configuration(self, app_server, app_test):
        """Test the basic configuration of the settings page"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()

        # Check that the session state is initialized
        assert hasattr(at, "session_state")
        assert "user_settings" in at.session_state

        # Check that models are loaded
        assert "ll_model_config" in at.session_state
        assert "embed_model_config" in at.session_state
