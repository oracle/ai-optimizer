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
