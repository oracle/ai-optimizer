# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import MagicMock

import pandas as pd
from streamlit import session_state as state

from client.utils import vs_options


#############################################################################
# Test _get_vs_fields
#############################################################################
class TestGetVsFields:
    """Test _get_vs_fields function"""

    def test_returns_correct_fields(self, app_server):
        """Test that _get_vs_fields returns expected field tuples"""
        assert app_server is not None

        fields = vs_options._get_vs_fields()

        assert len(fields) == 6
        assert ("Select Alias:", "alias") in fields
        assert ("Select Model:", "model") in fields
        assert ("Select Chunk Size:", "chunk_size") in fields
        assert ("Select Chunk Overlap:", "chunk_overlap") in fields
        assert ("Select Distance Metric:", "distance_metric") in fields
        assert ("Select Index Type:", "index_type") in fields

    def test_fields_order_is_consistent(self, app_server):
        """Test that _get_vs_fields returns fields in consistent order"""
        assert app_server is not None

        fields = vs_options._get_vs_fields()

        # Verify order: alias, model, chunk_size, chunk_overlap, distance_metric, index_type
        assert fields[0][1] == "alias"
        assert fields[1][1] == "model"
        assert fields[2][1] == "chunk_size"
        assert fields[3][1] == "chunk_overlap"
        assert fields[4][1] == "distance_metric"
        assert fields[5][1] == "index_type"


#############################################################################
# Test _get_valid_options
#############################################################################
class TestGetValidOptions:
    """Test _get_valid_options function"""

    def test_no_filters_returns_all(self, app_server, sample_vector_stores_list):
        """Test _get_valid_options with no filters returns all unique values"""
        assert app_server is not None

        vs_df = pd.DataFrame(sample_vector_stores_list)
        selections = {}

        result = vs_options._get_valid_options(vs_df, "alias", selections)

        assert len(result) == 2
        assert "vs1" in result
        assert "vs2" in result

    def test_with_filter_returns_filtered(self, app_server, sample_vector_stores_list):
        """Test _get_valid_options filters by other selections"""
        assert app_server is not None

        vs_df = pd.DataFrame(sample_vector_stores_list)
        # Filter by chunk_size=1000 which should only match vs1
        selections = {"chunk_size": 1000}

        result = vs_options._get_valid_options(vs_df, "alias", selections)

        assert len(result) == 1
        assert "vs1" in result

    def test_excludes_empty_strings(self, app_server):
        """Test _get_valid_options excludes empty strings from results"""
        assert app_server is not None

        vs_df = pd.DataFrame([
            {"alias": "vs1", "model": "openai/text-embed-3"},
            {"alias": "", "model": "openai/text-embed-3"},
        ])
        selections = {}

        result = vs_options._get_valid_options(vs_df, "alias", selections)

        assert "" not in result
        assert "vs1" in result


#############################################################################
# Test _auto_select
#############################################################################
class TestAutoSelect:
    """Test _auto_select function"""

    def test_single_option_auto_selects(self, app_server):
        """Test auto-selection when there's only one valid option"""
        assert app_server is not None

        vs_df = pd.DataFrame([
            {"alias": "only_one", "model": "openai/text-embed-3", "chunk_size": 1000,
             "chunk_overlap": 200, "distance_metric": "cosine", "index_type": "IVF"},
        ])
        selections = {"alias": "", "model": "", "chunk_size": "", "chunk_overlap": "",
                      "distance_metric": "", "index_type": ""}

        result = vs_options._auto_select(vs_df, selections)

        # All fields should be auto-selected since there's only one option
        assert result["alias"] == "only_one"
        assert result["model"] == "openai/text-embed-3"

    def test_multiple_options_no_auto_select(self, app_server, sample_vector_stores_list):
        """Test no auto-selection when multiple options exist"""
        assert app_server is not None

        vs_df = pd.DataFrame(sample_vector_stores_list)
        selections = {"alias": "", "model": "", "chunk_size": "", "chunk_overlap": "",
                      "distance_metric": "", "index_type": ""}

        result = vs_options._auto_select(vs_df, selections)

        # Model should be auto-selected (same for both), but alias should not
        assert result["model"] == "openai/text-embed-3"  # Same for both
        assert result["alias"] == ""  # Multiple options, no auto-select

    def test_invalid_selection_cleared(self, app_server, sample_vector_stores_list):
        """Test that invalid selections are cleared"""
        assert app_server is not None

        vs_df = pd.DataFrame(sample_vector_stores_list)
        # Set an invalid alias that doesn't exist in the dataframe
        selections = {"alias": "invalid_alias", "model": "", "chunk_size": "",
                      "chunk_overlap": "", "distance_metric": "", "index_type": ""}

        result = vs_options._auto_select(vs_df, selections)

        # Invalid alias should be cleared
        assert result["alias"] == ""


