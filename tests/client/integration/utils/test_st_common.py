# pylint: disable=protected-access,import-error,import-outside-toplevel,redefined-outer-name
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch

import pandas as pd
import pytest
import streamlit as st
from streamlit import session_state as state

from client.utils import st_common


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

    # Set widget states to simulate user selections
    state.selected_vector_search_model = sample_vector_store_data["model"]
    state.selected_vector_search_chunk_size = sample_vector_store_data["chunk_size"]
    state.selected_vector_search_chunk_overlap = sample_vector_store_data["chunk_overlap"]
    state.selected_vector_search_distance_metric = sample_vector_store_data["distance_metric"]
    state.selected_vector_search_alias = sample_vector_store_data["alias"]
    state.selected_vector_search_index_type = sample_vector_store_data["index_type"]

    yield state

    # Cleanup after test
    for key in list(state.keys()):
        if key.startswith("selected_vector_search_"):
            del state[key]


#############################################################################
# Test Vector Store Reset Button Functionality - Integration Tests
#############################################################################
class TestVectorStoreResetButtonIntegration:
    """Integration tests for vector store selection Reset button"""

    def test_reset_button_callback_execution(self, app_server, vector_store_state, sample_vector_store_data):
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
            patch.object(st.sidebar, "selectbox"),
            patch.object(st, "info"),
        ):
            # Create test dataframe using shared test data
            vs_df = pd.DataFrame([sample_vector_store_data])

            # Mock enabled models
            with patch.object(st_common, "enabled_models_lookup") as mock_models:
                mock_models.return_value = {"openai/text-embed-3": {"id": "text-embed-3"}}

                # Call the function
                st_common.render_vector_store_selection(vs_df)

            # Verify reset callback was executed
            assert reset_callback_executed

            # Verify all widget states are cleared
            assert state.selected_vector_search_model == ""
            assert state.selected_vector_search_chunk_size == ""
            assert state.selected_vector_search_chunk_overlap == ""
            assert state.selected_vector_search_distance_metric == ""
            assert state.selected_vector_search_alias == ""
            assert state.selected_vector_search_index_type == ""

            # Verify client_settings are also cleared
            assert state.client_settings["vector_search"]["model"] == ""
            assert state.client_settings["vector_search"]["chunk_size"] == ""
            assert state.client_settings["vector_search"]["chunk_overlap"] == ""
            assert state.client_settings["vector_search"]["distance_metric"] == ""
            assert state.client_settings["vector_search"]["vector_store"] == ""
            assert state.client_settings["vector_search"]["alias"] == ""
            assert state.client_settings["vector_search"]["index_type"] == ""

    def test_reset_preserves_non_vector_store_settings(self, app_server, vector_store_state, sample_vector_store_data):
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
            patch.object(st.sidebar, "selectbox"),
            patch.object(st, "info"),
        ):
            vs_df = pd.DataFrame([sample_vector_store_data])

            with patch.object(st_common, "enabled_models_lookup") as mock_models:
                mock_models.return_value = {"openai/text-embed-3": {"id": "text-embed-3"}}
                st_common.render_vector_store_selection(vs_df)

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

        # Setup clean state
        state.client_settings = {
            "vector_search": {
                "enabled": True,
                "model": "",  # Empty after reset
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

        # Clear widget states (simulating post-reset state)
        state.selected_vector_search_model = ""
        state.selected_vector_search_chunk_size = ""
        state.selected_vector_search_chunk_overlap = ""
        state.selected_vector_search_distance_metric = ""
        state.selected_vector_search_alias = ""
        state.selected_vector_search_index_type = ""

        selectbox_calls = []

        def mock_selectbox(label, options, key, index, disabled=False):
            selectbox_calls.append(
                {"label": label, "options": options, "key": key, "index": index, "disabled": disabled}
            )
            # Return the value at index
            return options[index] if 0 <= index < len(options) else ""

        with (
            patch.object(st.sidebar, "subheader"),
            patch.object(st.sidebar, "button"),
            patch.object(st.sidebar, "selectbox", side_effect=mock_selectbox),
            patch.object(st, "info"),
        ):
            # Create dataframe with single option per field using shared fixture
            single_vs = sample_vector_store_data.copy()
            single_vs["alias"] = "single_alias"
            single_vs["vector_store"] = "single_vs"
            vs_df = pd.DataFrame([single_vs])

            with patch.object(st_common, "enabled_models_lookup") as mock_models:
                mock_models.return_value = {"openai/text-embed-3": {"id": "text-embed-3"}}
                st_common.render_vector_store_selection(vs_df)

            # Verify auto-population happened for single options
            assert state.client_settings["vector_search"]["alias"] == "single_alias"
            assert state.client_settings["vector_search"]["model"] == sample_vector_store_data["model"]
            assert state.client_settings["vector_search"]["chunk_size"] == sample_vector_store_data["chunk_size"]
            assert state.client_settings["vector_search"]["chunk_overlap"] == sample_vector_store_data["chunk_overlap"]
            assert (
                state.client_settings["vector_search"]["distance_metric"]
                == sample_vector_store_data["distance_metric"]
            )
            assert state.client_settings["vector_search"]["index_type"] == sample_vector_store_data["index_type"]

            # Verify widget states were also set
            assert state.selected_vector_search_alias == "single_alias"
            assert state.selected_vector_search_model == sample_vector_store_data["model"]

    def test_no_auto_population_with_multiple_options(
        self, app_server, sample_vector_store_data, sample_vector_store_data_alt
    ):
        """Test that fields with multiple options are NOT auto-populated after reset"""
        assert app_server is not None

        # Setup clean state after reset
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

        # Clear widget states
        for key in ["model", "chunk_size", "chunk_overlap", "distance_metric", "alias", "index_type"]:
            state[f"selected_vector_search_{key}"] = ""

        with (
            patch.object(st.sidebar, "subheader"),
            patch.object(st.sidebar, "button"),
            patch.object(st.sidebar, "selectbox", return_value=""),
            patch.object(st, "info"),
        ):
            # Create dataframe with multiple options using shared fixtures
            vs1 = sample_vector_store_data.copy()
            vs1["alias"] = "alias1"
            vs2 = sample_vector_store_data_alt.copy()
            vs2["alias"] = "alias2"
            vs_df = pd.DataFrame([vs1, vs2])

            with patch.object(st_common, "enabled_models_lookup") as mock_models:
                mock_models.return_value = {"openai/text-embed-3": {"id": "text-embed-3"}}
                st_common.render_vector_store_selection(vs_df)

            # With multiple options, fields should remain empty (no auto-population)
            assert state.client_settings["vector_search"]["alias"] == ""
            assert state.client_settings["vector_search"]["chunk_size"] == ""
            assert state.client_settings["vector_search"]["chunk_overlap"] == ""
            assert state.client_settings["vector_search"]["distance_metric"] == ""
            assert state.client_settings["vector_search"]["index_type"] == ""

    def test_reset_button_with_filtered_dataframe(
        self, app_server, sample_vector_store_data, sample_vector_store_data_alt
    ):
        """Test reset button behavior with dynamically filtered dataframes"""
        assert app_server is not None

        # Setup state with a filter already applied
        state.client_settings = {
            "vector_search": {
                "enabled": True,
                "model": sample_vector_store_data["model"],
                "chunk_size": sample_vector_store_data["chunk_size"],
                "chunk_overlap": "",
                "distance_metric": "",
                "vector_store": "",
                "alias": "alias1",  # Filter applied
                "index_type": "",
                "top_k": 10,
                "search_type": "Similarity",
                "score_threshold": 0.5,
                "fetch_k": 20,
                "lambda_mult": 0.5,
            },
            "database": {"alias": "DEFAULT"},
        }

        state.selected_vector_search_alias = "alias1"
        state.selected_vector_search_model = sample_vector_store_data["model"]
        state.selected_vector_search_chunk_size = sample_vector_store_data["chunk_size"]

        def mock_button(label, **kwargs):
            if "Reset" in label and "on_click" in kwargs:
                kwargs["on_click"]()
            return True

        with (
            patch.object(st.sidebar, "subheader"),
            patch.object(st.sidebar, "button", side_effect=mock_button),
            patch.object(st.sidebar, "selectbox", return_value=""),
            patch.object(st, "info"),
        ):
            # Create dataframe with same alias using shared fixtures
            vs1 = sample_vector_store_data.copy()
            vs1["alias"] = "alias1"
            vs2 = sample_vector_store_data_alt.copy()
            vs2["alias"] = "alias1"
            vs_df = pd.DataFrame([vs1, vs2])

            with patch.object(st_common, "enabled_models_lookup") as mock_models:
                mock_models.return_value = {"openai/text-embed-3": {"id": "text-embed-3"}}
                st_common.render_vector_store_selection(vs_df)

            # After reset, all filters should be cleared
            assert state.selected_vector_search_alias == ""
            assert state.selected_vector_search_model == ""
            assert state.selected_vector_search_chunk_size == ""
            assert state.client_settings["vector_search"]["alias"] == ""
            assert state.client_settings["vector_search"]["model"] == ""
            assert state.client_settings["vector_search"]["chunk_size"] == ""
