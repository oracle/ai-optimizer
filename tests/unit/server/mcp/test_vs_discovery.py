"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for vs_discovery.py - vector store discovery behavior.

Tests that discovery setting properly controls whether database is queried
or configured table is returned.
"""

from unittest.mock import MagicMock, patch

import pytest

from server.mcp.tools.vs_discovery import _vs_discovery_impl


class TestVsDiscoveryImpl:
    """Tests for _vs_discovery_impl function."""

    @pytest.fixture
    def mock_vector_search_discovery_enabled(self):
        """Create mock vector search settings with discovery enabled."""
        mock = MagicMock()
        mock.discovery = True
        mock.model = "openai/text-embedding-3-small"
        mock.chunk_size = 1000
        mock.chunk_overlap = 200
        mock.distance_metric = "COSINE"
        mock.index_type = "HNSW"
        mock.alias = "TEST_ALIAS"
        mock.description = "Test description"
        return mock

    @pytest.fixture
    def mock_vector_search_discovery_disabled(self):
        """Create mock vector search settings with discovery disabled."""
        mock = MagicMock()
        mock.discovery = False
        mock.model = "openai/text-embedding-3-small"
        mock.chunk_size = 1000
        mock.chunk_overlap = 200
        mock.distance_metric = "COSINE"
        mock.index_type = "HNSW"
        mock.alias = "MY_DOCS"
        mock.description = "My configured vector store"
        return mock

    @pytest.fixture
    def mock_client_settings_discovery_disabled(self, mock_vector_search_discovery_disabled):
        """Create mock client settings with discovery disabled."""
        mock = MagicMock()
        mock.vector_search = mock_vector_search_discovery_disabled
        return mock

    @pytest.fixture
    def mock_client_settings_discovery_enabled(self, mock_vector_search_discovery_enabled):
        """Create mock client settings with discovery enabled."""
        mock = MagicMock()
        mock.vector_search = mock_vector_search_discovery_enabled
        return mock

    def test_discovery_disabled_returns_configured_table(
        self, mock_client_settings_discovery_disabled
    ):
        """Test that when discovery is disabled, configured table is returned without DB query."""
        with patch(
            "server.mcp.tools.vs_discovery.utils_settings.get_client",
            return_value=mock_client_settings_discovery_disabled,
        ), patch(
            "server.mcp.tools.vs_discovery.execute_vector_table_query"
        ) as mock_query:
            result = _vs_discovery_impl(thread_id="test-thread")

            # Should NOT query database
            mock_query.assert_not_called()

            # Should return success with configured table
            assert result.status == "success"
            assert len(result.parsed_tables) == 1

            # Table should match configured settings
            table = result.parsed_tables[0]
            assert table.parsed.model == "openai/text-embedding-3-small"
            assert table.parsed.alias == "MY_DOCS"
            assert table.parsed.description == "My configured vector store"
            assert table.parsed.chunk_size == 1000
            assert table.parsed.distance_metric == "COSINE"

    def test_discovery_enabled_queries_database(
        self, mock_client_settings_discovery_enabled
    ):
        """Test that when discovery is enabled, database is queried for tables."""
        mock_db_results = [
            ("SCHEMA1", "TABLE1", '{"model": "openai/text-embedding-3-small"}'),
            ("SCHEMA2", "TABLE2", '{"model": "openai/text-embedding-3-small"}'),
        ]

        with patch(
            "server.mcp.tools.vs_discovery.utils_settings.get_client",
            return_value=mock_client_settings_discovery_enabled,
        ), patch(
            "server.mcp.tools.vs_discovery.execute_vector_table_query",
            return_value=mock_db_results,
        ) as mock_query, patch(
            "server.mcp.tools.vs_discovery.is_model_enabled",
            return_value=True,
        ):
            result = _vs_discovery_impl(thread_id="test-thread", filter_enabled_models=True)

            # Should query database
            mock_query.assert_called_once_with("test-thread")

            # Should return tables from database
            assert result.status == "success"
            assert len(result.parsed_tables) == 2

    def test_discovery_disabled_skips_llm_table_selection(
        self, mock_client_settings_discovery_disabled
    ):
        """Test that discovery disabled results in single table, skipping LLM selection.

        This tests the integration between vs_discovery and vs_retriever:
        When discovery is disabled, only one table is returned, which causes
        the retriever's _select_tables_with_llm to skip the LLM call.
        """
        with patch(
            "server.mcp.tools.vs_discovery.utils_settings.get_client",
            return_value=mock_client_settings_discovery_disabled,
        ):
            result = _vs_discovery_impl(thread_id="test-thread")

            # Should return exactly 1 table (the configured one)
            assert result.status == "success"
            assert len(result.parsed_tables) == 1

            # This single table will cause _select_tables_with_llm to skip LLM
            # (tested separately in retriever tests)

    def test_discovery_disabled_with_minimal_settings(self):
        """Test that discovery disabled works even with minimal settings.

        Note: get_vs_table generates a table name even with None values,
        so this scenario doesn't return an error - it generates a fallback name.
        """
        mock_vector_search = MagicMock()
        mock_vector_search.discovery = False
        mock_vector_search.model = None
        mock_vector_search.chunk_size = 0
        mock_vector_search.chunk_overlap = 0
        mock_vector_search.distance_metric = None
        mock_vector_search.index_type = None
        mock_vector_search.alias = None
        mock_vector_search.description = None

        mock_client_settings = MagicMock()
        mock_client_settings.vector_search = mock_vector_search

        with patch(
            "server.mcp.tools.vs_discovery.utils_settings.get_client",
            return_value=mock_client_settings,
        ):
            result = _vs_discovery_impl(thread_id="test-thread")

            # get_vs_table generates a fallback table name even with None values
            assert result.status == "success"
            assert len(result.parsed_tables) == 1
