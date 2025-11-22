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
# Test Vector Search Tool Selection
#############################################################################
class TestVectorSearchToolSelection:
    """Test the Vector Search tool selection behavior in chatbot.py sidebar"""

    ST_FILE = "../src/client/content/chatbot.py"

    def test_vector_search_not_shown_when_no_enabled_embedding_models(self, app_server, app_test, auth_headers):
        """
        Test that Vector Search option is NOT shown in Tool Selection selectbox
        when vector stores exist but their embedding models are not enabled.

        This test currently FAILS and detects the bug.

        Scenario:
        - Database has vector stores that use "openai/text-embedding-3-small"
        - That OpenAI model is NOT enabled
        - But a different embedding model (Cohere) IS enabled
        - tools_sidebar() only checks if ANY embedding models exist (line 291)
        - It doesn't check if those models match the vector store models

        Expected behavior:
        - Vector Search should NOT appear in Tool Selection (no usable vector stores)
        - User should only see "LLM Only" option

        Current broken behavior:
        - Vector Search appears in Tool Selection
        - When selected, render_vector_store_selection() filters out all vector stores
        - User sees "Please select existing Vector Store options" with disabled dropdowns
        - User gets stuck with unusable UI

        Location of bug: src/client/utils/st_common.py:290-303
        The check needs to verify that enabled models actually match vector store models,
        not just that some embedding models are enabled.
        """
        import requests
        from conftest import TEST_CONFIG

        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Load full config like launch_client.py does (line 56-64)
        full_config = requests.get(
            url=f"{at.session_state.server['url']}:{at.session_state.server['port']}/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": TEST_CONFIG["client"], "full_config": True, "incl_sensitive": True, "incl_readonly": True},
            timeout=120,
        ).json()
        for key, value in full_config.items():
            at.session_state[key] = value

        at.run()

        # Modify session state to simulate the problematic scenario:
        # - Database is connected and has vector stores that use specific models
        # - Those specific models are NOT enabled
        # - But OTHER embedding models ARE enabled (so embed_models_enabled is not empty)
        # This causes the bug: Vector Search appears but no vector stores are actually usable

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
                    "index_type": "IVF"
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
                    model["enabled"] = True   # Enable a different model
                else:
                    model["enabled"] = False

        # Ensure at least one language model is enabled so the app runs
        ll_enabled = False
        for model in at.session_state.model_configs:
            if model["type"] == "ll" and model["enabled"]:
                ll_enabled = True
                break

        if not ll_enabled:
            # Enable the first LL model we find
            for model in at.session_state.model_configs:
                if model["type"] == "ll":
                    model["enabled"] = True
                    break

        # Re-run with modified state
        at.run()

        # Get the Tool Selection selectbox
        selectboxes = [sb for sb in at.selectbox if sb.label == "Tool Selection"]

        # The bug: Vector Search appears as an option even when its vector stores can't be used
        # Scenario: embed models ARE enabled, but they don't match the vector store models
        # Expected: Vector Search should NOT appear (or should check model compatibility)
        # Bug: Vector Search appears but render_vector_store_selection filters everything out
        if selectboxes:
            tool_selectbox = selectboxes[0]
            # THIS SHOULD FAIL - Vector Search should NOT be in the options when
            # the enabled embedding models don't match any vector store models
            assert "Vector Search" not in tool_selectbox.options, (
                f"BUG DETECTED: Vector Search appears in Tool Selection even though no vector stores "
                f"are usable (enabled models don't match vector store models). "
                f"Found options: {tool_selectbox.options}"
            )

    def test_vector_search_disabled_when_selected_with_no_enabled_models(self, app_server, app_test, auth_headers):
        """
        Test that demonstrates the broken UX when Vector Search is selected
        but no embedding models are enabled.

        This test shows what happens when a user manages to select Vector Search
        despite having no enabled embedding models - all the vector store selection
        dropdowns become disabled, creating a poor user experience.

        This test documents the current broken behavior that will be fixed.
        """
        import requests
        from conftest import TEST_CONFIG

        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Load full config like launch_client.py does
        full_config = requests.get(
            url=f"{at.session_state.server['url']}:{at.session_state.server['port']}/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": TEST_CONFIG["client"], "full_config": True, "incl_sensitive": True, "incl_readonly": True},
            timeout=120,
        ).json()
        for key, value in full_config.items():
            at.session_state[key] = value

        at.run()

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
                    "index_type": "IVF"
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

        # Try to select Vector Search if it exists in options (this is the bug)
        selectboxes = [sb for sb in at.selectbox if sb.label == "Tool Selection"]

        if selectboxes and "Vector Search" in selectboxes[0].options:
            # This is the buggy behavior - Vector Search shouldn't be an option
            tool_selectbox = selectboxes[0]

            # Try to select it
            tool_selectbox.set_value("Vector Search").run()

            # Now check that vector store selection is broken
            # Should see "Vector Store" subheader
            subheaders = [sh.value for sh in at.sidebar.subheader]
            assert "Vector Store" in subheaders, (
                "Vector Store subheader should appear but user cannot select anything"
            )

            # Check that we end up in a broken state with info message
            info_messages = [i.value for i in at.info]
            assert any(
                "Please select existing Vector Store options" in msg
                for msg in info_messages
            ), "Should show info message about selecting vector store options (broken UX)"

    def test_vector_search_shown_when_embedding_models_enabled(self, app_server, app_test, auth_headers):
        """
        Test that Vector Search option IS shown when vector stores exist
        AND their embedding models are enabled.

        This is the happy path - when everything is configured correctly.
        """
        import requests
        from conftest import TEST_CONFIG

        assert app_server is not None
        at = app_test(self.ST_FILE)

        # Load full config like launch_client.py does
        full_config = requests.get(
            url=f"{at.session_state.server['url']}:{at.session_state.server['port']}/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": TEST_CONFIG["client"], "full_config": True, "incl_sensitive": True, "incl_readonly": True},
            timeout=120,
        ).json()
        for key, value in full_config.items():
            at.session_state[key] = value

        at.run()

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
                    "index_type": "IVF"
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
