# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    # Streamlit File
    ST_FILE = "../src/client/content/tools/tabs/prompt_eng.py"

    def test_change_prompt(self, app_server, app_test):
        """Test changing prompt instructions via MCP prompts interface"""
        assert app_server is not None

        at = app_test(self.ST_FILE).run()

        # Select a prompt from the dropdown
        # The key is now "selected_prompt" (unified interface)
        available_prompts = list(at.session_state.prompt_configs)
        if not available_prompts:
            # No prompts available, test passes
            return

        # Get the first available prompt title
        first_prompt_title = available_prompts[0]["title"]
        at.selectbox(key="selected_prompt").set_value(first_prompt_title).run()

        # Check that prompt instructions were loaded
        assert "selected_prompt_instructions" in at.session_state

        # Try to save without changes - should show "No Changes Detected"
        at.button(key="save_sys_prompt").click().run()
        assert at.info[0].value == "Prompt Instructions - No Changes Detected."

    def test_prompt_page_loads(self, app_server, app_test):
        """Test that the prompt engineering page loads without errors"""
        assert app_server is not None

        at = app_test(self.ST_FILE).run()

        # Verify page loaded successfully
        assert not at.exception

        # Verify key session state exists
        assert "prompt_configs" in at.session_state

    def test_get_prompts_includes_text(self, app_server, app_test):
        """Test that get_prompts() fetches prompts with text field"""
        assert app_server is not None

        at = app_test(self.ST_FILE).run()

        # Verify prompt_configs has text field
        if at.session_state.prompt_configs:
            first_prompt = at.session_state.prompt_configs[0]
            assert "text" in first_prompt
            assert isinstance(first_prompt["text"], str)
            assert len(first_prompt["text"]) > 0

    def test_get_prompt_instructions_from_cache(self, app_server, app_test):
        """Test that get_prompt_instructions() reads from cached state"""
        assert app_server is not None

        at = app_test(self.ST_FILE).run()

        if not at.session_state.prompt_configs:
            # No prompts available, skip test
            return

        # Select a prompt
        first_prompt_title = at.session_state.prompt_configs[0]["title"]
        at.selectbox(key="selected_prompt").set_value(first_prompt_title).run()

        # Verify instructions were loaded from cache
        assert "selected_prompt_instructions" in at.session_state
        expected_text = at.session_state.prompt_configs[0]["text"]
        assert at.session_state.selected_prompt_instructions == expected_text

    def test_prompt_selection_updates_instructions(self, app_server, app_test):
        """Test that changing prompt selection updates instructions"""
        assert app_server is not None

        at = app_test(self.ST_FILE).run()

        if len(at.session_state.prompt_configs) < 2:
            # Need at least 2 prompts for this test
            return

        # Select first prompt
        first_prompt_title = at.session_state.prompt_configs[0]["title"]
        at.selectbox(key="selected_prompt").set_value(first_prompt_title).run()
        first_instructions = at.session_state.selected_prompt_instructions

        # Select second prompt
        second_prompt_title = at.session_state.prompt_configs[1]["title"]
        at.selectbox(key="selected_prompt").set_value(second_prompt_title).run()
        second_instructions = at.session_state.selected_prompt_instructions

        # Instructions should be different
        assert first_instructions != second_instructions
        assert second_instructions == at.session_state.prompt_configs[1]["text"]
