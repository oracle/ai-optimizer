"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.core.sidebar
"""
# spell-checker: disable

from unittest.mock import call, patch

import pandas as pd
import pytest

from client.tests.conftest import AttrDict, base_test_settings

MODULE = "client.app.core.sidebar"
HELPERS = "client.app.core.helpers"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_state(extra=None):
    """Build a minimal session state for sidebar tests."""
    data = AttrDict(
        {
            "settings": base_test_settings(
                client_settings={
                    "database": {},
                    "ll_model": {},
                    "tools_enabled": [],
                    "vector_search": {},
                },
            ),
            "optimizer_client": "test-client",
            "optimizer_help": {
                "temperature": "help",
                "max_tokens": "help",
                "top_p": "help",
                "frequency_penalty": "help",
                "presence_penalty": "help",
                "top_k": "",
                "score_threshold": "",
                "fetch_k": "",
                "lambda_mult": "",
                "vector_search_discovery": "",
                "vector_search_rephrase": "",
                "vector_search_grade": "",
            },
            "tool_box": {},
        }
    )
    if extra:
        data.update(extra)
    return data


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------
class TestOnModelChange:
    """Tests for _on_model_change."""

    def test_splits_provider_model(self):
        """Verify provider/model string is split and persisted."""
        state = _make_state()
        state["runtime_chat_model_selector"] = "openai/gpt-5"
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _on_model_change

            _on_model_change()
        mock_update.assert_called_once_with({"ll_model": {"provider": "openai", "id": "gpt-5"}})

    def test_noop_when_empty(self):
        """Verify no update when selector value is empty."""
        state = _make_state()
        state["runtime_chat_model_selector"] = ""
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _on_model_change

            _on_model_change()
        mock_update.assert_not_called()

    def test_noop_when_no_slash(self):
        """Verify no update when selector value has no slash separator."""
        state = _make_state()
        state["runtime_chat_model_selector"] = "noslash"
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _on_model_change

            _on_model_change()
        mock_update.assert_not_called()


class TestOnChatHistoryChange:
    """Tests for _on_chat_history_change."""

    def test_persists_checkbox(self):
        """Verify chat history checkbox value is persisted to settings."""
        state = _make_state()
        state["runtime_chat_history_enabled"] = False
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _on_chat_history_change

            _on_chat_history_change()
        mock_update.assert_called_once_with({"ll_model": {"chat_history": False}})


class TestClearServerHistory:
    """Tests for _clear_server_history."""

    def test_calls_api_patch(self):
        """Verify API patch is called to clear server history."""
        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_patch") as mock_patch,
        ):
            from client.app.core.sidebar import _clear_server_history

            _clear_server_history()
        mock_patch.assert_called_once()

    def test_swallows_exception(self):
        """Verify API exceptions are swallowed without propagating."""
        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_patch", side_effect=Exception("fail")),
        ):
            from client.app.core.sidebar import _clear_server_history

            _clear_server_history()  # Should not raise


class TestOnLlModelParamChange:
    """Tests for _on_ll_model_param_change."""

    def test_persists_value(self):
        """Verify model parameter value is persisted to settings."""
        state = _make_state()
        state["runtime_chat_temperature"] = 0.7
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _on_ll_model_param_change

            _on_ll_model_param_change("temperature", "runtime_chat_temperature")
        mock_update.assert_called_once_with({"ll_model": {"temperature": 0.7}})


class TestOnToolsChange:
    """Tests for _on_tools_change."""

    def test_persists_tools_list(self):
        """Verify selected tools list is persisted to settings."""
        state = _make_state()
        state["runtime_tools"] = ["Vector Search"]
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _on_tools_change

            _on_tools_change()
        mock_update.assert_called_once_with({"tools_enabled": ["Vector Search"]})


class TestOnDdsChange:
    """Tests for _on_dds_change (Deep Data Security tool-connection toggle)."""

    def test_persists_enabled_flag(self):
        state = _make_state()
        state["runtime_dds_enabled"] = True
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _on_dds_change

            _on_dds_change()
        mock_update.assert_called_once_with({"deep_data_security": {"enabled": True}})


class TestOnVsSubtoolChange:
    """Tests for _on_vs_subtool_change."""

    def test_persists_discovery_rephrase_grade(self):
        """Verify vector search subtool toggles are persisted."""
        state = _make_state()
        state["runtime_vs_discovery"] = True
        state["runtime_vs_rephrase"] = False
        state["runtime_vs_grade"] = True
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _on_vs_subtool_change

            _on_vs_subtool_change()
        mock_update.assert_called_once_with({"vector_search": {"discovery": True, "rephrase": False, "grade": True}})

    def test_empty_when_no_widget_keys(self):
        """Verify no update when subtool widget keys are absent."""
        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _on_vs_subtool_change

            _on_vs_subtool_change()
        mock_update.assert_not_called()


class TestOnVsParamChange:
    """Tests for _on_vs_param_change."""

    def test_persists_value(self):
        """Verify vector search parameter value is persisted."""
        state = _make_state()
        state["runtime_vs_search_type"] = "Similarity"
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _on_vs_param_change

            _on_vs_param_change("search_type", "runtime_vs_search_type")
        mock_update.assert_called_once_with({"vector_search": {"search_type": "Similarity"}})


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
class TestUsableModelsLookup:
    """Tests for _usable_models_lookup."""

    def test_enabled_and_usable(self):
        """Verify only enabled and usable models are included."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "openai", "status": "available"},
            {"id": "m2", "type": "ll", "enabled": True, "provider": "oci", "status": "unreachable"},
        ]
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import _usable_models_lookup

            result = _usable_models_lookup()
        assert "openai/m1" in result
        assert "oci/m2" not in result

    def test_excludes_non_usable(self):
        """Verify models whose status is not 'available' are excluded."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "p", "status": "unreachable"},
        ]
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import _usable_models_lookup

            result = _usable_models_lookup()
        assert result == {}


class TestVsEmbedKey:
    """Tests for _vs_embed_key."""

    def test_builds_key(self):
        """Verify provider/id key is built from embedding model dict."""
        from client.app.core.sidebar import _vs_embed_key

        vs = {"embedding_model": {"provider": "oci", "id": "emb1"}}
        assert _vs_embed_key(vs) == "oci/emb1"

    def test_empty_for_non_dict(self):
        """Verify empty string returned when embedding_model is not a dict."""
        from client.app.core.sidebar import _vs_embed_key

        assert _vs_embed_key({"embedding_model": "not-a-dict"}) == ""

    def test_empty_for_empty_dict(self):
        """Verify empty string returned when embedding_model dict is empty."""
        from client.app.core.sidebar import _vs_embed_key

        assert _vs_embed_key({"embedding_model": {}}) == ""

    def test_missing_embedding_model(self):
        """Verify empty string returned when embedding_model key is absent."""
        from client.app.core.sidebar import _vs_embed_key

        assert _vs_embed_key({}) == ""


# ---------------------------------------------------------------------------
# Vector Store Selection Helpers
# ---------------------------------------------------------------------------
class TestBuildVsDataframe:
    """Tests for _build_vs_dataframe."""

    def test_model_column_added(self):
        """Verify model column is derived from embedding_model provider/id."""
        from client.app.core.sidebar import _build_vs_dataframe

        stores = [{"alias": "a", "embedding_model": {"provider": "p", "id": "m"}}]
        df = _build_vs_dataframe(stores)
        assert "model" in df.columns
        assert df.iloc[0]["model"] == "p/m"

    def test_empty_list(self):
        """Verify empty dataframe returned for empty store list."""
        from client.app.core.sidebar import _build_vs_dataframe

        df = _build_vs_dataframe([])
        assert df.empty

    def test_keeps_distance_strategy(self):
        """Verify distance_strategy column is preserved as-is."""
        from client.app.core.sidebar import _build_vs_dataframe

        stores = [{"alias": "a", "distance_strategy": "cosine", "embedding_model": {"provider": "p", "id": "m"}}]
        df = _build_vs_dataframe(stores)
        assert "distance_strategy" in df.columns


class TestVsStoreFields:
    """Tests for _vs_store_fields."""

    def test_returns_expected_tuples(self):
        """Verify six label/column tuples are returned."""
        from client.app.core.sidebar import _vs_store_fields

        fields = _vs_store_fields()
        assert len(fields) == 6
        columns = [f[1] for f in fields]
        assert "alias" in columns
        assert "model" in columns
        assert all(isinstance(f, tuple) and len(f) == 2 for f in fields)


class TestVsGetValidOptions:
    """Tests for _vs_get_valid_options."""

    def test_cross_filtering(self):
        """Verify valid options are filtered based on current selections."""
        from client.app.core.sidebar import _vs_get_valid_options

        df = pd.DataFrame(
            {
                "alias": ["a", "a", "b"],
                "model": ["m1", "m2", "m1"],
                "chunk_size": [100, 200, 100],
                "chunk_overlap": [10, 20, 10],
                "distance_strategy": ["cosine", "cosine", "euclidean"],
                "index_type": ["hnsw", "hnsw", "ivf"],
            }
        )
        selections = {
            "alias": "a",
            "model": "",
            "chunk_size": "",
            "chunk_overlap": "",
            "distance_strategy": "",
            "index_type": "",
        }
        result = _vs_get_valid_options(df, "model", selections)
        assert "m1" in result
        assert "m2" in result

    def test_excludes_empty_strings(self):
        """Verify empty string values are excluded from valid options."""
        from client.app.core.sidebar import _vs_get_valid_options

        df = pd.DataFrame(
            {
                "alias": ["a", ""],
                "model": ["m1", ""],
                "chunk_size": [100, 0],
                "chunk_overlap": [10, 0],
                "distance_strategy": ["cosine", ""],
                "index_type": ["hnsw", ""],
            }
        )
        selections = {
            "alias": "",
            "model": "",
            "chunk_size": "",
            "chunk_overlap": "",
            "distance_strategy": "",
            "index_type": "",
        }
        result = _vs_get_valid_options(df, "model", selections)
        assert "" not in result


class TestVsAutoSelect:
    """Tests for _vs_auto_select."""

    def test_single_option_auto_selected(self):
        """Verify single-option fields are automatically selected."""
        from client.app.core.sidebar import _vs_auto_select

        df = pd.DataFrame(
            {
                "alias": ["a"],
                "model": ["m1"],
                "chunk_size": [100],
                "chunk_overlap": [10],
                "distance_strategy": ["cosine"],
                "index_type": ["hnsw"],
            }
        )
        selections = {
            "alias": "",
            "model": "",
            "chunk_size": "",
            "chunk_overlap": "",
            "distance_strategy": "",
            "index_type": "",
        }
        result = _vs_auto_select(df, selections)
        assert result["alias"] == "a"
        assert result["model"] == "m1"

    def test_clears_invalid_selection(self):
        """Verify invalid selections are corrected to valid values."""
        from client.app.core.sidebar import _vs_auto_select

        df = pd.DataFrame(
            {
                "alias": ["a"],
                "model": ["m1"],
                "chunk_size": [100],
                "chunk_overlap": [10],
                "distance_strategy": ["cosine"],
                "index_type": ["hnsw"],
            }
        )
        selections = {
            "alias": "invalid",
            "model": "",
            "chunk_size": "",
            "chunk_overlap": "",
            "distance_strategy": "",
            "index_type": "",
        }
        result = _vs_auto_select(df, selections)
        assert result["alias"] == "a"  # Corrected to valid value


class TestVsGetCurrentSelections:
    """Tests for _vs_get_current_selections."""

    def test_from_widget_state(self):
        """Verify selections are read from widget state keys."""
        state = _make_state()
        state["settings"]["client_settings"]["vector_search"] = {}
        state["runtime_vs_store_alias_0"] = "myalias"
        with patch(f"{MODULE}.state", state):
            from client.app.core.sidebar import _vs_get_current_selections

            result = _vs_get_current_selections(key_version=0)
        assert result["alias"] == "myalias"

    def test_falls_back_to_client_settings(self):
        """Verify fallback to saved client settings when no widget state."""
        state = _make_state()
        state["settings"]["client_settings"]["vector_search"] = {
            "alias": "saved",
            "provider": "oci",
            "id": "emb1",
        }
        with patch(f"{MODULE}.state", state):
            from client.app.core.sidebar import _vs_get_current_selections

            result = _vs_get_current_selections(key_version=0)
        assert result["alias"] == "saved"
        assert result["model"] == "oci/emb1"

    def test_model_empty_when_no_provider(self):
        """Verify model is empty when provider is not in settings."""
        state = _make_state()
        state["settings"]["client_settings"]["vector_search"] = {}
        with patch(f"{MODULE}.state", state):
            from client.app.core.sidebar import _vs_get_current_selections

            result = _vs_get_current_selections(key_version=0)
        assert result["model"] == ""


class TestVsResetSelections:
    """Tests for _vs_reset_selections."""

    def test_clears_fields_and_increments_version(self):
        """Verify selections are cleared and key version is incremented."""
        state = _make_state()
        state["settings"]["client_settings"]["vector_search"] = {"alias": "old"}
        state["_vs_key_version"] = 0
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import _vs_reset_selections

            _vs_reset_selections()
        assert state["_vs_key_version"] == 1
        mock_update.assert_called_once()
        payload = mock_update.call_args[0][0]
        assert payload["vector_search"]["alias"] is None


# ---------------------------------------------------------------------------
# Main UI Functions
# ---------------------------------------------------------------------------
class TestToolkitSidebar:
    """Tests for toolkit_sidebar."""

    def test_no_models_returns_early(self, mock_st):
        """Verify early return when no models are configured."""
        state = _make_state()
        state["settings"]["model_configs"] = []
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import toolkit_sidebar

            toolkit_sidebar()
        mock_st.sidebar.subheader.assert_not_called()

    def test_no_db_disables_tools(self, mock_st):
        """Verify tools are disabled when no database is configured."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "p", "status": "available"},
        ]
        state["settings"]["client_settings"]["tools_enabled"] = []
        state["runtime_tools"] = []
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import toolkit_sidebar

            toolkit_sidebar()
        # Vector Search and NL2SQL should be disabled
        assert state.tool_box["Vector Search"]["enabled"] is False
        assert state.tool_box["NL2SQL"]["enabled"] is False

    def test_happy_path_with_vector_stores(self, mock_st):
        """Verify Vector Search is enabled when vector stores exist."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "p", "status": "available"},
            {"id": "e1", "type": "embed", "enabled": True, "provider": "oci"},
        ]
        state["settings"]["database_configs"] = [
            {
                "alias": "db1",
                "usable": True,
                "vector_stores": [
                    {"embedding_model": {"provider": "oci", "id": "e1"}},
                ],
            },
        ]
        state["settings"]["nl2sql_available"] = True
        state["settings"]["client_settings"]["database"] = {"alias": "db1"}
        state["settings"]["client_settings"]["tools_enabled"] = []
        state["runtime_tools"] = []
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import toolkit_sidebar

            toolkit_sidebar()
        assert state.tool_box["Vector Search"]["enabled"] is True

    def test_small_model_auto_disables_vector_search_subtools(self, mock_st):
        """Verify Vector Search sub-tools are auto-disabled for a newly selected small model."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {
                "id": "llama3.2:1b",
                "type": "ll",
                "enabled": True,
                "provider": "ollama",
                "status": "available",
                "small_model": True,
            },
            {"id": "e1", "type": "embed", "enabled": True, "provider": "oci"},
        ]
        state["settings"]["database_configs"] = [
            {
                "alias": "db1",
                "usable": True,
                "vector_stores": [{"embedding_model": {"provider": "oci", "id": "e1"}}],
            },
        ]
        client_settings = state["settings"]["client_settings"]
        client_settings["database"] = {"alias": "db1"}
        client_settings["ll_model"] = {"provider": "ollama", "id": "llama3.2:1b"}
        client_settings["tools_enabled"] = ["Vector Search"]
        client_settings["vector_search"] = {"discovery": True, "rephrase": True, "grade": True}
        state["runtime_tools"] = ["Vector Search"]
        state["runtime_vs_discovery"] = True
        state["runtime_vs_rephrase"] = True
        state["runtime_vs_grade"] = True

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import toolkit_sidebar

            toolkit_sidebar()

        assert client_settings["vector_search"] == {"discovery": False, "rephrase": False, "grade": False}
        assert state["runtime_vs_discovery"] is False
        assert state["runtime_vs_rephrase"] is False
        assert state["runtime_vs_grade"] is False
        mock_update.assert_called_once_with({"vector_search": {"discovery": False, "rephrase": False, "grade": False}})
        mock_st.sidebar.info.assert_called_once_with("CPU Mode: Additional tools auto-disabled")

    def test_small_model_finishes_cpu_optimization_after_testbed(self, mock_st):
        """Verify Chatbot disables controls that were unavailable on Testbed."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {
                "id": "llama3.2:1b",
                "type": "ll",
                "enabled": True,
                "provider": "ollama",
                "status": "available",
                "small_model": True,
            },
            {"id": "e1", "type": "embed", "enabled": True, "provider": "oci"},
        ]
        state["settings"]["database_configs"] = [
            {
                "alias": "db1",
                "usable": True,
                "vector_stores": [{"embedding_model": {"provider": "oci", "id": "e1"}}],
            },
        ]
        client_settings = state["settings"]["client_settings"]
        client_settings["database"] = {"alias": "db1"}
        client_settings["ll_model"] = {"provider": "ollama", "id": "llama3.2:1b"}
        client_settings["tools_enabled"] = ["Vector Search"]
        client_settings["vector_search"] = {"discovery": True, "rephrase": True, "grade": True}
        state["runtime_tools"] = ["Vector Search"]
        state["runtime_vs_discovery"] = True
        state["runtime_vs_rephrase"] = True
        state["runtime_vs_grade"] = True

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import toolkit_sidebar

            toolkit_sidebar(show_vs_subtools=False)
            assert client_settings["vector_search"] == {"discovery": False, "rephrase": True, "grade": True}

            toolkit_sidebar(show_vs_subtools=True)
            assert client_settings["vector_search"] == {"discovery": False, "rephrase": False, "grade": False}

            client_settings["vector_search"].update({"rephrase": True, "grade": True})
            state["runtime_vs_rephrase"] = True
            state["runtime_vs_grade"] = True
            toolkit_sidebar(show_vs_subtools=True)

        assert client_settings["vector_search"] == {"discovery": False, "rephrase": True, "grade": True}
        assert mock_update.call_args_list == [
            call({"vector_search": {"discovery": False}}),
            call({"vector_search": {"rephrase": False, "grade": False}}),
        ]

    def test_nl2sql_disabled_when_proxy_unavailable(self, mock_st):
        """Verify NL2SQL is disabled when nl2sql_available is False."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "p", "status": "available"},
        ]
        state["settings"]["database_configs"] = [
            {"alias": "db1", "usable": True, "vector_stores": []},
        ]
        state["settings"]["nl2sql_available"] = False
        state["settings"]["client_settings"]["database"] = {"alias": "db1"}
        state["settings"]["client_settings"]["tools_enabled"] = []
        state["runtime_tools"] = []
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import toolkit_sidebar

            toolkit_sidebar()
        assert state.tool_box["NL2SQL"]["enabled"] is False

    def test_nl2sql_enabled_when_proxy_available(self, mock_st):
        """Verify NL2SQL is enabled when nl2sql_available is True."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "p", "status": "available"},
        ]
        state["settings"]["database_configs"] = [
            {"alias": "db1", "usable": True, "vector_stores": []},
        ]
        state["settings"]["nl2sql_available"] = True
        state["settings"]["client_settings"]["database"] = {"alias": "db1"}
        state["settings"]["client_settings"]["tools_enabled"] = []
        state["runtime_tools"] = []
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import toolkit_sidebar

            toolkit_sidebar()
        assert state.tool_box["NL2SQL"]["enabled"] is True

    def test_prunes_invalid_tools(self, mock_st):
        """Verify tools without required resources are pruned from enabled list."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "p", "status": "available"},
        ]
        state["settings"]["client_settings"]["tools_enabled"] = ["Vector Search", "NL2SQL"]
        state["runtime_tools"] = []
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import toolkit_sidebar

            toolkit_sidebar()
        # Both tools should be pruned since no DB configured
        assert state["settings"]["client_settings"]["tools_enabled"] == []

    def test_hides_deep_data_security_for_language_model_only(self, mock_st):
        """Verify Deep Data Security is hidden when no chat tools are selected."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "p", "status": "available"},
        ]
        state["settings"]["database_configs"] = [
            {"alias": "db1", "usable": True, "vector_stores": []},
        ]
        client_settings = state["settings"]["client_settings"]
        client_settings["database"] = {"alias": "db1"}
        client_settings["tools_enabled"] = []
        client_settings["deep_data_security"] = {
            "base_alias": "db1",
            "enabled": True,
            "end_user": "SCOUT1",
        }
        state["runtime_tools"] = []
        state["runtime_dds_enabled"] = True

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import toolkit_sidebar

            toolkit_sidebar()

        assert all(call.args[0] != "Deep Data Security" for call in mock_st.sidebar.checkbox.call_args_list)

    def test_auto_configures_single_dds_end_user_for_selected_chat_tool(self, mock_st):
        """A single DDS end user is ready before the user visits the Tools page."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "p", "status": "available"},
        ]
        state["settings"]["database_configs"] = [
            {"alias": "db1", "usable": True, "vector_stores": []},
        ]
        client_settings = state["settings"]["client_settings"]
        client_settings["database"] = {"alias": "db1"}
        client_settings["tools_enabled"] = ["NL2SQL"]
        state["runtime_tools"] = ["NL2SQL"]
        state["runtime_dds_enabled"] = False

        def _update_settings(payload):
            client_settings["deep_data_security"] = payload["deep_data_security"]
            return client_settings

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
            patch(f"{MODULE}.is_authenticated", return_value=True, create=True),
            patch(f"{MODULE}.api_get", return_value=[{"name": "SCOUT1"}], create=True) as mock_get,
            patch(
                f"{MODULE}.api_post",
                return_value={"alias": "DB1::SCOUT1", "base_alias": "db1", "end_user": "SCOUT1"},
                create=True,
            ) as mock_post,
            patch(f"{MODULE}.update_client_settings", side_effect=_update_settings),
        ):
            from client.app.core.sidebar import toolkit_sidebar

            toolkit_sidebar()

        mock_get.assert_called_once_with("deepsec/end-users", extra_headers={"client": "test-client"})
        mock_post.assert_called_once_with(
            "deepsec/connect-as",
            json={"end_user": "SCOUT1"},
            extra_headers={"client": "test-client"},
            timeout=60,
        )
        assert any(call.args[0] == "Deep Data Security" for call in mock_st.sidebar.checkbox.call_args_list)


