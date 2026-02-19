"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/mcp/tools/vs_retriever.py

Tests distance-to-similarity conversion and score threshold filtering.
"""
# pylint: disable=import-outside-toplevel

from unittest.mock import MagicMock, patch
from langchain_core.documents import Document

from common.schema import VectorSearchSettings


class TestDistanceToSimilarityConversion:
    """Tests for distance-to-similarity score conversion logic."""

    def test_cosine_distance_to_similarity(self):
        """Test COSINE distance conversion: similarity = 1 - (distance / 2).

        COSINE distance range: [0, 2]
        - 0.0 distance = 1.0 similarity (perfect match)
        - 1.0 distance = 0.5 similarity (orthogonal)
        - 2.0 distance = 0.0 similarity (opposite)
        """
        # Mock the vectorstores.similarity_search_with_score to return distances
        mock_vectorstore = MagicMock()
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content="Perfect match", metadata={}), 0.0),
            (Document(page_content="Good match", metadata={}), 0.4),
            (Document(page_content="Medium match", metadata={}), 1.0),
            (Document(page_content="Poor match", metadata={}), 1.6),
            (Document(page_content="Very poor match", metadata={}), 2.0),
        ]

        # Import the function we're testing
        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=5,
            score_threshold=0.0,  # No filtering for this test
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="TEST_TABLE",
                question="test query",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="COSINE",
            )

        # Verify similarity scores
        assert len(documents) == 5
        assert documents[0].metadata["similarity_score"] == 1.0  # 1 - (0.0 / 2)
        assert documents[1].metadata["similarity_score"] == 0.8  # 1 - (0.4 / 2)
        assert documents[2].metadata["similarity_score"] == 0.5  # 1 - (1.0 / 2)
        assert documents[3].metadata["similarity_score"] == 0.2  # 1 - (1.6 / 2)
        assert documents[4].metadata["similarity_score"] == 0.0  # 1 - (2.0 / 2)

    def test_dot_product_similarity(self):
        """Test DOT product: already a similarity metric, higher is better."""
        mock_vectorstore = MagicMock()
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content="High similarity", metadata={}), 0.95),
            (Document(page_content="Medium similarity", metadata={}), 0.6),
            (Document(page_content="Low similarity", metadata={}), 0.3),
        ]

        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=3,
            score_threshold=0.0,
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="TEST_TABLE",
                question="test query",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="DOT",
            )

        # DOT scores should pass through unchanged
        assert len(documents) == 3
        assert documents[0].metadata["similarity_score"] == 0.95
        assert documents[1].metadata["similarity_score"] == 0.6
        assert documents[2].metadata["similarity_score"] == 0.3

    def test_euclidean_distance_to_similarity(self):
        """Test EUCLIDEAN distance conversion: similarity = 1 / (1 + distance).

        EUCLIDEAN distance range: [0, ∞)
        - 0.0 distance = 1.0 similarity
        - 1.0 distance = 0.5 similarity
        - 9.0 distance = 0.1 similarity
        """
        mock_vectorstore = MagicMock()
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content="Perfect match", metadata={}), 0.0),
            (Document(page_content="Close match", metadata={}), 1.0),
            (Document(page_content="Distant match", metadata={}), 9.0),
        ]

        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=3,
            score_threshold=0.0,
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="TEST_TABLE",
                question="test query",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="EUCLIDEAN",
            )

        # Verify similarity scores
        assert len(documents) == 3
        assert documents[0].metadata["similarity_score"] == 1.0  # 1 / (1 + 0)
        assert documents[1].metadata["similarity_score"] == 0.5  # 1 / (1 + 1)
        assert documents[2].metadata["similarity_score"] == 0.1  # 1 / (1 + 9)


class TestScoreThresholdFiltering:
    """Tests for score threshold filtering logic."""

    def test_threshold_disabled_when_zero(self):
        """Test that score_threshold=0.0 disables filtering (returns all documents)."""
        mock_vectorstore = MagicMock()
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content="Doc 1", metadata={}), 0.0),   # similarity = 1.0
            (Document(page_content="Doc 2", metadata={}), 0.4),   # similarity = 0.8
            (Document(page_content="Doc 3", metadata={}), 1.0),   # similarity = 0.5
            (Document(page_content="Doc 4", metadata={}), 1.6),   # similarity = 0.2
        ]

        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=4,
            score_threshold=0.0,  # Disabled
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="TEST_TABLE",
                question="test query",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="COSINE",
            )

        # All 4 documents should be returned
        assert len(documents) == 4

    def test_threshold_filters_low_scores(self):
        """Test that score_threshold filters out documents below threshold."""
        mock_vectorstore = MagicMock()
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content="Doc 1", metadata={}), 0.0),   # similarity = 1.0 ✓
            (Document(page_content="Doc 2", metadata={}), 0.4),   # similarity = 0.8 ✓
            (Document(page_content="Doc 3", metadata={}), 1.0),   # similarity = 0.5 ✗
            (Document(page_content="Doc 4", metadata={}), 1.6),   # similarity = 0.2 ✗
        ]

        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=4,
            score_threshold=0.65,  # Filter out < 0.65
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="TEST_TABLE",
                question="test query",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="COSINE",
            )

        # Only 2 documents with similarity >= 0.65 should be returned
        assert len(documents) == 2
        assert documents[0].page_content == "Doc 1"
        assert documents[0].metadata["similarity_score"] == 1.0
        assert documents[1].page_content == "Doc 2"
        assert documents[1].metadata["similarity_score"] == 0.8

    def test_threshold_at_boundary(self):
        """Test that score_threshold includes documents at exact threshold value."""
        mock_vectorstore = MagicMock()
        # Create doc with distance that converts to exactly 0.65 similarity
        # For COSINE: similarity = 1 - (distance / 2)
        # 0.65 = 1 - (distance / 2) => distance = 0.7
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content="Above threshold", metadata={}), 0.6),   # similarity = 0.7
            (Document(page_content="At threshold", metadata={}), 0.7),      # similarity = 0.65
            (Document(page_content="Below threshold", metadata={}), 0.8),   # similarity = 0.6
        ]

        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=3,
            score_threshold=0.65,
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="TEST_TABLE",
                question="test query",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="COSINE",
            )

        # Should include documents >= 0.65 (first two)
        assert len(documents) == 2
        assert documents[0].page_content == "Above threshold"
        assert documents[1].page_content == "At threshold"

    def test_threshold_returns_empty_when_no_matches(self):
        """Test that high threshold can result in empty results."""
        mock_vectorstore = MagicMock()
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content="Low score 1", metadata={}), 1.4),  # similarity = 0.3
            (Document(page_content="Low score 2", metadata={}), 1.6),  # similarity = 0.2
        ]

        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=2,
            score_threshold=0.9,  # Very high threshold
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="TEST_TABLE",
                question="test query",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="COSINE",
            )

        # No documents meet threshold
        assert len(documents) == 0


class TestTopKAndThresholdInteraction:
    """Tests for interaction between top_k and score_threshold."""

    def test_top_k_retrieved_then_threshold_filters(self):
        """Test that database retrieves top_k, then threshold filters the results.

        This is the key behavior:
        1. Database retrieves top_k=8 documents (best matches)
        2. Application filters by score_threshold (e.g., 0.6)
        3. Result may be fewer than top_k documents
        """
        mock_vectorstore = MagicMock()
        # Simulate database returning top_k=8 documents
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content=f"Doc {i}", metadata={}), 0.1 * i)
            for i in range(8)
        ]
        # Distances: 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7
        # Similarities (COSINE): 1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65

        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=8,
            score_threshold=0.6,  # Set below the edge case to avoid floating point issues
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="TEST_TABLE",
                question="test query",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="COSINE",
            )

        # All 8 documents have similarity >= 0.6, so all should pass
        assert len(documents) == 8
        assert mock_vectorstore.similarity_search_with_score.call_args[1]["k"] == 8

    def test_optimal_defaults_target_three_docs(self):
        """Test that defaults (top_k=8, threshold=0.65) target ~3 relevant documents.

        Based on empirical testing:
        - top_k=8 retrieves 8 candidates
        - threshold=0.65 has ~40-50% pass-through rate
        - Result: ~3-4 documents (sweet spot for RAG)
        """
        mock_vectorstore = MagicMock()
        # Simulate realistic score distribution
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content="Excellent match", metadata={}), 0.0),   # 1.0
            (Document(page_content="Very good match", metadata={}), 0.2),   # 0.9
            (Document(page_content="Good match", metadata={}), 0.4),        # 0.8
            (Document(page_content="Decent match", metadata={}), 0.7),      # 0.65
            (Document(page_content="Marginal match", metadata={}), 0.9),    # 0.55
            (Document(page_content="Weak match", metadata={}), 1.1),        # 0.45
            (Document(page_content="Poor match", metadata={}), 1.3),        # 0.35
            (Document(page_content="Very poor match", metadata={}), 1.5),   # 0.25
        ]

        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=8,
            score_threshold=0.65,
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="TEST_TABLE",
                question="test query",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="COSINE",
            )

        # Should get 4 documents >= 0.65 threshold (target ~3)
        assert len(documents) == 4
        assert all(doc.metadata["similarity_score"] >= 0.65 for doc in documents)


class TestMetadataEnrichment:
    """Tests for metadata enrichment with similarity scores and table names."""

    def test_similarity_score_added_to_metadata(self):
        """Test that similarity_score is added to document metadata."""
        mock_vectorstore = MagicMock()
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content="Test doc", metadata={"existing": "value"}), 0.4),
        ]

        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=1,
            score_threshold=0.0,
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="MY_TABLE",
                question="test",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="COSINE",
            )

        # Verify metadata enrichment
        assert len(documents) == 1
        assert "similarity_score" in documents[0].metadata
        assert documents[0].metadata["similarity_score"] == 0.8  # 1 - (0.4/2)
        assert "searched_table" in documents[0].metadata
        assert documents[0].metadata["searched_table"] == "MY_TABLE"
        # Existing metadata should be preserved
        assert documents[0].metadata["existing"] == "value"

    def test_similarity_score_rounded_to_three_decimals(self):
        """Test that similarity scores are rounded to 3 decimal places."""
        mock_vectorstore = MagicMock()
        # Create a distance that results in non-round similarity
        # distance = 0.3333 => similarity = 1 - (0.3333/2) = 0.83335
        mock_vectorstore.similarity_search_with_score.return_value = [
            (Document(page_content="Test", metadata={}), 0.3333),
        ]

        from server.mcp.tools.vs_retriever import _search_table

        vector_search = VectorSearchSettings(
            search_type="Similarity",
            top_k=1,
            score_threshold=0.0,
        )

        with patch("server.mcp.tools.vs_retriever.OracleVS", return_value=mock_vectorstore):
            documents = _search_table(
                table_name="TEST",
                question="test",
                db_conn=MagicMock(),
                embed_client=MagicMock(),
                vector_search=vector_search,
                table_distance_metric="COSINE",
            )

        # Should be rounded to 3 decimals
        assert documents[0].metadata["similarity_score"] == 0.833
