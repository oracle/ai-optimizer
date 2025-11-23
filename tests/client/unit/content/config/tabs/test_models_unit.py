"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for models.py to increase coverage
"""
# spell-checker: disable
# pylint: disable=import-error import-outside-toplevel

from unittest.mock import MagicMock



#############################################################################
# Test Helper Functions
#############################################################################
class TestModelHelpers:
    """Test model helper functions"""

    def test_get_supported_models_ll(self, monkeypatch):
        """Test get_supported_models for language models"""
        from client.content.config.tabs import models
        from client.utils import api_call

        # Mock API response - API filters by type, so returns only LL models
        mock_models = [
            {"id": "gpt-4", "type": "ll"},
            {"id": "gpt-3.5", "type": "ll"},
        ]
        monkeypatch.setattr(api_call, "get", lambda endpoint, params=None: mock_models)

        # Get LL models
        result = models.get_supported_models("ll")

        # Should return what API returns (API does the filtering)
        assert len(result) == 2
        assert all(m["type"] == "ll" for m in result)

    def test_get_supported_models_embed(self, monkeypatch):
        """Test get_supported_models for embedding models"""
        from client.content.config.tabs import models
        from client.utils import api_call

        # Mock API response - API filters by type, so returns only embed models
        mock_models = [
            {"id": "text-embed", "type": "embed"},
            {"id": "cohere-embed", "type": "embed"},
        ]
        monkeypatch.setattr(api_call, "get", lambda endpoint, params=None: mock_models)

        # Get embed models
        result = models.get_supported_models("embed")

        # Should return what API returns (API does the filtering)
        assert len(result) == 2
        assert all(m["type"] == "embed" for m in result)


#############################################################################
# Test Model Initialization
#############################################################################
class TestModelInitialization:
    """Test _initialize_model function"""

    def test_initialize_model_add(self):
        """Test initializing model for add action"""
        from client.content.config.tabs import models

        # Call _initialize_model for add
        result = models._initialize_model("add", "ll")  # pylint: disable=protected-access

        # Verify default values
        assert result["type"] == "ll"
        assert result["enabled"] is True
        assert result["provider"] == "unset"
        assert result["status"] == "CUSTOM"

    def test_initialize_model_edit(self, monkeypatch):
        """Test initializing model for edit action"""
        from client.content.config.tabs import models
        from client.utils import api_call
        import streamlit as st

        # Mock API response for edit
        mock_model = {
            "id": "gpt-4",
            "provider": "openai",
            "type": "ll",
            "enabled": True,
            "api_base": "https://api.openai.com",
        }
        monkeypatch.setattr(api_call, "get", lambda endpoint: mock_model)

        # Mock st.checkbox for enabled field
        monkeypatch.setattr(st, "checkbox", MagicMock(return_value=True))

        # Call _initialize_model for edit
        result = models._initialize_model("edit", "ll", "gpt-4", "openai")  # pylint: disable=protected-access

        # Verify existing model data is returned
        assert result["id"] == "gpt-4"
        assert result["provider"] == "openai"
        assert result["enabled"] is True


#############################################################################
# Test Model Rendering Functions
#############################################################################
class TestModelRendering:
    """Test model rendering functions"""

    def test_render_provider_selection(self, monkeypatch):
        """Test _render_provider_selection function"""
        from client.content.config.tabs import models
        import streamlit as st

        # Mock st.selectbox
        mock_selectbox = MagicMock(return_value="openai")
        monkeypatch.setattr(st, "selectbox", mock_selectbox)

        # Setup test data
        model = {"provider": "openai"}
        supported_models = [
            {"provider": "openai", "id": "gpt-4", "models": [{"key": "gpt-4"}]},
            {"provider": "anthropic", "id": "claude", "models": [{"key": "claude"}]},
        ]

        # Call function
        # pylint: disable=protected-access
        result_model, provider_models, disable_oci = models._render_provider_selection(
            model, supported_models, "add"
        )

        # Verify selectbox was called
        assert mock_selectbox.called
        assert result_model["provider"] == "openai"
        assert isinstance(provider_models, list)
        assert isinstance(disable_oci, bool)

    def test_render_model_selection(self, monkeypatch):
        """Test _render_model_selection function"""
        from client.content.config.tabs import models
        import streamlit as st

        # Mock st.selectbox
        mock_selectbox = MagicMock(return_value="gpt-4")
        monkeypatch.setattr(st, "selectbox", mock_selectbox)

        # Setup test data
        model = {"id": "gpt-4", "provider": "openai"}
        provider_models = [
            {"key": "gpt-4", "id": "gpt-4", "provider": "openai"},
            {"key": "gpt-3.5", "id": "gpt-3.5", "provider": "openai"},
        ]

        # Call function
        result = models._render_model_selection(model, provider_models, "add")  # pylint: disable=protected-access

        # Verify function worked
        assert "id" in result
        assert result["id"] == "gpt-4"

    def test_render_api_configuration(self, monkeypatch):
        """Test _render_api_configuration function"""
        from client.content.config.tabs import models
        import streamlit as st

        # Mock st.text_input
        mock_text_input = MagicMock(side_effect=["https://api.openai.com", "sk-test-key"])
        monkeypatch.setattr(st, "text_input", mock_text_input)

        # Setup test data
        model = {"id": "gpt-4", "provider": "openai"}
        provider_models = [
            {"key": "gpt-4", "api_base": "https://api.openai.com"},
        ]

        # Call function
        result = models._render_api_configuration(model, provider_models, False)  # pylint: disable=protected-access

        # Verify function worked
        assert "api_base" in result
        assert "api_key" in result
        assert mock_text_input.call_count == 2

    def test_render_model_specific_config_ll(self, monkeypatch):
        """Test _render_model_specific_config for language models"""
        from client.content.config.tabs import models
        import streamlit as st

        # Mock st.number_input
        mock_number_input = MagicMock(side_effect=[8192, 4096])
        monkeypatch.setattr(st, "number_input", mock_number_input)

        # Setup test data
        model = {"id": "gpt-4", "provider": "openai", "type": "ll"}
        provider_models = [
            {"key": "gpt-4", "max_input_tokens": 8192, "max_tokens": 4096},
        ]

        # Call function
        result = models._render_model_specific_config(model, "ll", provider_models)  # pylint: disable=protected-access

        # Verify function worked
        assert "max_input_tokens" in result
        assert "max_tokens" in result
        assert result["max_input_tokens"] == 8192
        assert result["max_tokens"] == 4096

    def test_render_model_specific_config_embed(self, monkeypatch):
        """Test _render_model_specific_config for embedding models"""
        from client.content.config.tabs import models
        import streamlit as st

        # Mock st.number_input
        mock_number_input = MagicMock(return_value=8192)
        monkeypatch.setattr(st, "number_input", mock_number_input)

        # Setup test data
        model = {"id": "text-embed", "provider": "openai", "type": "embed"}
        provider_models = [
            {"key": "text-embed", "max_chunk_size": 8192},
        ]

        # Call function
        result = models._render_model_specific_config(model, "embed", provider_models)  # pylint: disable=protected-access

        # Verify function worked
        assert "max_chunk_size" in result
        assert result["max_chunk_size"] == 8192


#############################################################################
# Test Clear Client Models
#############################################################################
class TestClearClientModels:
    """Test clear_client_models function"""

    def test_clear_client_models_ll_model(self):
        """Test clearing ll_model from client settings"""
        from client.content.config.tabs import models
        from streamlit import session_state as state

        # Setup state
        state.client_settings = {
            "ll_model": {"model": "openai/gpt-4"},
            "testbed": {
                "judge_model": "openai/gpt-4",
                "qa_ll_model": None,
                "qa_embed_model": None,
            },
        }

        # Clear the model
        models.clear_client_models("openai", "gpt-4")

        # Verify both ll_model and judge_model were cleared
        assert state.client_settings["ll_model"]["model"] is None
        assert state.client_settings["testbed"]["judge_model"] is None

    def test_clear_client_models_no_match(self):
        """Test clearing models when no match is found"""
        from client.content.config.tabs import models
        from streamlit import session_state as state

        # Setup state
        state.client_settings = {
            "ll_model": {"model": "openai/gpt-4"},
            "testbed": {
                "judge_model": None,
                "qa_ll_model": None,
                "qa_embed_model": None,
            },
        }

        # Try to clear a model that doesn't match
        models.clear_client_models("anthropic", "claude")

        # Verify nothing was changed
        assert state.client_settings["ll_model"]["model"] == "openai/gpt-4"
