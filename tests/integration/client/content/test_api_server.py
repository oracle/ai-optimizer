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

    ST_FILE = "../src/client/content/api_server.py"

    def test_api_server_settings(self, app_server, app_test):
        """Change the Current System Prompt"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        assert at.session_state.server["port"] is not None
        assert at.session_state.server["key"] is not None
        assert at.number_input(key="user_server_port").value == int(at.session_state.server["port"])
        assert at.text_input(key="user_server_key").value == at.session_state.server["key"]

    def test_copy_client_settings_success(self, app_test, app_server):
        """Test the copy_client_settings function with a successful API call"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()

        # Store original value for cleanup
        original_auth_profile = at.session_state.client_settings["oci"]["auth_profile"]

        # Check that Server/Client Identical
        assert at.session_state.client_settings == at.session_state.server_settings
        # Update Client Settings
        at.session_state.client_settings["oci"]["auth_profile"] = "TESTING"
        assert at.session_state.client_settings != at.session_state.server_settings
        assert at.session_state.server_settings["oci"]["auth_profile"] != "TESTING"
        at.button(key="copy_client_settings").click().run()
        # Validate settings have been copied
        assert at.session_state.client_settings == at.session_state.server_settings
        assert at.session_state.server_settings["oci"]["auth_profile"] == "TESTING"

        # Clean up: restore original value both in session state and on server to avoid polluting other tests
        at.session_state.client_settings["oci"]["auth_profile"] = original_auth_profile
        # Copy the restored settings back to the server
        at.button(key="copy_client_settings").click().run()
        # Verify cleanup worked
        assert at.session_state.server_settings["oci"]["auth_profile"] == original_auth_profile