class TestHistorySidebar:
    """Tests for history_sidebar."""

    def test_no_models_returns_early(self, mock_st):
        """Verify early return when no models are configured."""
        state = _make_state()
        state["settings"]["model_configs"] = []
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import history_sidebar

            history_sidebar()
        mock_st.sidebar.subheader.assert_not_called()

    def test_renders_widgets(self, mock_st):
        """Verify sidebar widgets are rendered when models exist."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "p", "status": "available"},
        ]
        state["settings"]["client_settings"]["ll_model"] = {"chat_history": True}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import history_sidebar

            history_sidebar()
        mock_st.sidebar.subheader.assert_called_once()


class TestLmSidebar:
    """Tests for lm_sidebar."""

    def test_returns_model_options(self, mock_st):
        """Verify usable model options are returned."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "openai", "status": "available"},
        ]
        state["settings"]["client_settings"]["ll_model"] = {"provider": "openai", "id": "m1"}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import lm_sidebar

            result = lm_sidebar()
        assert result == ["openai/m1"]

    def test_empty_models(self, mock_st):
        """Verify empty list returned when no models are configured."""
        state = _make_state()
        state["settings"]["model_configs"] = []
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import lm_sidebar

            result = lm_sidebar()
        assert not result

    def test_renders_sliders(self, mock_st):
        """Verify all model parameter sliders and selectbox are rendered."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "p", "status": "available"},
        ]
        state["settings"]["client_settings"]["ll_model"] = {"provider": "p", "id": "m1", "temperature": 0.5}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import lm_sidebar

            lm_sidebar()
        # Temperature, Max Output Tokens, Top P, Frequency Penalty, Presence Penalty = 5 sliders
        assert mock_st.sidebar.slider.call_count == 5
        assert mock_st.sidebar.selectbox.call_count == 1

    def test_auto_persists_first_model_when_none_selected(self, mock_st):
        """When client_settings has no ll_model provider/id but usable models exist,
        the selectbox silently defaults to index 0 — so lm_sidebar must persist
        that selection, otherwise the server sees ll_model.{provider,id}=None and
        chat prompts fail with 'No language model configured'.
        """
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "cohere.command-r-plus", "type": "ll", "enabled": True, "provider": "oci", "status": "available"},
            {"id": "meta.llama-3", "type": "ll", "enabled": True, "provider": "oci", "status": "available"},
        ]
        state["settings"]["client_settings"]["ll_model"] = {}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import lm_sidebar

            lm_sidebar()
        mock_update.assert_any_call({"ll_model": {"provider": "oci", "id": "cohere.command-r-plus"}})

    def test_no_persist_when_current_model_valid(self, mock_st):
        """Verify update_client_settings is NOT called when the saved ll_model is already
        in the usable options — guards against a rerender loop."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "openai", "status": "available"},
        ]
        state["settings"]["client_settings"]["ll_model"] = {"provider": "openai", "id": "m1"}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
            patch(f"{MODULE}.update_client_settings") as mock_update,
        ):
            from client.app.core.sidebar import lm_sidebar

            lm_sidebar()
        mock_update.assert_not_called()


