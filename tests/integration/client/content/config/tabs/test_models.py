# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

import os
from unittest.mock import MagicMock, patch

from integration.client.conftest import temporary_sys_path

# Streamlit File
ST_FILE = "../src/client/content/config/tabs/models.py"


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    def test_model_page(self, app_server, app_test):
        """Test basic page layout"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        titles = at.get("title")
        assert any("Models" in t.value for t in titles)

        headers = at.get("header")
        assert any("Language Models" in h.value for h in headers)
        assert any("Embedding Models" in h.value for h in headers)

    def test_model_tables(self, app_server, app_test):
        """Test that the model tables are setup"""
        assert app_server is not None
        at = app_test(ST_FILE).run()
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

    def test_add_model_buttons_exist(self, app_server, app_test):
        """Test that add model buttons exist for all model types"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Check that add buttons exist
        add_ll_button = at.button(key="add_ll_model")
        add_embed_button = at.button(key="add_embed_model")

        assert add_ll_button is not None
        assert add_embed_button is not None
        assert add_ll_button.label == "Add"
        assert add_embed_button.label == "Add"

    def test_model_display_both_types(self, app_server, app_test):
        """Test that both language and embedding models are displayed"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Verify model configs are loaded
        assert hasattr(at.session_state, "model_configs")
        assert at.session_state.model_configs is not None

        # Should have sections for both types even if no models exist
        headers = at.get("header")
        header_text = [h.value for h in headers]
        assert any("Language Models" in text for text in header_text)
        assert any("Embedding Models" in text for text in header_text)

    def test_model_enabled_display(self, app_server, app_test):
        """Test that model enabled status is displayed correctly"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        for model in at.session_state.model_configs:
            enabled_field = at.text_input(key=f"{model['type']}_{model['provider']}_{model['id']}_enabled")
            # Should show enabled status as emoji
            assert enabled_field.value in ["🟢", "⚪"]  # Either enabled or disabled
            assert enabled_field.disabled is True  # Should be read-only

    def test_model_config_fields_readonly(self, app_server, app_test):
        """Test that model configuration fields are read-only in the table"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        for model in at.session_state.model_configs:
            model_field = at.text_input(key=f"{model['type']}_{model['provider']}_{model['id']}")
            api_base_field = at.text_input(key=f"{model['type']}_{model['provider']}_{model['id']}_api_base")

            assert model_field.disabled is True
            assert api_base_field.disabled is True
            assert model_field.value == f"{model['provider']}/{model['id']}"
            assert api_base_field.value == model["api_base"]

    def test_page_structure_and_dividers(self, app_server, app_test):
        """Test that the page has proper structure with dividers"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Should have dividers separating sections
        dividers = at.get("divider")
        assert len(dividers) >= 2  # At least one between title and first section, one between sections

    def test_model_configs_initialization(self, app_server, app_test):
        """Test that model configs are properly initialized from API"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Should have model_configs in session state
        assert hasattr(at.session_state, "model_configs")
        assert at.session_state.model_configs is not None
        assert isinstance(at.session_state.model_configs, list)

    def test_page_content_verification(self, app_server, app_test):
        """Test that page displays expected content and instructions"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Check for instructional text
        text_elements = at.get("text")
        markdown_elements = at.get("markdown")

        # Should have some form of instructional text
        all_text = []
        if text_elements:
            all_text.extend([t.value for t in text_elements])
        if markdown_elements:
            all_text.extend([m.value for m in markdown_elements])

        # Should mention updating, adding, or deleting models
        assert any(any(word in text.lower() for word in ["update", "add", "delete", "model"]) for text in all_text)


