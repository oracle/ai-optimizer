# pylint: disable=protected-access,import-error,import-outside-toplevel,redefined-outer-name
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch, MagicMock

import pytest
import streamlit as st
from streamlit import session_state as state

from client.utils import vs_options


#############################################################################
# Fixtures
#############################################################################
@pytest.fixture
def vector_store_state(sample_vector_store_data):
    """Setup common vector store state for tests using shared test data"""
    # Setup initial state with vector search settings
    state.client_settings = {
        "vector_search": {
            "enabled": True,
            "discovery": False,
            **sample_vector_store_data,
            "top_k": 10,
            "search_type": "Similarity",
            "score_threshold": 0.5,
            "fetch_k": 20,
            "lambda_mult": 0.5,
        },
        "database": {"alias": "DEFAULT"},
        "ll_model": {"model": "gpt-4", "temperature": 0.8},
    }
    state.database_configs = [
        {"name": "DEFAULT", "vector_stores": [sample_vector_store_data]}
    ]
    state.model_configs = [
        {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True}
    ]
    state["_vs_key_version"] = 0

    yield state

    # Cleanup after test
    for key in list(state.keys()):
        if key.startswith("vs_") or key.startswith("_vs_"):
            del state[key]


#############################################################################
# Test Discovery Mode - Integration Tests
#############################################################################
class TestDiscoveryModeIntegration:
    """Integration tests for discovery mode skipping vector store selection"""

    def test_discovery_true_sidebar_skips_selection(self, app_server, vector_store_state):
        """Test that discovery=True with sidebar location skips vector store selection UI"""
        assert app_server is not None

        # Enable discovery mode
        vector_store_state.client_settings["vector_search"]["discovery"] = True

        subheader_called = False

        def mock_subheader(*_args, **_kwargs):
            nonlocal subheader_called
            subheader_called = True

        with patch.object(st.sidebar, "subheader", side_effect=mock_subheader):
            vs_options.vector_store_selection(location="sidebar")

        # UI should NOT be rendered when discovery=True and location=sidebar
        assert not subheader_called

    def test_discovery_true_main_renders_selection(self, app_server, vector_store_state):
        """Test that discovery=True with main location still renders vector store selection UI"""
        assert app_server is not None

        # Enable discovery mode
        vector_store_state.client_settings["vector_search"]["discovery"] = True

        subheader_called = False

        def mock_subheader(*_args, **_kwargs):
            nonlocal subheader_called
            subheader_called = True

        # Create mock columns with selectbox method
        def create_mock_columns(spec):
            return [MagicMock(selectbox=MagicMock(return_value="")) for _ in spec]

        with (
            patch.object(st, "subheader", side_effect=mock_subheader),
            patch.object(st, "button"),
            patch.object(st, "selectbox", return_value=""),
            patch.object(st, "empty", return_value=MagicMock()),
            patch.object(st, "columns", side_effect=create_mock_columns),
        ):
            vs_options.vector_store_selection(location="main")

        # UI SHOULD be rendered when location=main (regardless of discovery setting)
        assert subheader_called

    def test_discovery_false_sidebar_renders_selection(self, app_server, vector_store_state):
        """Test that discovery=False with sidebar location renders vector store selection UI"""
        assert app_server is not None

        # Explicitly disable discovery mode
        vector_store_state.client_settings["vector_search"]["discovery"] = False

        subheader_called = False

        def mock_subheader(*_args, **_kwargs):
            nonlocal subheader_called
            subheader_called = True

        with (
            patch.object(st.sidebar, "subheader", side_effect=mock_subheader),
            patch.object(st.sidebar, "button"),
            patch.object(st.sidebar, "selectbox", return_value=""),
            patch.object(st, "empty", return_value=MagicMock()),
        ):
            vs_options.vector_store_selection(location="sidebar")

        # UI SHOULD be rendered when discovery=False
        assert subheader_called

    def test_discovery_missing_sidebar_renders_selection(self, app_server, sample_vector_store_data):
        """Test that missing discovery key (defaults to False) renders vector store selection UI"""
        assert app_server is not None

        # Setup state WITHOUT discovery key
        state.client_settings = {
            "vector_search": {
                "enabled": True,
                **sample_vector_store_data,
                "top_k": 10,
                "search_type": "Similarity",
                # NOTE: no "discovery" key
            },
            "database": {"alias": "DEFAULT"},
        }
        state.database_configs = [
            {"name": "DEFAULT", "vector_stores": [sample_vector_store_data]}
        ]
        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True}
        ]
        state["_vs_key_version"] = 0

        subheader_called = False

        def mock_subheader(*_args, **_kwargs):
            nonlocal subheader_called
            subheader_called = True

        with (
            patch.object(st.sidebar, "subheader", side_effect=mock_subheader),
            patch.object(st.sidebar, "button"),
            patch.object(st.sidebar, "selectbox", return_value=""),
            patch.object(st, "empty", return_value=MagicMock()),
        ):
            vs_options.vector_store_selection(location="sidebar")

        # UI SHOULD be rendered when discovery key is missing (defaults to False)
        assert subheader_called