class TestVectorSearchSidebar:
    """Tests for vector_search_sidebar."""

    def test_not_enabled_returns_early(self, mock_st):
        """Verify early return when Vector Search is not enabled."""
        state = _make_state()
        state["settings"]["client_settings"]["tools_enabled"] = []
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.core.sidebar import vector_search_sidebar

            vector_search_sidebar()
        mock_st.sidebar.subheader.assert_not_called()

    def test_renders_search_type(self, mock_st):
        """Verify search type selectbox and Top K input are rendered."""
        state = _make_state()
        state["settings"]["client_settings"]["tools_enabled"] = ["Vector Search"]
        state["settings"]["client_settings"]["vector_search"] = {"search_type": "Similarity"}
        state["settings"]["database_configs"] = []
        state["runtime_vs_search_type"] = "Similarity"
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.vector_store_selection"),
        ):
            from client.app.core.sidebar import vector_search_sidebar

            vector_search_sidebar()
        mock_st.sidebar.selectbox.assert_called_once()
        mock_st.sidebar.number_input.assert_called_once()  # Top K

    def test_similarity_params(self, mock_st):
        """Verify Similarity search type renders score threshold slider."""
        state = _make_state()
        state["settings"]["client_settings"]["tools_enabled"] = ["Vector Search"]
        state["settings"]["client_settings"]["vector_search"] = {}
        state["settings"]["database_configs"] = []
        state["runtime_vs_search_type"] = "Similarity"
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.vector_store_selection"),
        ):
            from client.app.core.sidebar import vector_search_sidebar

            vector_search_sidebar()
        # Score Threshold slider
        assert mock_st.sidebar.slider.call_count == 1

    def test_mmr_params(self, mock_st):
        """Verify MMR search type renders fetch_k, diversity, and Top K inputs."""
        state = _make_state()
        state["settings"]["client_settings"]["tools_enabled"] = ["Vector Search"]
        state["settings"]["client_settings"]["vector_search"] = {}
        state["settings"]["database_configs"] = []
        state["runtime_vs_search_type"] = "Maximal Marginal Relevance"
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.vector_store_selection"),
        ):
            from client.app.core.sidebar import vector_search_sidebar

            vector_search_sidebar()
        # Fetch K number_input + Top K = 2 number_inputs
        assert mock_st.sidebar.number_input.call_count == 2
        # Degree of Diversity slider
        assert mock_st.sidebar.slider.call_count == 1


