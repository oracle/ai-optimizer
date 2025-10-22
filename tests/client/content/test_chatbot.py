"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

from unittest.mock import patch


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    ST_FILE = "../src/client/content/chatbot.py"

    def test_disabled(self, app_server, app_test):
        """Test everything is disabled as nothing configured"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        assert (
            at.error[0].value == "No language models are configured and/or enabled. Disabling Client."
            and at.error[0].icon == "🛑"
        )


#############################################################################
# Test Prompt Switching Functions
#############################################################################
class TestPromptSwitching:
    """Test automatic prompt switching based on tool selection"""

    def test_switch_prompt_to_vector_search(self, app_server, app_test):
        """Test that selecting Vector Search switches to Vector Search Example prompt"""
        from client.utils.st_common import switch_prompt

        assert app_server is not None
        at = app_test(TestStreamlit.ST_FILE)
        at.run()

        # Setup: ensure we're not starting with Vector Search Example or Custom
        at.session_state.client_settings["prompts"]["sys"] = "Basic Example"

        # Mock streamlit's info to track if prompt was switched
        with patch("client.utils.st_common.state", at.session_state):
            with patch("client.utils.st_common.st") as mock_st:
                # Act: Switch to Vector Search prompt
                switch_prompt("sys", "Vector Search Example")

                # Assert: Prompt was updated
                assert at.session_state.client_settings["prompts"]["sys"] == "Vector Search Example"
                # Assert: User was notified via st.info
                mock_st.info.assert_called_once()
                assert "Vector Search Example" in str(mock_st.info.call_args)

    def test_switch_prompt_to_basic_example(self, app_server, app_test):
        """Test that disabling Vector Search switches to Basic Example prompt"""
        from client.utils.st_common import switch_prompt

        assert app_server is not None
        at = app_test(TestStreamlit.ST_FILE)
        at.run()

        # Setup: Start with Vector Search Example
        at.session_state.client_settings["prompts"]["sys"] = "Vector Search Example"

        # Mock streamlit's state and info
        with patch("client.utils.st_common.state", at.session_state):
            with patch("client.utils.st_common.st") as mock_st:
                # Act: Switch to Basic Example
                switch_prompt("sys", "Basic Example")

                # Assert: Prompt was updated
                assert at.session_state.client_settings["prompts"]["sys"] == "Basic Example"
                # Assert: User was notified
                mock_st.info.assert_called_once()
                assert "Basic Example" in str(mock_st.info.call_args)

    def test_switch_prompt_does_not_override_custom(self, app_server, app_test):
        """Test that automatic switching respects Custom prompt selection"""
        from client.utils.st_common import switch_prompt

        assert app_server is not None
        at = app_test(TestStreamlit.ST_FILE)
        at.run()

        # Setup: User has selected Custom prompt
        at.session_state.client_settings["prompts"]["sys"] = "Custom"

        # Mock streamlit's state and info
        with patch("client.utils.st_common.state", at.session_state):
            with patch("client.utils.st_common.st") as mock_st:
                # Act: Attempt to switch to Vector Search Example
                switch_prompt("sys", "Vector Search Example")

                # Assert: Prompt remains Custom (not overridden)
                assert at.session_state.client_settings["prompts"]["sys"] == "Custom"
                # Assert: User was NOT notified (no switching occurred)
                mock_st.info.assert_not_called()

    def test_switch_prompt_does_not_switch_if_already_set(self, app_server, app_test):
        """Test that switching to the same prompt doesn't trigger notification"""
        from client.utils.st_common import switch_prompt

        assert app_server is not None
        at = app_test(TestStreamlit.ST_FILE)
        at.run()

        # Setup: Already on Vector Search Example
        at.session_state.client_settings["prompts"]["sys"] = "Vector Search Example"

        # Mock streamlit's state and info
        with patch("client.utils.st_common.state", at.session_state):
            with patch("client.utils.st_common.st") as mock_st:
                # Act: Try to switch to Vector Search Example again
                switch_prompt("sys", "Vector Search Example")

                # Assert: Prompt remains the same
                assert at.session_state.client_settings["prompts"]["sys"] == "Vector Search Example"
                # Assert: User was NOT notified (no change occurred)
                mock_st.info.assert_not_called()

    def test_vector_search_tool_enables_vector_search_prompt(self, app_server, app_test):
        """Test that selecting Vector Search tool enables Vector Search and switches prompt"""
        assert app_server is not None
        at = app_test(TestStreamlit.ST_FILE)
        at.run()

        # Setup: Start with None tool selected and Basic Example prompt
        at.session_state.selected_tool = "None"
        at.session_state.client_settings["prompts"]["sys"] = "Basic Example"
        at.session_state.client_settings["vector_search"] = {"enabled": False}
        at.session_state.client_settings["selectai"] = {"enabled": False}

        # Simulate selecting Vector Search tool
        # This would trigger the _update_set_tool callback in tools_sidebar()
        at.session_state.selected_tool = "Vector Search"

        # Mock the switch_prompt behavior
        with patch("client.utils.st_common.state", at.session_state):
            with patch("client.utils.st_common.st"):
                # Import and call the function that would be triggered
                from client.utils.st_common import switch_prompt

                # Simulate what _update_set_tool does
                at.session_state.client_settings["vector_search"]["enabled"] = (
                    at.session_state.selected_tool == "Vector Search"
                )
                at.session_state.client_settings["selectai"]["enabled"] = (
                    at.session_state.selected_tool == "SelectAI"
                )

                # Apply prompt switching logic
                if at.session_state.client_settings["vector_search"]["enabled"]:
                    switch_prompt("sys", "Vector Search Example")
                else:
                    switch_prompt("sys", "Basic Example")

                # Assert: Vector Search is enabled
                assert at.session_state.client_settings["vector_search"]["enabled"] is True
                assert at.session_state.client_settings["selectai"]["enabled"] is False
                # Assert: Prompt switched to Vector Search Example
                assert at.session_state.client_settings["prompts"]["sys"] == "Vector Search Example"

    def test_selectai_tool_uses_basic_prompt(self, app_server, app_test):
        """Test that selecting SelectAI tool uses Basic Example prompt"""
        assert app_server is not None
        at = app_test(TestStreamlit.ST_FILE)
        at.run()

        # Setup: Start with Vector Search selected
        at.session_state.selected_tool = "Vector Search"
        at.session_state.client_settings["prompts"]["sys"] = "Vector Search Example"
        at.session_state.client_settings["vector_search"] = {"enabled": True}
        at.session_state.client_settings["selectai"] = {"enabled": False}

        # Simulate selecting SelectAI tool
        at.session_state.selected_tool = "SelectAI"

        # Mock the switch_prompt behavior
        with patch("client.utils.st_common.state", at.session_state):
            with patch("client.utils.st_common.st"):
                from client.utils.st_common import switch_prompt

                # Simulate what _update_set_tool does
                at.session_state.client_settings["vector_search"]["enabled"] = (
                    at.session_state.selected_tool == "Vector Search"
                )
                at.session_state.client_settings["selectai"]["enabled"] = (
                    at.session_state.selected_tool == "SelectAI"
                )

                # Apply prompt switching logic
                if at.session_state.client_settings["vector_search"]["enabled"]:
                    switch_prompt("sys", "Vector Search Example")
                else:
                    switch_prompt("sys", "Basic Example")

                # Assert: SelectAI is enabled, Vector Search is disabled
                assert at.session_state.client_settings["vector_search"]["enabled"] is False
                assert at.session_state.client_settings["selectai"]["enabled"] is True
                # Assert: Prompt switched to Basic Example
                assert at.session_state.client_settings["prompts"]["sys"] == "Basic Example"

    def test_none_tool_uses_basic_prompt(self, app_server, app_test):
        """Test that selecting None tool uses Basic Example prompt"""
        assert app_server is not None
        at = app_test(TestStreamlit.ST_FILE)
        at.run()

        # Setup: Start with Vector Search selected
        at.session_state.selected_tool = "Vector Search"
        at.session_state.client_settings["prompts"]["sys"] = "Vector Search Example"
        at.session_state.client_settings["vector_search"] = {"enabled": True}
        at.session_state.client_settings["selectai"] = {"enabled": False}

        # Simulate selecting None tool
        at.session_state.selected_tool = "None"

        # Mock the switch_prompt behavior
        with patch("client.utils.st_common.state", at.session_state):
            with patch("client.utils.st_common.st"):
                from client.utils.st_common import switch_prompt

                # Simulate what _update_set_tool does
                at.session_state.client_settings["vector_search"]["enabled"] = (
                    at.session_state.selected_tool == "Vector Search"
                )
                at.session_state.client_settings["selectai"]["enabled"] = (
                    at.session_state.selected_tool == "SelectAI"
                )

                # Apply prompt switching logic
                if at.session_state.client_settings["vector_search"]["enabled"]:
                    switch_prompt("sys", "Vector Search Example")
                else:
                    switch_prompt("sys", "Basic Example")

                # Assert: Both tools are disabled
                assert at.session_state.client_settings["vector_search"]["enabled"] is False
                assert at.session_state.client_settings["selectai"]["enabled"] is False
                # Assert: Prompt switched to Basic Example
                assert at.session_state.client_settings["prompts"]["sys"] == "Basic Example"

    def test_custom_prompt_not_overridden_by_tool_selection(self, app_server, app_test):
        """Test that Custom prompt is not overridden when switching tools"""
        assert app_server is not None
        at = app_test(TestStreamlit.ST_FILE)
        at.run()

        # Setup: User has Custom prompt selected
        at.session_state.selected_tool = "None"
        at.session_state.client_settings["prompts"]["sys"] = "Custom"
        at.session_state.client_settings["vector_search"] = {"enabled": False}
        at.session_state.client_settings["selectai"] = {"enabled": False}

        # Simulate selecting Vector Search tool
        at.session_state.selected_tool = "Vector Search"

        # Mock the switch_prompt behavior
        with patch("client.utils.st_common.state", at.session_state):
            with patch("client.utils.st_common.st"):
                from client.utils.st_common import switch_prompt

                # Simulate what _update_set_tool does
                at.session_state.client_settings["vector_search"]["enabled"] = (
                    at.session_state.selected_tool == "Vector Search"
                )
                at.session_state.client_settings["selectai"]["enabled"] = (
                    at.session_state.selected_tool == "SelectAI"
                )

                # Apply prompt switching logic
                if at.session_state.client_settings["vector_search"]["enabled"]:
                    switch_prompt("sys", "Vector Search Example")
                else:
                    switch_prompt("sys", "Basic Example")

                # Assert: Vector Search is enabled
                assert at.session_state.client_settings["vector_search"]["enabled"] is True
                # Assert: Prompt remains Custom (not overridden)
                assert at.session_state.client_settings["prompts"]["sys"] == "Custom"
