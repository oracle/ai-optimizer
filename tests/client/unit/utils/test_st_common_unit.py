"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

from io import BytesIO
from unittest.mock import MagicMock
import pandas as pd
import pytest
from streamlit import session_state as state
from client.utils import st_common, api_call


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

        def mock_patch(endpoint, payload, params, toast=True):
            nonlocal patch_called
            patch_called = True
            return {}

        monkeypatch.setattr(api_call, "patch", mock_patch)

        st_common.patch_settings()

        assert patch_called

    def test_patch_settings_api_error(self, app_server, monkeypatch):
        """Test patch_settings with API error"""
        assert app_server is not None

        state.client_settings = {"client": "test-client", "ll_model": {}}

        # Mock api_call.patch to raise error
        def mock_patch(endpoint, payload, params, toast=True):
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

    def test_update_filtered_vector_store_no_filters(self, app_server):
        """Test update_filtered_vector_store with no filters"""
        assert app_server is not None

        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True},
        ]

        vs_df = pd.DataFrame([
            {"alias": "vs1", "model": "openai/text-embed-3", "chunk_size": 1000,
             "chunk_overlap": 200, "distance_metric": "cosine", "index_type": "IVF"},
            {"alias": "vs2", "model": "openai/text-embed-3", "chunk_size": 500,
             "chunk_overlap": 100, "distance_metric": "euclidean", "index_type": "HNSW"},
        ])

        result = st_common.update_filtered_vector_store(vs_df)

        # Should return all rows (filtered by enabled models only)
        assert len(result) == 2

    def test_update_filtered_vector_store_with_alias_filter(self, app_server):
        """Test update_filtered_vector_store with alias filter"""
        assert app_server is not None

        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True},
        ]
        state.selected_vector_search_alias = "vs1"

        vs_df = pd.DataFrame([
            {"alias": "vs1", "model": "openai/text-embed-3", "chunk_size": 1000,
             "chunk_overlap": 200, "distance_metric": "cosine", "index_type": "IVF"},
            {"alias": "vs2", "model": "openai/text-embed-3", "chunk_size": 500,
             "chunk_overlap": 100, "distance_metric": "euclidean", "index_type": "HNSW"},
        ])

        result = st_common.update_filtered_vector_store(vs_df)

        # Should only return vs1
        assert len(result) == 1
        assert result.iloc[0]["alias"] == "vs1"

    def test_update_filtered_vector_store_disabled_model(self, app_server):
        """Test that disabled embedding models filter out vector stores"""
        assert app_server is not None

        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": False},
        ]

        vs_df = pd.DataFrame([
            {"alias": "vs1", "model": "openai/text-embed-3", "chunk_size": 1000,
             "chunk_overlap": 200, "distance_metric": "cosine", "index_type": "IVF"},
        ])

        result = st_common.update_filtered_vector_store(vs_df)

        # Should return empty (model not enabled)
        assert len(result) == 0

    def test_update_filtered_vector_store_multiple_filters(self, app_server):
        """Test update_filtered_vector_store with multiple filters"""
        assert app_server is not None

        state.model_configs = [
            {"id": "text-embed-3", "provider": "openai", "type": "embed", "enabled": True},
        ]
        state.selected_vector_search_alias = "vs1"
        state.selected_vector_search_model = "openai/text-embed-3"
        state.selected_vector_search_chunk_size = 1000

        vs_df = pd.DataFrame([
            {"alias": "vs1", "model": "openai/text-embed-3", "chunk_size": 1000,
             "chunk_overlap": 200, "distance_metric": "cosine", "index_type": "IVF"},
            {"alias": "vs1", "model": "openai/text-embed-3", "chunk_size": 500,
             "chunk_overlap": 100, "distance_metric": "euclidean", "index_type": "HNSW"},
        ])

        result = st_common.update_filtered_vector_store(vs_df)

        # Should only return the 1000 chunk_size entry
        assert len(result) == 1
        assert result.iloc[0]["chunk_size"] == 1000


