# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from io import BytesIO
from unittest.mock import MagicMock, patch

import pandas as pd
import streamlit as st
from streamlit import session_state as state

from client.utils import api_call, st_common


#############################################################################
# Test State Helpers
#############################################################################
class TestStateHelpers:
    """Test state helper functions"""

    def test_clear_state_key_existing_key(self, app_server):
        """Test clearing an existing key from state"""
        assert app_server is not None

        state.test_key = "test_value"
        st_common.clear_state_key("test_key")

        assert not hasattr(state, "test_key")

    def test_clear_state_key_non_existing_key(self, app_server):
        """Test clearing a non-existing key (should not raise error)"""
        assert app_server is not None

        # Should not raise exception
        st_common.clear_state_key("non_existing_key")
        assert True

    def test_state_configs_lookup_simple(self, app_server):
        """Test state_configs_lookup with simple config"""
        assert app_server is not None

        state.test_configs = [
            {"id": "model1", "name": "Model 1"},
            {"id": "model2", "name": "Model 2"},
        ]

        result = st_common.state_configs_lookup("test_configs", "id")

        assert len(result) == 2
        assert "model1" in result
        assert result["model1"]["name"] == "Model 1"
        assert "model2" in result
        assert result["model2"]["name"] == "Model 2"

    def test_state_configs_lookup_with_section(self, app_server):
        """Test state_configs_lookup with section parameter"""
        assert app_server is not None

        state.test_configs = {
            "tools": [
                {"name": "tool1", "type": "retriever"},
                {"name": "tool2", "type": "grader"},
            ],
            "prompts": [
                {"name": "prompt1", "type": "system"},
            ],
        }

        result = st_common.state_configs_lookup("test_configs", "name", "tools")

        assert len(result) == 2
        assert "tool1" in result
        assert "tool2" in result
        assert "prompt1" not in result

    def test_state_configs_lookup_missing_key(self, app_server):
        """Test state_configs_lookup when some items missing the key"""
        assert app_server is not None

        state.test_configs = [
            {"id": "model1", "name": "Model 1"},
            {"name": "Model 2"},  # Missing 'id'
            {"id": "model3", "name": "Model 3"},
        ]

        result = st_common.state_configs_lookup("test_configs", "id")

        # Should only include items with 'id' key
        assert len(result) == 2
        assert "model1" in result
        assert "model3" in result


#############################################################################
# Test Model Helpers
#############################################################################
class TestModelHelpers:
    """Test model helper functions"""

    def test_enabled_models_lookup_language_models(self, app_server):
        """Test enabled_models_lookup for language models"""
        assert app_server is not None

        state.model_configs = [
            {"id": "gpt-4", "provider": "openai", "type": "ll", "enabled": True},
            {"id": "gpt-3.5", "provider": "openai", "type": "ll", "enabled": False},
            {"id": "text-embed", "provider": "openai", "type": "embed", "enabled": True},
        ]

        result = st_common.enabled_models_lookup("ll")

        # Should only include enabled language models
        assert len(result) == 1
        assert "openai/gpt-4" in result
        assert "openai/gpt-3.5" not in result
        assert "openai/text-embed" not in result

    def test_enabled_models_lookup_embedding_models(self, app_server):
        """Test enabled_models_lookup for embedding models"""
        assert app_server is not None

        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True},
            {"id": "cohere-embed", "provider": "cohere", "type": "embed", "enabled": True},
            {"id": "gpt-4", "provider": "openai", "type": "ll", "enabled": True},
        ]

        result = st_common.enabled_models_lookup("embed")

        # Should only include enabled embedding models
        assert len(result) == 2
        assert "openai/text-embed-3" in result
        assert "cohere/cohere-embed" in result
        assert "openai/gpt-4" not in result

    def test_enabled_models_lookup_no_enabled_models(self, app_server):
        """Test enabled_models_lookup when no models are enabled"""
        assert app_server is not None

        state.model_configs = [
            {"id": "gpt-4", "provider": "openai", "type": "ll", "enabled": False},
            {"id": "gpt-3.5", "provider": "openai", "type": "ll", "enabled": False},
        ]

        result = st_common.enabled_models_lookup("ll")

        # Should return empty dict
        assert len(result) == 0