#############################################################################
# Test Functions Directly
#############################################################################
class TestModelFunctions:
    """Test individual functions from models.py"""

    def test_clear_client_models_function(self, app_server, app_test):
        """Test clear_client_models function behavior"""
        from client.content.config.tabs.models import clear_client_models

        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Set up test client settings
        at.session_state.client_settings = {
            "ll_model": {"model": "openai/test-model"},
            "testbed": {
                "judge_model": "openai/test-model",
                "qa_ll_model": "different/model",
                "qa_embed_model": "openai/test-model",
            },
        }

        # Call function under test
        with patch("client.content.config.tabs.models.state", at.session_state):
            clear_client_models("openai", "test-model")

        # Verify clearing worked
        assert at.session_state.client_settings["ll_model"]["model"] is None
        assert at.session_state.client_settings["testbed"]["judge_model"] is None
        assert at.session_state.client_settings["testbed"]["qa_ll_model"] == "different/model"
        assert at.session_state.client_settings["testbed"]["qa_embed_model"] is None

    def test_clear_client_models_no_matches(self, app_server, app_test):
        """Test clear_client_models when no models match"""
        from client.content.config.tabs.models import clear_client_models

        assert app_server is not None
        at = app_test(ST_FILE).run()

        original_settings = {
            "ll_model": {"model": "different/model"},
            "testbed": {
                "judge_model": "other/model",
                "qa_ll_model": "another/model",
                "qa_embed_model": "yet-another/model",
            },
        }
        at.session_state.client_settings = original_settings.copy()

        with patch("client.content.config.tabs.models.state", at.session_state):
            clear_client_models("openai", "nonexistent-model")

        # Settings should remain unchanged
        assert at.session_state.client_settings == original_settings

    def test_get_models_function(self, app_server, app_test):
        """Test get_models function retrieves data properly"""
        from client.content.config.tabs.models import get_models

        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Clear existing model configs to test refresh
        at.session_state.model_configs = None

        # Use proper API context patching
        with patch("client.content.config.tabs.models.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                get_models()

        # Should have loaded model configs
        assert at.session_state.model_configs is not None
        assert isinstance(at.session_state.model_configs, list)

    def test_get_models_force_refresh(self, app_server, app_test):
        """Test get_models with force=True"""
        from client.content.config.tabs.models import get_models

        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Set some existing data
        at.session_state.model_configs = ["old_data"]

        with patch("client.content.config.tabs.models.state", at.session_state):
            with patch("client.utils.api_call.state", at.session_state):
                get_models(force=True)

        # Should have refreshed with real data
        assert at.session_state.model_configs != ["old_data"]
        assert isinstance(at.session_state.model_configs, list)

    def test_get_supported_models_function(self, app_server, app_test):
        """Test get_supported_models function"""
        from client.content.config.tabs.models import get_supported_models

        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Get providers using API context
        with patch("client.utils.api_call.state", at.session_state):
            models = get_supported_models(model_type="ll")

        # Should return a list of provider names
        assert isinstance(models, list)
        assert len(models) > 0
        # Common providers should be included
        assert any(model["provider"] in ["openai", "anthropic", "ollama"] for model in models)

    def test_create_model_function_structure(self, app_server):
        """Test create_model function structure and requirements"""
        from client.content.config.tabs.models import create_model

        assert app_server is not None
        # Test that function accepts model structure and exists
        assert callable(create_model)

    def test_patch_model_function_structure(self, app_server):
        """Test patch_model function structure"""
        from client.content.config.tabs.models import patch_model

        assert app_server is not None
        # Verify function exists and is callable
        assert callable(patch_model)

    def test_delete_model_function_structure(self, app_server):
        """Test delete_model function structure"""
        from client.content.config.tabs.models import delete_model

        assert app_server is not None
        # Verify function exists and is callable
        assert callable(delete_model)

    def test_edit_model_dialog_structure(self, app_server):
        """Test edit_model dialog function structure"""
        from client.content.config.tabs.models import edit_model

        assert app_server is not None
        # Verify function exists and is callable
        assert callable(edit_model)

    def test_render_model_rows_function(self, app_server):
        """Test render_model_rows function structure"""
        import inspect
        from client.content.config.tabs.models import render_model_rows

        assert app_server is not None
        # Verify function exists and is callable
        assert callable(render_model_rows)
        # Test that function can be imported and has correct signature
        sig = inspect.signature(render_model_rows)
        params = list(sig.parameters.keys())
        assert "model_type" in params

    def test_display_models_function(self, app_server):
        """Test main display_models function"""
        from client.content.config.tabs.models import display_models

        assert app_server is not None
        # Verify function exists and is callable
        assert callable(display_models)

    def test_model_config_data_structure(self, app_server, app_test):
        """Test that model configs have expected structure"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        for model in at.session_state.model_configs:
            # Required fields
            assert "id" in model
            assert "type" in model
            assert "provider" in model
            assert "enabled" in model
            assert "api_base" in model

            # Type should be valid
            assert model["type"] in ["ll", "embed"]

            # Enabled should be boolean
            assert isinstance(model["enabled"], bool)

            # Provider and ID should be strings
            assert isinstance(model["provider"], str)
            assert isinstance(model["id"], str)

    def test_language_model_specific_fields(self, app_server, app_test):
        """Test that language models have specific fields"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        ll_models = [m for m in at.session_state.model_configs if m["type"] == "ll"]

        for model in ll_models:
            # Language model specific fields might be present
            # These are optional in the API but commonly used
            if "max_input_tokens" in model:
                assert isinstance(model["max_input_tokens"], int)
            if "temperature" in model:
                assert isinstance(model["temperature"], (int, float))
            if "max_tokens" in model:
                assert isinstance(model["max_tokens"], int)
            if "frequency_penalty" in model:
                assert isinstance(model["frequency_penalty"], (int, float))

    def test_embedding_model_specific_fields(self, app_server, app_test):
        """Test that embedding models have specific fields"""
        assert app_server is not None
        at = app_test(ST_FILE).run()

        embed_models = [m for m in at.session_state.model_configs if m["type"] == "embed"]

        for model in embed_models:
            # Embedding model specific fields might be present
            if "max_chunk_size" in model:
                assert isinstance(model["max_chunk_size"], int)

    def test_render_model_selection_with_custom_model_id(self, app_server, app_test):
        """Test that _render_model_selection handles custom model IDs not in supported models list"""
        from client.content.config.tabs.models import _render_model_selection, get_supported_models

        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Get actual supported models from API
        with patch("client.utils.api_call.state", at.session_state):
            supported_models = get_supported_models("ll")

        # Find a provider and create a model with a custom ID not in their supported list
        openai_provider = next((p for p in supported_models if p["provider"] == "openai"), None)
        assert openai_provider is not None, "OpenAI provider should be available in supported models"

        provider_models = openai_provider["models"]
        model_keys = [m["key"] for m in provider_models]

        # Create a custom model ID that definitely won't be in the supported list
        custom_model_id = "custom-fine-tuned-model-12345"
        assert custom_model_id not in model_keys, (
            f"Custom model ID {custom_model_id} should not be in supported models"
        )

        # Test model with custom ID
        model = {"id": custom_model_id, "provider": "openai", "type": "ll"}

        action = "edit"

        with patch("client.content.config.tabs.models.state", at.session_state):
            # This should preserve the custom model ID even though it's not in provider models
            result_model = _render_model_selection(model, provider_models, action)

            # The model ID should be preserved
            assert result_model["id"] == custom_model_id

    def test_render_api_configuration_preserves_saved_api_base(self, app_server, app_test):
        """Test that _render_api_configuration preserves saved api_base over LiteLLM default"""
        from client.content.config.tabs.models import _render_api_configuration, get_supported_models

        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Get actual supported models from API
        with patch("client.utils.api_call.state", at.session_state):
            supported_models = get_supported_models("ll")

        # Find OpenAI provider
        openai_provider = next((p for p in supported_models if p["provider"] == "openai"), None)
        assert openai_provider is not None, "OpenAI provider should be available in supported models"

        provider_models = openai_provider["models"]

        # Find a model that has an api_base in the provider models
        model_with_api_base = next((m for m in provider_models if m.get("api_base")), None)
        if model_with_api_base:
            litellm_api_base = model_with_api_base["api_base"]
            model_id = model_with_api_base["key"]
        else:
            # Fallback if no model has api_base
            litellm_api_base = "https://api.openai.com/v1"
            model_id = "gpt-4"

        # Create a model with a SAVED custom api_base (different from LiteLLM default)
        saved_custom_api_base = "https://my-custom-api.example.com/v1"
        model = {
            "id": model_id,
            "provider": "openai",
            "type": "ll",
            "api_base": saved_custom_api_base,  # This is the saved configuration
        }

        disable_for_oci = False

        with patch("client.content.config.tabs.models.state", at.session_state):
            # This should preserve the saved api_base, NOT overwrite with LiteLLM default
            result_model = _render_api_configuration(model, provider_models, disable_for_oci)

            # The saved api_base should be preserved (regression test for commit 5612888)
            assert result_model["api_base"] == saved_custom_api_base
            assert result_model["api_base"] != litellm_api_base or saved_custom_api_base == litellm_api_base

    def test_render_api_configuration_uses_litellm_default_when_no_saved_value(self, app_server, app_test):
        """Test that _render_api_configuration uses LiteLLM default when no saved api_base exists"""
        from client.content.config.tabs.models import _render_api_configuration, get_supported_models

        assert app_server is not None
        at = app_test(ST_FILE).run()

        # Get actual supported models from API
        with patch("client.utils.api_call.state", at.session_state):
            supported_models = get_supported_models("ll")

        # Find OpenAI provider
        openai_provider = next((p for p in supported_models if p["provider"] == "openai"), None)
        assert openai_provider is not None, "OpenAI provider should be available in supported models"

        provider_models = openai_provider["models"]

        # Find a model that has an api_base in the provider models
        model_with_api_base = next((m for m in provider_models if m.get("api_base")), None)
        if model_with_api_base:
            litellm_api_base = model_with_api_base["api_base"]
            model_id = model_with_api_base["key"]
        else:
            # Fallback if no model has api_base
            litellm_api_base = "https://api.openai.com/v1"
            model_id = "gpt-4"

        # Create a model WITHOUT a saved api_base (new model being added)
        model = {
            "id": model_id,
            "provider": "openai",
            "type": "ll",
            # Note: No "api_base" key - simulating a new model being added
        }

        disable_for_oci = False

        with patch("client.content.config.tabs.models.state", at.session_state):
            # This should use the LiteLLM default api_base
            result_model = _render_api_configuration(model, provider_models, disable_for_oci)

            # Should fall back to LiteLLM default when no saved value exists
            if model_with_api_base:
                assert result_model["api_base"] == litellm_api_base
            else:
                # If no model has api_base, it should be empty string
                assert result_model["api_base"] == ""


#############################################################################
# Test Model CRUD Operations
#############################################################################
class TestModelCRUD:
    """Test model create/patch/delete operations"""

    def test_create_model_success(self, monkeypatch):
        """Test creating a new model"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.config.tabs import models
            from client.utils import api_call
            import streamlit as st

            # Setup test model
            test_model = {
                "id": "new-model",
                "provider": "openai",
                "type": "ll",
                "enabled": True,
            }

            # Mock API call
            mock_post = MagicMock()
            monkeypatch.setattr(api_call, "post", mock_post)

            # Mock st.success
            mock_success = MagicMock()
            monkeypatch.setattr(st, "success", mock_success)

            # Call create_model
            models.create_model(test_model)

            # Verify API was called
            mock_post.assert_called_once()
            assert mock_success.called

    def test_patch_model_success(self, monkeypatch):
        """Test patching an existing model"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.config.tabs import models
            from client.utils import api_call
            import streamlit as st
            from streamlit import session_state as state

            # Setup test model
            test_model = {
                "id": "existing-model",
                "provider": "openai",
                "type": "ll",
                "enabled": False,
            }

            # Setup state with client settings
            state.client_settings = {
                "ll_model": {"model": "openai/existing-model"},
                "testbed": {
                    "judge_model": None,
                    "qa_ll_model": None,
                    "qa_embed_model": None,
                },
            }

            # Mock API call
            mock_patch = MagicMock()
            monkeypatch.setattr(api_call, "patch", mock_patch)

            # Mock st.success
            mock_success = MagicMock()
            monkeypatch.setattr(st, "success", mock_success)

            # Call patch_model
            models.patch_model(test_model)

            # Verify API was called
            mock_patch.assert_called_once()
            assert mock_success.called

            # Verify model was cleared from client settings since it was disabled
            assert state.client_settings["ll_model"]["model"] is None

    def test_delete_model_success(self, monkeypatch):
        """Test deleting a model"""
        with temporary_sys_path(os.path.join(os.path.dirname(__file__), "../../../../../../src")):
            from client.content.config.tabs import models
            from client.utils import api_call
            import streamlit as st
            from streamlit import session_state as state

            # Setup state with client settings
            state.client_settings = {
                "ll_model": {"model": "openai/test-model"},
                "testbed": {
                    "judge_model": None,
                    "qa_ll_model": None,
                    "qa_embed_model": None,
                },
            }

            # Mock API call
            mock_delete = MagicMock()
            monkeypatch.setattr(api_call, "delete", mock_delete)

            # Mock st.success
            mock_success = MagicMock()
            monkeypatch.setattr(st, "success", mock_success)

            # Mock sleep to speed up test
            monkeypatch.setattr("time.sleep", MagicMock())

            # Call delete_model
            models.delete_model("openai", "test-model")

            # Verify API was called
            mock_delete.assert_called_once_with(endpoint="v1/models/openai/test-model")
            assert mock_success.called

            # Verify model was cleared from client settings
            assert state.client_settings["ll_model"]["model"] is None
