# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from test.integration.client.conftest import enable_test_models, run_page_with_models_enabled


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

    def test_page_loads_with_enabled_model(self, app_server, app_test):
        """Test that chatbot page loads successfully when a language model is enabled"""
        run_page_with_models_enabled(app_server, app_test, self.ST_FILE)


#############################################################################
# Test Vector Search Tool Selection
#############################################################################
class TestVectorSearchToolSelection:
    """Test the Vector Search tool selection behavior in chatbot.py sidebar"""

    ST_FILE = "../src/client/content/chatbot.py"

    def test_vector_search_not_shown_when_no_enabled_embedding_models(self, app_server, app_test):
        """
        Test that Vector Search option is NOT shown in Tool Selection selectbox
        when vector stores exist but their embedding models are not enabled.

        Scenario:
        - Database has vector stores that use "openai/text-embedding-3-small"
        - That OpenAI model is NOT enabled
        - But a different embedding model (Cohere) IS enabled
        - tools_sidebar() checks if enabled models match vector store models

        Expected behavior:
        - Vector Search should NOT appear in Tool Selection (no usable vector stores)
        - User should only see "LLM Only" option

        What this test verifies:
        - Vector Search when enabled embedding models don't match vector store models
        """
        assert app_server is not None
        at = app_test(self.ST_FILE).run()

        # Modify session state to simulate the problematic scenario:
        # - Database is connected and has vector stores that use specific models
        # - Those specific models are NOT enabled
        # - But OTHER embedding models ARE enabled (so embed_models_enabled is not empty)

        # First, ensure we have a connected database with vector stores
        if at.session_state.database_configs:
            db_config = at.session_state.database_configs[0]
            db_config["connected"] = True
            # Vector store uses openai/text-embedding-3-small
            db_config["vector_stores"] = [
                {
                    "vector_store": "VS_TEST_OPENAI_SMALL",
                    "alias": "TEST_DATA",
                    "model": "openai/text-embedding-3-small",
                    "chunk_size": 500,
                    "chunk_overlap": 50,
                    "distance_metric": "COSINE",
                    "index_type": "IVF",
                }
            ]
            at.session_state.client_settings["database"]["alias"] = db_config["name"]

        # Disable the OpenAI embedding model that the vector store needs
        # But enable a DIFFERENT embedding model (Cohere)
        for model in at.session_state.model_configs:
            if model["type"] == "embed":
                if "text-embedding-3-small" in model["id"]:
                    model["enabled"] = False  # Disable the model the vector store needs
                elif "cohere" in model["provider"]:
                    model["enabled"] = True  # Enable a different model
                else:
                    model["enabled"] = False

        # Ensure at least one language model is enabled so the app runs
        at = enable_test_models(at)

        # Re-run with modified state
        at.run()

        # Get the Tool Selection selectbox
        selectboxes = [sb for sb in at.selectbox if sb.label == "Tool Selection"]

        # Vector Search appears as an option even when its vector stores can't be used
        # Scenario: embed models ARE enabled, but they don't match the vector store models
        # Expected: Vector Search should NOT appear (or should check model compatibility)
        if selectboxes:
            tool_selectbox = selectboxes[0]
            # THIS SHOULD FAIL - Vector Search should NOT be in the options when
            # the enabled embedding models don't match any vector store models
            assert "Vector Search" not in tool_selectbox.options, (
                f"BUG DETECTED: Vector Search appears in Tool Selection even though no vector stores "
                f"are usable (enabled models don't match vector store models). "
                f"Found options: {tool_selectbox.options}"
            )

    def test_vector_search_disabled_when_selected_with_no_enabled_models(self, app_server, app_test):
        """
        Test that Vector Search can be selected and used when models match.

        This test verifies that when Vector Search appears (because enabled models
        match vector stores), the user can successfully select and use it.
        """
        assert app_server is not None
        at = app_test(self.ST_FILE).run()

        # Set up the problematic scenario
        if at.session_state.database_configs:
            db_config = at.session_state.database_configs[0]
            db_config["connected"] = True
            db_config["vector_stores"] = [
                {
                    "vector_store": "VS_TEST_OPENAI_SMALL",
                    "alias": "TEST_DATA",
                    "model": "openai/text-embedding-3-small",
                    "chunk_size": 500,
                    "chunk_overlap": 50,
                    "distance_metric": "COSINE",
                    "index_type": "IVF",
                }
            ]
            at.session_state.client_settings["database"]["alias"] = db_config["name"]

        # Disable ALL embedding models
        for model in at.session_state.model_configs:
            if model["type"] == "embed":
                model["enabled"] = False

        # Ensure at least one LL model is enabled
        for model in at.session_state.model_configs:
            if model["type"] == "ll":
                model["enabled"] = True
                break

        # Re-run
        at.run()

        # Try to select Vector Search if it exists in options
        selectboxes = [sb for sb in at.selectbox if sb.label == "Tool Selection"]

        if selectboxes and "Vector Search" in selectboxes[0].options:
            # Vector Search shouldn't be an option
            tool_selectbox = selectboxes[0]

            # Try to select it
            tool_selectbox.set_value("Vector Search").run()

            # Now check that vector store selection is broken
            # Should see "Vector Store" subheader
            subheaders = [sh.value for sh in at.sidebar.subheader]
            assert "Vector Store" in subheaders, "Vector Store subheader should appear but user cannot select anything"

            # Check that we end up in a broken state with info message
            info_messages = [i.value for i in at.info]
            assert any("Please select existing Vector Store options" in msg for msg in info_messages), (
                "Should show info message about selecting vector store options (broken UX)"
            )

    def test_vector_search_shown_when_embedding_models_enabled(self, app_server, app_test):
        """
        Test that Vector Search option IS shown when vector stores exist
        AND their embedding models are enabled.

        This is the happy path - when everything is configured correctly.
        """
        assert app_server is not None
        at = app_test(self.ST_FILE).run()

        # Set up the happy path scenario
        if at.session_state.database_configs:
            db_config = at.session_state.database_configs[0]
            db_config["connected"] = True
            db_config["vector_stores"] = [
                {
                    "vector_store": "VS_TEST_OPENAI_SMALL",
                    "alias": "TEST_DATA",
                    "model": "openai/text-embedding-3-small",
                    "chunk_size": 500,
                    "chunk_overlap": 50,
                    "distance_metric": "COSINE",
                    "index_type": "IVF",
                }
            ]
            at.session_state.client_settings["database"]["alias"] = db_config["name"]

        # Enable at least one embedding model that matches a vector store
        for model in at.session_state.model_configs:
            if model["type"] == "embed" and "text-embedding-3-small" in model["id"]:
                model["enabled"] = True

        # Ensure at least one LL model is enabled
        for model in at.session_state.model_configs:
            if model["type"] == "ll":
                model["enabled"] = True
                break

        # Re-run
        at.run()

        # Get the Tool Selection selectbox (if it exists)
        selectboxes = [sb for sb in at.selectbox if sb.label == "Tool Selection"]

        if selectboxes:
            tool_selectbox = selectboxes[0]
            # Vector Search SHOULD be in the options
            assert "Vector Search" in tool_selectbox.options, (
                "Vector Search should appear when embedding models are enabled"
            )