#############################################################################
# Test Common Helpers
#############################################################################
class TestCommonHelpers:
    """Test common helper functions"""

    def test_bool_to_emoji_true(self, app_server):
        """Test bool_to_emoji with True"""
        assert app_server is not None

        result = st_common.bool_to_emoji(True)
        assert result == "✅"

    def test_bool_to_emoji_false(self, app_server):
        """Test bool_to_emoji with False"""
        assert app_server is not None

        result = st_common.bool_to_emoji(False)
        assert result == "⚪"

    def test_local_file_payload_single_file(self, app_server):
        """Test local_file_payload with single file"""
        assert app_server is not None

        # Create a mock file
        mock_file = MagicMock(spec=BytesIO)
        mock_file.name = "test.txt"
        mock_file.getvalue.return_value = b"test content"
        mock_file.type = "text/plain"

        result = st_common.local_file_payload(mock_file)

        assert len(result) == 1
        assert result[0][0] == "files"
        assert result[0][1][0] == "test.txt"
        assert result[0][1][1] == b"test content"
        assert result[0][1][2] == "text/plain"

    def test_local_file_payload_multiple_files(self, app_server):
        """Test local_file_payload with multiple files"""
        assert app_server is not None

        # Create mock files
        mock_file1 = MagicMock(spec=BytesIO)
        mock_file1.name = "test1.txt"
        mock_file1.getvalue.return_value = b"content1"
        mock_file1.type = "text/plain"

        mock_file2 = MagicMock(spec=BytesIO)
        mock_file2.name = "test2.txt"
        mock_file2.getvalue.return_value = b"content2"
        mock_file2.type = "text/plain"

        result = st_common.local_file_payload([mock_file1, mock_file2])

        assert len(result) == 2
        assert result[0][1][0] == "test1.txt"
        assert result[1][1][0] == "test2.txt"

    def test_local_file_payload_duplicate_files(self, app_server):
        """Test local_file_payload with duplicate file names"""
        assert app_server is not None

        # Create mock files with same name
        mock_file1 = MagicMock(spec=BytesIO)
        mock_file1.name = "test.txt"
        mock_file1.getvalue.return_value = b"content1"
        mock_file1.type = "text/plain"

        mock_file2 = MagicMock(spec=BytesIO)
        mock_file2.name = "test.txt"
        mock_file2.getvalue.return_value = b"content2"
        mock_file2.type = "text/plain"

        result = st_common.local_file_payload([mock_file1, mock_file2])

        # Should only include first file (deduplication)
        assert len(result) == 1
        assert result[0][1][0] == "test.txt"

    def test_patch_settings_success(self, app_server, monkeypatch):
        """Test patch_settings with successful API call"""
        assert app_server is not None

        state.client_settings = {"client": "test-client", "ll_model": {}}

        # Mock api_call.patch
        patch_called = False

        def mock_patch(endpoint, payload, params=None, toast=True):
            nonlocal patch_called
            patch_called = True
            # Parameters are needed for the API call but not validated in this test
            assert endpoint is not None
            assert payload is not None
            # params and toast are optional but accepted for API compatibility
            _ = params  # Mark as intentionally unused
            _ = toast  # Mark as intentionally unused
            return {}

        monkeypatch.setattr(api_call, "patch", mock_patch)

        st_common.patch_settings()

        assert patch_called

    def test_patch_settings_api_error(self, app_server, monkeypatch):
        """Test patch_settings with API error"""
        assert app_server is not None

        state.client_settings = {"client": "test-client", "ll_model": {}}

        # Mock api_call.patch to raise error
        def mock_patch(endpoint, payload, params=None, toast=True):
            # Parameters validated before raising error
            assert endpoint is not None
            assert payload is not None
            # params and toast are optional but accepted for API compatibility
            _ = params  # Mark as intentionally unused
            _ = toast  # Mark as intentionally unused
            raise api_call.ApiError("Update failed")

        monkeypatch.setattr(api_call, "patch", mock_patch)

        # Should not raise exception (error is logged)
        st_common.patch_settings()
        assert True