# ---------------------------------------------------------------------------
# _disable_tool
# ---------------------------------------------------------------------------
class TestDisableTool:
    """Tests for _disable_tool."""

    def test_disables_tool(self, mock_st):
        """Verify tool is disabled and warning is shown when reason provided."""
        state = _make_state()
        state.tool_box = {"Vector Search": {"enabled": True}}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.core.sidebar import _disable_tool

            _disable_tool("Vector Search", "No DB")
        assert state.tool_box["Vector Search"]["enabled"] is False
        mock_st.warning.assert_called_once()

    def test_disables_without_reason(self, mock_st):
        """Verify tool is disabled without warning when no reason given."""
        state = _make_state()
        state.tool_box = {"NL2SQL": {"enabled": True}}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.core.sidebar import _disable_tool

            _disable_tool("NL2SQL")
        assert state.tool_box["NL2SQL"]["enabled"] is False
        mock_st.sidebar.warning.assert_not_called()


# ---------------------------------------------------------------------------
# _is_small_model
# ---------------------------------------------------------------------------
class TestIsSmallModel:
    """Tests for _is_small_model."""

    def test_true_when_model_config_says_small(self):
        """Verify returns True when model config has small_model=True."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "llama3.2:1b", "type": "ll", "provider": "ollama", "small_model": True},
        ]
        state["settings"]["client_settings"]["ll_model"] = {"provider": "ollama", "id": "llama3.2:1b"}
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import _is_small_model

            assert _is_small_model(state["settings"]["client_settings"]) is True

    def test_false_when_model_config_says_not_small(self):
        """Verify returns False when model config has small_model=False."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "llama3:70b", "type": "ll", "provider": "ollama", "small_model": False},
        ]
        state["settings"]["client_settings"]["ll_model"] = {"provider": "ollama", "id": "llama3:70b"}
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import _is_small_model

            assert _is_small_model(state["settings"]["client_settings"]) is False

    def test_false_when_no_model_config_found(self):
        """Verify returns False when model id is not in model_configs."""
        state = _make_state()
        state["settings"]["model_configs"] = []
        state["settings"]["client_settings"]["ll_model"] = {"provider": "openai", "id": "gpt-5-mini"}
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import _is_small_model

            assert _is_small_model(state["settings"]["client_settings"]) is False

    def test_false_when_no_ll_model(self):
        """Verify returns False when ll_model is empty."""
        state = _make_state()
        state["settings"]["model_configs"] = []
        state["settings"]["client_settings"]["ll_model"] = {}
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.core.sidebar import _is_small_model

            assert _is_small_model(state["settings"]["client_settings"]) is False


# ---------------------------------------------------------------------------
# _render_vs_subtools
# ---------------------------------------------------------------------------
class TestRenderVsSubtools:
    """Tests for _render_vs_subtools."""

    def test_large_model_does_not_warn(self, mock_st):
        """Verify rephrase and grade render without a small-model warning."""
        state = _make_state()
        vs_settings = {"rephrase": True, "grade": True}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.core.sidebar import _render_vs_subtools

            _render_vs_subtools(vs_settings, small_model=False)
        assert vs_settings["rephrase"] is True
        assert vs_settings["grade"] is True
        mock_st.sidebar.warning.assert_not_called()
