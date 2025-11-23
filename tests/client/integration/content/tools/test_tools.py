"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error import-outside-toplevel

from conftest import create_tabs_mock, run_streamlit_test


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    # Streamlit File path
    ST_FILE = "../src/client/content/tools/tools.py"

    def test_initialization(self, app_server, app_test):
        """Test tools page initialization"""
        assert app_server is not None

        at = app_test(self.ST_FILE)
        run_streamlit_test(at)

    def test_tabs_created(self, app_server, app_test, monkeypatch):
        """Test that two tabs are created: Prompts and Split/Embed"""
        assert app_server is not None

        # Mock st.tabs to capture what tabs are created
        tabs_created = create_tabs_mock(monkeypatch)

        at = app_test(self.ST_FILE)
        run_streamlit_test(at)

        # Should create exactly 2 tabs
        assert len(tabs_created) == 2
        assert "🎤 Prompts" in tabs_created
        assert "📚 Split/Embed" in tabs_created

    def test_tabs_order(self, app_server, app_test, monkeypatch):
        """Test that tabs are in correct order: Prompts then Split/Embed"""
        assert app_server is not None

        # Mock st.tabs to capture what tabs are created
        tabs_created = create_tabs_mock(monkeypatch)

        at = app_test(self.ST_FILE)
        run_streamlit_test(at)

        # Verify order
        assert tabs_created[0] == "🎤 Prompts"
        assert tabs_created[1] == "📚 Split/Embed"

    def test_get_prompts_called_in_prompt_tab(self, app_server, app_test, monkeypatch):
        """Test that get_prompts is called for prompt_eng tab"""
        assert app_server is not None

        get_prompts_called = False

        from client.content.tools.tabs import prompt_eng

        original_get_prompts = prompt_eng.get_prompts

        def mock_get_prompts(*args, **kwargs):
            nonlocal get_prompts_called
            get_prompts_called = True
            return original_get_prompts(*args, **kwargs)

        monkeypatch.setattr(prompt_eng, "get_prompts", mock_get_prompts)

        at = app_test(self.ST_FILE)
        run_streamlit_test(at)

        # get_prompts should be called
        assert get_prompts_called, "get_prompts should be called in prompt_eng tab"

    def test_display_prompt_eng_called(self, app_server, app_test, monkeypatch):
        """Test that display_prompt_eng is called"""
        assert app_server is not None

        display_called = False

        from client.content.tools.tabs import prompt_eng

        original_display = prompt_eng.display_prompt_eng

        def mock_display(*args, **kwargs):
            nonlocal display_called
            display_called = True
            return original_display(*args, **kwargs)

        monkeypatch.setattr(prompt_eng, "display_prompt_eng", mock_display)

        at = app_test(self.ST_FILE)
        run_streamlit_test(at)

        # display_prompt_eng should be called
        assert display_called, "display_prompt_eng should be called"

    def test_split_embed_dependencies_called(self, app_server, app_test, monkeypatch):
        """Test that split_embed tab calls required dependencies"""
        assert app_server is not None

        calls = {
            "get_models": False,
            "get_databases": False,
            "get_oci": False,
            "display_split_embed": False,
        }

        from client.content.config.tabs import models, databases, oci
        from client.content.tools.tabs import split_embed

        # Mock all the functions
        original_get_models = models.get_models
        original_get_databases = databases.get_databases
        original_get_oci = oci.get_oci
        original_display = split_embed.display_split_embed

        def mock_get_models(*args, **kwargs):
            calls["get_models"] = True
            return original_get_models(*args, **kwargs)

        def mock_get_databases(*args, **kwargs):
            calls["get_databases"] = True
            return original_get_databases(*args, **kwargs)

        def mock_get_oci(*args, **kwargs):
            calls["get_oci"] = True
            return original_get_oci(*args, **kwargs)

        def mock_display(*args, **kwargs):
            calls["display_split_embed"] = True
            return original_display(*args, **kwargs)

        monkeypatch.setattr(models, "get_models", mock_get_models)
        monkeypatch.setattr(databases, "get_databases", mock_get_databases)
        monkeypatch.setattr(oci, "get_oci", mock_get_oci)
        monkeypatch.setattr(split_embed, "display_split_embed", mock_display)

        at = app_test(self.ST_FILE)
        run_streamlit_test(at)

        # All split_embed dependencies should be called
        assert calls["get_models"], "get_models should be called for split_embed tab"
        assert calls["get_databases"], "get_databases should be called for split_embed tab"
        assert calls["get_oci"], "get_oci should be called for split_embed tab"
        assert calls["display_split_embed"], "display_split_embed should be called"

    def test_page_renders_without_errors(self, app_server, app_test):
        """Test that page renders completely without errors"""
        assert app_server is not None

        at = app_test(self.ST_FILE)
        run_streamlit_test(at)

    def test_page_with_empty_state(self, app_server, app_test):
        """Test page behavior with minimal state"""
        assert app_server is not None

        at = app_test(self.ST_FILE)

        # Clear optional state that might exist
        if hasattr(at.session_state, "prompt_configs"):
            at.session_state.prompt_configs = []

        run_streamlit_test(at)

    def test_integration_between_tabs(self, app_server, app_test):
        """Test that both tabs can be accessed without interference"""
        assert app_server is not None

        at = app_test(self.ST_FILE)
        run_streamlit_test(at)