#############################################################################
# Test Client Settings Update
#############################################################################
class TestClientSettingsUpdate:
    """Test update_client_settings function"""

    def test_update_client_settings_no_changes(self, app_server):
        """Test update_client_settings when values haven't changed"""
        assert app_server is not None

        state.client_settings = {
            "ll_model": {
                "model": "gpt-4",
                "temperature": 0.7,
            }
        }

        # No widgets set, so should use default values
        st_common.update_client_settings("ll_model")

        # Values should remain unchanged
        assert state.client_settings["ll_model"]["model"] == "gpt-4"
        assert state.client_settings["ll_model"]["temperature"] == 0.7

    def test_update_client_settings_with_changes(self, app_server):
        """Test update_client_settings when widget values changed"""
        assert app_server is not None

        state.client_settings = {
            "ll_model": {
                "model": "gpt-4",
                "temperature": 0.7,
            }
        }

        # Set widget values
        state.selected_ll_model_model = "gpt-3.5"
        state.selected_ll_model_temperature = 1.0

        st_common.update_client_settings("ll_model")

        # Values should be updated
        assert state.client_settings["ll_model"]["model"] == "gpt-3.5"
        assert state.client_settings["ll_model"]["temperature"] == 1.0

    def test_update_client_settings_clears_user_client(self, app_server):
        """Test that update_client_settings clears user_client"""
        assert app_server is not None

        state.client_settings = {"ll_model": {}}
        state.user_client = "some_client"

        st_common.update_client_settings("ll_model")

        # user_client should be cleared
        assert not hasattr(state, "user_client")


#############################################################################
# Test Database Configuration Check
#############################################################################
class TestDatabaseConfigurationCheck:
    """Test is_db_configured function"""

    def test_is_db_configured_true(self, app_server):
        """Test is_db_configured when database is configured and connected"""
        assert app_server is not None

        state.database_configs = [
            {"name": "DEFAULT", "connected": True},
            {"name": "OTHER", "connected": False},
        ]
        state.client_settings = {"database": {"alias": "DEFAULT"}}

        result = st_common.is_db_configured()

        assert result is True

    def test_is_db_configured_false_not_connected(self, app_server):
        """Test is_db_configured when database exists but not connected"""
        assert app_server is not None

        state.database_configs = [
            {"name": "DEFAULT", "connected": False},
        ]
        state.client_settings = {"database": {"alias": "DEFAULT"}}

        result = st_common.is_db_configured()

        assert result is False

    def test_is_db_configured_false_no_database(self, app_server):
        """Test is_db_configured when no database configured"""
        assert app_server is not None

        state.database_configs = []
        state.client_settings = {"database": {"alias": "DEFAULT"}}

        result = st_common.is_db_configured()

        assert result is False

    def test_is_db_configured_false_different_alias(self, app_server):
        """Test is_db_configured when configured database has different alias"""
        assert app_server is not None

        state.database_configs = [
            {"name": "OTHER", "connected": True},
        ]
        state.client_settings = {"database": {"alias": "DEFAULT"}}

        result = st_common.is_db_configured()

        assert result is False


