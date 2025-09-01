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
    ST_FILE = "../src/client/content/config/tabs/models.py"

    def test_model_page(self, app_server, app_test):
        """Test basic page layout"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()

        titles = at.get("title")
        assert any("Models" in t.value for t in titles)

        headers = at.get("header")
        assert any("Language Models" in h.value for h in headers)
        assert any("Embedding Models" in h.value for h in headers)

    def test_model_tables(self, app_server, app_test):
        """Test that the model tables are setup"""
        assert app_server is not None
        at = app_test(self.ST_FILE).run()
        assert at.session_state.model_configs is not None
        for model in at.session_state.model_configs:
            assert at.text_input(key=f"{model['type']}_{model['provider']}_{model['id']}_enabled").value == "⚪"
            assert (
                at.text_input(key=f"{model['type']}_{model['provider']}_{model['id']}").value
                == f"{model['provider']}/{model['id']}"
            )
            assert (
                at.text_input(key=f"{model['type']}_{model['provider']}_{model['id']}_api_base").value
                == model["api_base"]
            )
            assert at.button(key=f"{model['type']}_{model['provider']}_{model['id']}_edit") is not None

        for model_type in {item["type"] for item in at.session_state.model_configs}:
            assert at.button(key=f"add_{model_type}_model") is not None