#############################################################################
# Test Vector Store Reset Button Functionality - Integration Tests
#############################################################################
class TestVectorStoreResetButtonIntegration:
    """Integration tests for vector store selection Reset button"""

    def test_reset_button_callback_execution(self, app_server, vector_store_state):
        """Test that the Reset button callback is properly executed when clicked"""
        assert app_server is not None
        assert vector_store_state is not None

        reset_callback_executed = False

        def mock_button(label, **kwargs):
            nonlocal reset_callback_executed
            if "Reset" in label and "on_click" in kwargs:
                # Execute the callback to simulate button click
                kwargs["on_click"]()
                reset_callback_executed = True
            return True

        with (
            patch.object(st.sidebar, "subheader"),
            patch.object(st.sidebar, "button", side_effect=mock_button),
            patch.object(st.sidebar, "selectbox", return_value=""),
            patch.object(st, "empty", return_value=MagicMock()),
        ):
            vs_options.vector_store_selection(location="sidebar")

            # Verify reset callback was executed
            assert reset_callback_executed

            # Verify client_settings are cleared
            assert state.client_settings["vector_search"]["model"] == ""
            assert state.client_settings["vector_search"]["chunk_size"] == ""
            assert state.client_settings["vector_search"]["chunk_overlap"] == ""
            assert state.client_settings["vector_search"]["distance_metric"] == ""
            assert state.client_settings["vector_search"]["vector_store"] == ""
            assert state.client_settings["vector_search"]["alias"] == ""
            assert state.client_settings["vector_search"]["index_type"] == ""

    def test_reset_preserves_non_vector_store_settings(self, app_server, vector_store_state):
        """Test that Reset only affects vector store fields, not other settings"""
        assert app_server is not None
        assert vector_store_state is not None

        def mock_button(label, **kwargs):
            if "Reset" in label and "on_click" in kwargs:
                kwargs["on_click"]()
            return True

        with (
            patch.object(st.sidebar, "subheader"),
            patch.object(st.sidebar, "button", side_effect=mock_button),
            patch.object(st.sidebar, "selectbox", return_value=""),
            patch.object(st, "empty", return_value=MagicMock()),
        ):
            vs_options.vector_store_selection(location="sidebar")

            # Vector store fields should be cleared
            assert state.client_settings["vector_search"]["model"] == ""
            assert state.client_settings["vector_search"]["alias"] == ""

            # Other settings should be preserved
            assert state.client_settings["vector_search"]["top_k"] == 10
            assert state.client_settings["vector_search"]["search_type"] == "Similarity"
            assert state.client_settings["vector_search"]["score_threshold"] == 0.5
            assert state.client_settings["database"]["alias"] == "DEFAULT"
            assert state.client_settings["ll_model"]["model"] == "gpt-4"
            assert state.client_settings["ll_model"]["temperature"] == 0.8

    def test_auto_population_after_reset_single_option(self, app_server, sample_vector_store_data):
        """Test that fields with single options are auto-populated after reset"""
        assert app_server is not None

        # Setup clean state with single vector store option
        single_vs = sample_vector_store_data.copy()
        single_vs["alias"] = "single_alias"
        single_vs["vector_store"] = "single_vs"

        state.client_settings = {
            "vector_search": {
                "enabled": True,
                "model": "",
                "chunk_size": "",
                "chunk_overlap": "",
                "distance_metric": "",
                "vector_store": "",
                "alias": "",
                "index_type": "",
                "top_k": 10,
                "search_type": "Similarity",
                "score_threshold": 0.5,
                "fetch_k": 20,
                "lambda_mult": 0.5,
            },
            "database": {"alias": "DEFAULT"},
        }
        state.database_configs = [
            {"name": "DEFAULT", "vector_stores": [single_vs]}
        ]
        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True}
        ]
        state["_vs_key_version"] = 0

        # Track selectbox return values
        def mock_selectbox(_label, options, **_kwargs):
            # Return the auto-selected value (single option gets auto-selected)
            if len(options) == 2:  # ["", "value"]
                return options[1]
            return ""

        with (
            patch.object(st.sidebar, "subheader"),
            patch.object(st.sidebar, "button"),
            patch.object(st.sidebar, "selectbox", side_effect=mock_selectbox),
            patch.object(st, "empty", return_value=MagicMock()),
        ):
            vs_options.vector_store_selection(location="sidebar")

            # Verify auto-population happened for single options
            assert state.client_settings["vector_search"]["alias"] == "single_alias"
            assert state.client_settings["vector_search"]["model"] == sample_vector_store_data["model"]
            assert state.client_settings["vector_search"]["chunk_size"] == sample_vector_store_data["chunk_size"]

    def test_no_auto_population_with_multiple_options(
        self, app_server, sample_vector_store_data, sample_vector_store_data_alt
    ):
        """Test that fields with multiple options are NOT auto-populated after reset"""
        assert app_server is not None

        # Setup with multiple vector stores having different values
        vs1 = sample_vector_store_data.copy()
        vs1["alias"] = "alias1"
        vs2 = sample_vector_store_data_alt.copy()
        vs2["alias"] = "alias2"

        state.client_settings = {
            "vector_search": {
                "enabled": True,
                "model": "",
                "chunk_size": "",
                "chunk_overlap": "",
                "distance_metric": "",
                "vector_store": "",
                "alias": "",
                "index_type": "",
                "top_k": 10,
                "search_type": "Similarity",
                "score_threshold": 0.5,
                "fetch_k": 20,
                "lambda_mult": 0.5,
            },
            "database": {"alias": "DEFAULT"},
        }
        state.database_configs = [
            {"name": "DEFAULT", "vector_stores": [vs1, vs2]}
        ]
        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True}
        ]
        state["_vs_key_version"] = 0

        with (
            patch.object(st.sidebar, "subheader"),
            patch.object(st.sidebar, "button"),
            patch.object(st.sidebar, "selectbox", return_value=""),
            patch.object(st, "empty", return_value=MagicMock()),
        ):
            vs_options.vector_store_selection(location="sidebar")

            # With multiple options for alias, it should remain empty (no auto-population)
            assert state.client_settings["vector_search"]["alias"] == ""
            # Model is the same for both, so it should be auto-selected
            assert state.client_settings["vector_search"]["model"] == "openai/text-embed-3"

    def test_reset_button_with_filtered_dataframe(
        self, app_server, sample_vector_store_data, sample_vector_store_data_alt
    ):
        """Test reset button behavior with dynamically filtered dataframes"""
        assert app_server is not None

        # Setup with multiple vector stores
        vs1 = sample_vector_store_data.copy()
        vs1["alias"] = "alias1"
        vs2 = sample_vector_store_data_alt.copy()
        vs2["alias"] = "alias1"  # Same alias, different other fields

        state.client_settings = {
            "vector_search": {
                "enabled": True,
                "model": sample_vector_store_data["model"],
                "chunk_size": sample_vector_store_data["chunk_size"],
                "chunk_overlap": "",
                "distance_metric": "",
                "vector_store": "",
                "alias": "alias1",
                "index_type": "",
                "top_k": 10,
                "search_type": "Similarity",
                "score_threshold": 0.5,
                "fetch_k": 20,
                "lambda_mult": 0.5,
            },
            "database": {"alias": "DEFAULT"},
        }
        state.database_configs = [
            {"name": "DEFAULT", "vector_stores": [vs1, vs2]}
        ]
        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True}
        ]
        state["_vs_key_version"] = 0

        def mock_button(label, **kwargs):
            if "Reset" in label and "on_click" in kwargs:
                kwargs["on_click"]()
            return True

        with (
            patch.object(st.sidebar, "subheader"),
            patch.object(st.sidebar, "button", side_effect=mock_button),
            patch.object(st.sidebar, "selectbox", return_value=""),
            patch.object(st, "empty", return_value=MagicMock()),
        ):
            vs_options.vector_store_selection(location="sidebar")

            # After reset, all selection fields should be cleared
            assert state.client_settings["vector_search"]["alias"] == ""
            assert state.client_settings["vector_search"]["model"] == ""
            assert state.client_settings["vector_search"]["chunk_size"] == ""