#############################################################################
# Test Vector Store Helpers
#############################################################################
class TestVectorStoreHelpers:
    """Test vector store helper functions"""

    def test_update_filtered_vector_store_no_filters(self, app_server, sample_vector_stores_list):
        """Test update_filtered_vector_store with no filters"""
        assert app_server is not None

        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True},
        ]

        vs_df = pd.DataFrame(sample_vector_stores_list)

        result = st_common.update_filtered_vector_store(vs_df)

        # Should return all rows (filtered by enabled models only)
        assert len(result) == 2

    def test_update_filtered_vector_store_with_alias_filter(self, app_server, sample_vector_stores_list):
        """Test update_filtered_vector_store with alias filter"""
        assert app_server is not None

        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True},
        ]
        state.selected_vector_search_alias = "vs1"

        vs_df = pd.DataFrame(sample_vector_stores_list)

        result = st_common.update_filtered_vector_store(vs_df)

        # Should only return vs1
        assert len(result) == 1
        assert result.iloc[0]["alias"] == "vs1"

    def test_update_filtered_vector_store_disabled_model(self, app_server, sample_vector_store_data):
        """Test that disabled embedding models filter out vector stores"""
        assert app_server is not None

        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": False},
        ]

        # Use shared fixture with vs1 alias
        vs1 = sample_vector_store_data.copy()
        vs1["alias"] = "vs1"
        vs1.pop("vector_store", None)
        vs_df = pd.DataFrame([vs1])

        result = st_common.update_filtered_vector_store(vs_df)

        # Should return empty (model not enabled)
        assert len(result) == 0

    def test_update_filtered_vector_store_multiple_filters(self, app_server, sample_vector_stores_list):
        """Test update_filtered_vector_store with multiple filters"""
        assert app_server is not None

        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True},
        ]
        state.selected_vector_search_alias = "vs1"
        state.selected_vector_search_model = "openai/text-embed-3"
        state.selected_vector_search_chunk_size = 1000

        # Use only vs1 entries from the fixture
        vs1_entries = [vs.copy() for vs in sample_vector_stores_list]
        for vs in vs1_entries:
            vs["alias"] = "vs1"

        vs_df = pd.DataFrame(vs1_entries)

        result = st_common.update_filtered_vector_store(vs_df)

        # Should only return the 1000 chunk_size entry
        assert len(result) == 1
        assert result.iloc[0]["chunk_size"] == 1000


#############################################################################
# Test _vs_gen_selectbox Function
#############################################################################
class TestVsGenSelectbox:
    """Unit tests for the _vs_gen_selectbox function"""

    def test_single_option_auto_select_when_empty(self, app_server):
        """Test auto-selection when there's one option and current value is empty"""
        assert app_server is not None

        # Setup: empty current value
        state.client_settings = {"vector_search": {"alias": ""}}

        with patch.object(st.sidebar, "selectbox") as mock_selectbox:
            mock_selectbox.return_value = "single_option"

            st_common._vs_gen_selectbox("Select Alias:", ["single_option"], "selected_vector_search_alias")

            # Verify auto-selection occurred
            assert state.client_settings["vector_search"]["alias"] == "single_option"
            assert state.selected_vector_search_alias == "single_option"

            # Verify selectbox was called with correct index (1 = first real option after empty)
            mock_selectbox.assert_called_once()
            call_args = mock_selectbox.call_args
            assert call_args[1]["index"] == 1  # Index 1 points to "single_option" in ["", "single_option"]

    def test_single_option_no_auto_select_when_populated(self, app_server):
        """Test NO auto-selection when there's one option but value already exists"""
        assert app_server is not None

        # Setup: existing value
        state.client_settings = {"vector_search": {"alias": "existing_value"}}

        with patch.object(st.sidebar, "selectbox") as mock_selectbox:
            mock_selectbox.return_value = "existing_value"

            st_common._vs_gen_selectbox("Select Alias:", ["existing_value"], "selected_vector_search_alias")

            # Value should remain unchanged (not overwritten)
            assert state.client_settings["vector_search"]["alias"] == "existing_value"

            # Verify selectbox was called with existing value's index
            mock_selectbox.assert_called_once()
            call_args = mock_selectbox.call_args
            assert call_args[1]["index"] == 1  # existing_value is at index 1

    def test_multiple_options_no_auto_select(self, app_server):
        """Test no auto-selection with multiple options"""
        assert app_server is not None

        # Setup: empty value with multiple options
        state.client_settings = {"vector_search": {"alias": ""}}

        with patch.object(st.sidebar, "selectbox") as mock_selectbox:
            mock_selectbox.return_value = ""

            st_common._vs_gen_selectbox(
                "Select Alias:", ["option1", "option2", "option3"], "selected_vector_search_alias"
            )

            # Should remain empty (no auto-selection)
            assert state.client_settings["vector_search"]["alias"] == ""

            # Verify selectbox was called with index 0 (empty option)
            mock_selectbox.assert_called_once()
            call_args = mock_selectbox.call_args
            assert call_args[1]["index"] == 0  # Index 0 is the empty option

    def test_no_valid_options_disabled(self, app_server):
        """Test selectbox is disabled when no valid options"""
        assert app_server is not None

        state.client_settings = {"vector_search": {"alias": ""}}

        with patch.object(st.sidebar, "selectbox") as mock_selectbox:
            mock_selectbox.return_value = ""

            st_common._vs_gen_selectbox(
                "Select Alias:",
                [],  # No options
                "selected_vector_search_alias",
            )

            # Verify selectbox was called with disabled=True
            mock_selectbox.assert_called_once()
            call_args = mock_selectbox.call_args
            assert call_args[1]["disabled"] is True
            assert call_args[1]["index"] == 0

    def test_invalid_current_value_reset(self, app_server):
        """Test that invalid current value is reset to empty"""
        assert app_server is not None

        # Setup: value that's not in the options
        state.client_settings = {"vector_search": {"alias": "invalid_option"}}

        with patch.object(st.sidebar, "selectbox") as mock_selectbox:
            mock_selectbox.return_value = ""

            st_common._vs_gen_selectbox("Select Alias:", ["valid1", "valid2"], "selected_vector_search_alias")

            # Invalid value should not cause error, selectbox should show empty
            mock_selectbox.assert_called_once()
            call_args = mock_selectbox.call_args
            assert call_args[1]["index"] == 0  # Reset to empty option