#############################################################################
# Test _reset_selections
#############################################################################
class TestResetSelections:
    """Test _reset_selections function"""

    def test_reset_clears_all_vs_fields(self, app_server):
        """Test reset clears all vector store selection fields"""
        assert app_server is not None

        # Setup initial values
        state.client_settings = {
            "vector_search": {
                "model": "openai/text-embed-3",
                "chunk_size": 1000,
                "chunk_overlap": 200,
                "distance_metric": "cosine",
                "vector_store": "vs_test",
                "alias": "test_alias",
                "index_type": "IVF",
                "top_k": 10,
                "search_type": "Similarity",
            }
        }
        state["_vs_key_version"] = 0

        vs_options._reset_selections()

        # Verify VS selection fields were cleared
        assert state.client_settings["vector_search"]["alias"] == ""
        assert state.client_settings["vector_search"]["model"] == ""
        assert state.client_settings["vector_search"]["chunk_size"] == ""
        assert state.client_settings["vector_search"]["chunk_overlap"] == ""
        assert state.client_settings["vector_search"]["distance_metric"] == ""
        assert state.client_settings["vector_search"]["index_type"] == ""
        assert state.client_settings["vector_search"]["vector_store"] == ""

        # Verify other fields were NOT cleared
        assert state.client_settings["vector_search"]["top_k"] == 10
        assert state.client_settings["vector_search"]["search_type"] == "Similarity"

    def test_reset_increments_key_version(self, app_server):
        """Test reset increments the key version for widget reset"""
        assert app_server is not None

        state.client_settings = {"vector_search": {
            "alias": "", "model": "", "chunk_size": "", "chunk_overlap": "",
            "distance_metric": "", "index_type": "", "vector_store": ""
        }}
        state["_vs_key_version"] = 5

        vs_options._reset_selections()

        assert state["_vs_key_version"] == 6


#############################################################################
# Test _get_current_selections
#############################################################################
class TestGetCurrentSelections:
    """Test _get_current_selections function"""

    def test_gets_from_widget_state(self, app_server):
        """Test getting selections from widget state"""
        assert app_server is not None

        state.client_settings = {"vector_search": {"alias": "from_settings"}}
        state["vs_alias_0"] = "from_widget"

        result = vs_options._get_current_selections(key_version=0)

        assert result["alias"] == "from_widget"

    def test_falls_back_to_client_settings(self, app_server):
        """Test fallback to client_settings when widget not in state"""
        assert app_server is not None

        # Use a different key_version to avoid state from previous test
        state.client_settings = {"vector_search": {"alias": "from_settings", "model": "test_model"}}
        # No widget state set for this key_version

        result = vs_options._get_current_selections(key_version=99)

        assert result["alias"] == "from_settings"
        assert result["model"] == "test_model"


#############################################################################
# Test _render_selectbox
#############################################################################
class TestRenderSelectbox:
    """Test _render_selectbox function"""

    def test_selectbox_disabled_when_no_options(self, app_server):
        """Test selectbox is disabled when no valid options"""
        assert app_server is not None

        mock_container = MagicMock()
        mock_container.selectbox = MagicMock(return_value="")
        base_df = pd.DataFrame(columns=["alias", "model"])
        current_selections = {"alias": ""}

        vs_options._render_selectbox(
            mock_container, "Select Alias:", "alias", base_df, current_selections, key_version=0
        )

        # Verify selectbox was called with disabled=True
        mock_container.selectbox.assert_called_once()
        call_kwargs = mock_container.selectbox.call_args[1]
        assert call_kwargs["disabled"] is True

    def test_selectbox_enabled_with_options(self, app_server, sample_vector_stores_list):
        """Test selectbox is enabled when valid options exist"""
        assert app_server is not None

        mock_container = MagicMock()
        mock_container.selectbox = MagicMock(return_value="vs1")
        base_df = pd.DataFrame(sample_vector_stores_list)
        current_selections = {"alias": ""}

        vs_options._render_selectbox(
            mock_container, "Select Alias:", "alias", base_df, current_selections, key_version=0
        )

        # Verify selectbox was called with disabled=False
        mock_container.selectbox.assert_called_once()
        call_kwargs = mock_container.selectbox.call_args[1]
        assert call_kwargs["disabled"] is False

    def test_selectbox_preserves_valid_selection(self, app_server, sample_vector_stores_list):
        """Test selectbox preserves current selection if valid"""
        assert app_server is not None

        mock_container = MagicMock()
        mock_container.selectbox = MagicMock(return_value="vs1")
        base_df = pd.DataFrame(sample_vector_stores_list)
        current_selections = {"alias": "vs1"}

        vs_options._render_selectbox(
            mock_container, "Select Alias:", "alias", base_df, current_selections, key_version=0
        )

        # Verify selectbox was called with correct index for "vs1"
        call_kwargs = mock_container.selectbox.call_args[1]
        options = call_kwargs["options"]
        assert "vs1" in options
        # Index should point to vs1, not empty string
        assert call_kwargs["index"] == options.index("vs1")

    def test_selectbox_resets_invalid_selection(self, app_server, sample_vector_stores_list):
        """Test selectbox resets to empty when current selection is invalid"""
        assert app_server is not None

        mock_container = MagicMock()
        mock_container.selectbox = MagicMock(return_value="")
        base_df = pd.DataFrame(sample_vector_stores_list)
        current_selections = {"alias": "invalid_value"}

        vs_options._render_selectbox(
            mock_container, "Select Alias:", "alias", base_df, current_selections, key_version=0
        )

        # Verify selectbox was called with index 0 (empty option)
        call_kwargs = mock_container.selectbox.call_args[1]
        assert call_kwargs["index"] == 0