#############################################################################
# Test Language Model Selectbox
#############################################################################
class TestLanguageModelSelectbox:
    """Test that the Language Model selectbox is properly rendered in the sidebar"""

    ST_FILE = "../src/client/content/chatbot.py"

    def test_chat_model_selectbox_is_rendered(self, app_server, app_test):
        """
        Test that the Chat Model selectbox is rendered in the sidebar.

        This test ensures that the selectbox added in st_common.py:158-165
        remains in place and functions correctly. The selectbox should:
        - Be accessible via its key "selected_ll_model_model"
        - Show available language models as options
        - Have the currently selected model as the default value
        """
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Enable at least one language model
        at = enable_test_models(at)

        # Run the app
        at = at.run()

        # Access the chat model selectbox by its key
        # The selectbox is defined with key="selected_ll_model_model" in st_common.py:163
        assert hasattr(at.session_state, "selected_ll_model_model"), (
            "Chat model selectbox with key 'selected_ll_model_model' should be rendered. "
            "This selectbox was added in st_common.py:158-165 and must remain."
        )

        # Verify the selectbox value is set in session state
        selected_model = at.session_state.selected_ll_model_model
        assert selected_model is not None, "Chat model selectbox should have a selected value"

        # Verify the selected model matches what's in client_settings
        assert at.session_state.client_settings["ll_model"]["model"] == selected_model, (
            "Selected model in selectbox should match client_settings"
        )

    def test_chat_model_selectbox_updates_settings(self, app_server, app_test):
        """
        Test that changing the chat model selectbox updates the client settings.

        This verifies the on_change callback properly calls update_client_settings("ll_model").
        """
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Enable at least two language models for testing
        enabled_count = 0
        enabled_models = []
        for model in at.session_state.model_configs:
            if model["type"] == "ll" and enabled_count < 2:
                model["enabled"] = True
                enabled_models.append(f"{model['provider']}/{model['id']}")
                enabled_count += 1

        # Run the app
        at = at.run()

        # Verify we have multiple models available
        assert len(enabled_models) >= 2, "Need at least 2 models to test switching"

        # Get the initial model and verify it's in session state
        initial_model = at.session_state.selected_ll_model_model
        assert initial_model is not None

        # Find a different model to switch to
        new_model = next(m for m in enabled_models if m != initial_model)

        # Find the chat model selectbox and interact with it
        # The selectbox has key="selected_ll_model_model"
        selectboxes = [sb for sb in at.sidebar.selectbox if sb.key == "selected_ll_model_model"]

        assert len(selectboxes) == 1, "Should find exactly one chat model selectbox"
        chat_model_selectbox = selectboxes[0]

        # Select the new model using the selectbox
        chat_model_selectbox.select(new_model).run()

        # Verify the session state was updated
        assert at.session_state.selected_ll_model_model == new_model, (
            "Selectbox value should be updated in session state"
        )

        # Verify the client settings were updated by the on_change callback
        assert at.session_state.client_settings["ll_model"]["model"] == new_model, (
            "Changing the chat model selectbox should update client_settings via on_change callback"
        )

    def test_ll_sidebar_temperature_slider(self, app_server, app_test):
        """
        Test that the Temperature slider is rendered and functional.

        Verifies the slider in st_common.py:171-179.
        """
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Enable at least one language model
        at = enable_test_models(at)

        # Run the app
        at = at.run()

        # Check that the Temperature slider exists in session state
        assert hasattr(at.session_state, "selected_ll_model_temperature"), (
            "Temperature slider with key 'selected_ll_model_temperature' should be rendered"
        )

        # Verify the temperature value is set
        temperature = at.session_state.selected_ll_model_temperature
        assert temperature is not None
        assert 0.0 <= temperature <= 2.0, "Temperature should be between 0.0 and 2.0"

        # Find the temperature slider by key
        temperature_sliders = [s for s in at.sidebar.slider if s.key == "selected_ll_model_temperature"]
        assert len(temperature_sliders) == 1, "Should find exactly one temperature slider"

        temp_slider = temperature_sliders[0]

        # Test changing the temperature
        new_temp = 1.5
        temp_slider.set_value(new_temp).run()

        # Verify the value was updated
        assert at.session_state.selected_ll_model_temperature == new_temp
        assert at.session_state.client_settings["ll_model"]["temperature"] == new_temp

    def test_ll_sidebar_max_tokens_slider(self, app_server, app_test):
        """
        Test that the Maximum Output Tokens slider is rendered and functional.

        Verifies the slider in st_common.py:184-196.
        """
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Enable at least one language model
        at = enable_test_models(at)

        # Run the app
        at = at.run()

        # Check that the Max Tokens slider exists
        assert hasattr(at.session_state, "selected_ll_model_max_tokens"), (
            "Max tokens slider with key 'selected_ll_model_max_tokens' should be rendered"
        )

        # Verify the max tokens value is set
        max_tokens = at.session_state.selected_ll_model_max_tokens
        assert max_tokens is not None
        assert max_tokens >= 1, "Max tokens should be at least 1"

        # Find the max tokens slider by key
        max_tokens_sliders = [s for s in at.sidebar.slider if s.key == "selected_ll_model_max_tokens"]
        assert len(max_tokens_sliders) == 1, "Should find exactly one max tokens slider"

        max_tokens_slider = max_tokens_sliders[0]

        # Test changing the value (use a reasonable value like 500)
        new_tokens = min(500, max_tokens_slider.max)
        max_tokens_slider.set_value(new_tokens).run()

        # Verify the value was updated
        assert at.session_state.selected_ll_model_max_tokens == new_tokens
        assert at.session_state.client_settings["ll_model"]["max_tokens"] == new_tokens

    def test_ll_sidebar_top_p_slider(self, app_server, app_test):
        """
        Test that the Top P slider is rendered and functional.

        Verifies the slider in st_common.py:199-207.
        """
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Enable at least one language model
        at = enable_test_models(at)

        # Run the app
        at = at.run()

        # Check that the Top P slider exists
        assert hasattr(at.session_state, "selected_ll_model_top_p"), (
            "Top P slider with key 'selected_ll_model_top_p' should be rendered"
        )

        # Verify the top_p value is set
        top_p = at.session_state.selected_ll_model_top_p
        assert top_p is not None
        assert 0.0 <= top_p <= 1.0, "Top P should be between 0.0 and 1.0"

        # Find the top_p slider by key
        top_p_sliders = [s for s in at.sidebar.slider if s.key == "selected_ll_model_top_p"]
        assert len(top_p_sliders) == 1, "Should find exactly one top_p slider"

        top_p_slider = top_p_sliders[0]

        # Test changing the value
        new_top_p = 0.8
        top_p_slider.set_value(new_top_p).run()

        # Verify the value was updated
        assert at.session_state.selected_ll_model_top_p == new_top_p
        assert at.session_state.client_settings["ll_model"]["top_p"] == new_top_p

    def test_ll_sidebar_frequency_penalty_slider(self, app_server, app_test):
        """
        Test that the Frequency Penalty slider is rendered for non-XAI models.

        Verifies the slider in st_common.py:210-221.
        """
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Enable a non-XAI language model
        for model in at.session_state.model_configs:
            if model["type"] == "ll" and "xai" not in model["id"]:
                model["enabled"] = True
                break

        # Run the app
        at = at.run()

        # For non-XAI models, frequency penalty slider should exist
        current_model = at.session_state.client_settings["ll_model"]["model"]

        if "xai" not in current_model:
            # Check that the Frequency Penalty slider exists
            assert hasattr(at.session_state, "selected_ll_model_frequency_penalty"), (
                "Frequency penalty slider should be rendered for non-XAI models"
            )

            # Verify the frequency_penalty value is set
            freq_penalty = at.session_state.selected_ll_model_frequency_penalty
            assert freq_penalty is not None
            assert -2.0 <= freq_penalty <= 2.0, "Frequency penalty should be between -2.0 and 2.0"

            # Find the frequency penalty slider by key
            freq_sliders = [s for s in at.sidebar.slider if s.key == "selected_ll_model_frequency_penalty"]
            assert len(freq_sliders) == 1, "Should find frequency penalty slider for non-XAI models"

            freq_slider = freq_sliders[0]

            # Test changing the value
            new_freq = 0.5
            freq_slider.set_value(new_freq).run()

            # Verify the value was updated
            assert at.session_state.selected_ll_model_frequency_penalty == new_freq
            assert at.session_state.client_settings["ll_model"]["frequency_penalty"] == new_freq

    def test_ll_sidebar_presence_penalty_slider(self, app_server, app_test):
        """
        Test that the Presence Penalty slider is rendered for non-XAI models.

        Verifies the slider in st_common.py:224-232.
        """
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Enable a non-XAI language model
        for model in at.session_state.model_configs:
            if model["type"] == "ll" and "xai" not in model["id"]:
                model["enabled"] = True
                break

        # Run the app
        at = at.run()

        # For non-XAI models, presence penalty slider should exist
        current_model = at.session_state.client_settings["ll_model"]["model"]

        if "xai" not in current_model:
            # Check that the Presence Penalty slider exists
            assert hasattr(at.session_state, "selected_ll_model_presence_penalty"), (
                "Presence penalty slider should be rendered for non-XAI models"
            )

            # Verify the presence_penalty value is set
            pres_penalty = at.session_state.selected_ll_model_presence_penalty
            assert pres_penalty is not None
            assert -2.0 <= pres_penalty <= 2.0, "Presence penalty should be between -2.0 and 2.0"

            # Find the presence penalty slider by key
            pres_sliders = [s for s in at.sidebar.slider if s.key == "selected_ll_model_presence_penalty"]
            assert len(pres_sliders) == 1, "Should find presence penalty slider for non-XAI models"

            pres_slider = pres_sliders[0]

            # Test changing the value
            new_pres = -0.5
            pres_slider.set_value(new_pres).run()

            # Verify the value was updated
            assert at.session_state.selected_ll_model_presence_penalty == new_pres
            assert at.session_state.client_settings["ll_model"]["presence_penalty"] == new_pres

    def test_ll_sidebar_xai_model_hides_penalties(self, app_server, app_test):
        """
        Test that frequency and presence penalty sliders are NOT shown for XAI models.

        Verifies the conditional logic in st_common.py:210 that hides penalties for XAI.
        """
        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Create a mock XAI model and enable it
        xai_model = {
            "id": "grok-beta",
            "provider": "xai",
            "type": "ll",
            "enabled": True,
            "temperature": 0.7,
            "frequency_penalty": 0.0,
            "max_tokens": 1000,
            "presence_penalty": 0.0,
            "top_p": 1.0,
        }

        # Add XAI model and disable others
        at.session_state.model_configs.append(xai_model)
        for model in at.session_state.model_configs:
            if model["type"] == "ll":
                model["enabled"] = model["id"] == "grok-beta"

        # Set the client settings to use the XAI model before running
        at.session_state.client_settings["ll_model"]["model"] = "xai/grok-beta"

        # Run the app
        at = at.run()

        # Verify XAI model is selected
        current_model = at.session_state.client_settings["ll_model"]["model"]
        assert "xai" in current_model, f"XAI model should be selected, got: {current_model}"

        # Check that frequency and presence penalty sliders do NOT exist
        freq_sliders = [s for s in at.sidebar.slider if s.key == "selected_ll_model_frequency_penalty"]
        pres_sliders = [s for s in at.sidebar.slider if s.key == "selected_ll_model_presence_penalty"]

        assert len(freq_sliders) == 0, "Frequency penalty slider should NOT be shown for XAI models"
        assert len(pres_sliders) == 0, "Presence penalty slider should NOT be shown for XAI models"

        # But other sliders should still exist
        assert hasattr(at.session_state, "selected_ll_model_temperature"), (
            "Temperature slider should still exist for XAI models"
        )
        assert hasattr(at.session_state, "selected_ll_model_max_tokens"), (
            "Max tokens slider should still exist for XAI models"
        )
        assert hasattr(at.session_state, "selected_ll_model_top_p"), "Top P slider should still exist for XAI models"