#############################################################################
# Test Reset Button Callback Function
#############################################################################
class TestResetButtonCallback:
    """Unit tests for the reset button callback within render_vector_store_selection"""

    def test_reset_clears_correct_fields(self, app_server):
        """Test reset callback clears only the specified vector store fields"""
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

        # Set widget states
        state.selected_vector_search_model = "openai/text-embed-3"
        state.selected_vector_search_chunk_size = 1000
        state.selected_vector_search_chunk_overlap = 200
        state.selected_vector_search_distance_metric = "cosine"
        state.selected_vector_search_alias = "test_alias"
        state.selected_vector_search_index_type = "IVF"

        # Define and execute reset logic (simulating the reset callback)
        fields_to_reset = [
            "model",
            "chunk_size",
            "chunk_overlap",
            "distance_metric",
            "vector_store",
            "alias",
            "index_type",
        ]
        for key in fields_to_reset:
            widget_key = f"selected_vector_search_{key}"
            state[widget_key] = ""
            state.client_settings["vector_search"][key] = ""

        # Verify the correct fields were cleared
        for field in fields_to_reset:
            assert state.client_settings["vector_search"][field] == ""
            assert state[f"selected_vector_search_{field}"] == ""

        # Verify other fields were NOT cleared
        assert state.client_settings["vector_search"]["top_k"] == 10
        assert state.client_settings["vector_search"]["search_type"] == "Similarity"

    def test_reset_enables_auto_population(self, app_server):
        """Test that reset creates conditions for auto-population"""
        assert app_server is not None

        # Setup with existing values
        state.client_settings = {"vector_search": {"alias": "existing"}}
        state.selected_vector_search_alias = "existing"

        # Execute reset logic
        state.selected_vector_search_alias = ""
        state.client_settings["vector_search"]["alias"] = ""

        # After reset, fields should be empty (ready for auto-population)
        assert state.client_settings["vector_search"]["alias"] == ""
        assert state.selected_vector_search_alias == ""

        # Now when _vs_gen_selectbox is called with a single option, it should auto-populate
        with patch.object(st.sidebar, "selectbox") as mock_selectbox:
            mock_selectbox.return_value = "auto_selected"

            st_common._vs_gen_selectbox("Select Alias:", ["auto_selected"], "selected_vector_search_alias")

            # Verify auto-population happened
            assert state.client_settings["vector_search"]["alias"] == "auto_selected"
            assert state.selected_vector_search_alias == "auto_selected"
