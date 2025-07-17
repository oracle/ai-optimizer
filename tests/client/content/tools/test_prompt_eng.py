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
    ST_FILE = "../src/client/content/tools/prompt_eng.py"

    def test_change_sys(self, app_server, app_test):
        """Change the Current System Prompt"""
        assert app_server is not None

        at = app_test(self.ST_FILE).run()
        at.selectbox(key="selected_prompts_sys").set_value("Custom").run()
        assert at.session_state.user_settings["prompts"]["sys"] == "Custom"
        at.button(key="save_sys_prompt").click().run()
        assert at.info[0].value == "Custom (sys) Prompt Instructions - No Changes Detected."
        at.text_area(key="prompt_sys_prompt").set_value("This is my custom, sys prompt.").run()
        at.button(key="save_sys_prompt").click().run()
        assert at.toast[0].value == "Update Successful." and at.toast[0].icon == "✅"
        prompt = next(
            (
                prompt
                for prompt in at.session_state.prompt_configs
                if prompt["category"] == "sys" and prompt["name"] == "Custom"
            ),
            None,
        )
        assert prompt["prompt"] == "This is my custom, sys prompt."

    def test_change_ctx(self, app_server, app_test):
        """Change the Current System Prompt"""
        assert app_server is not None

        at = app_test(self.ST_FILE).run()
        print(at.selectbox)
        at.selectbox(key="selected_prompts_ctx").set_value("Custom").run()
        assert at.session_state.user_settings["prompts"]["ctx"] == "Custom"
        at.button(key="save_ctx_prompt").click().run()
        assert at.info[0].value == "Custom (ctx) Prompt Instructions - No Changes Detected."
        at.text_area(key="prompt_ctx_prompt").set_value("This is my custom, ctx prompt.").run()
        at.button(key="save_ctx_prompt").click().run()
        assert at.toast[0].value == "Update Successful." and at.toast[0].icon == "✅"
        prompt = next(
            (
                prompt
                for prompt in at.session_state.prompt_configs
                if prompt["category"] == "ctx" and prompt["name"] == "Custom"
            ),
            None,
        )
        assert prompt["prompt"] == "This is my custom, ctx prompt."
