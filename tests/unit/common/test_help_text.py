"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for common/help_text.py

Tests help text dictionary contents and structure.
"""

from common import help_text


class TestHelpDict:
    """Tests for help_dict dictionary."""

    def test_help_dict_is_dictionary(self):
        """help_dict should be a dictionary."""
        assert isinstance(help_text.help_dict, dict)

    def test_help_dict_has_expected_keys(self):
        """help_dict should contain all expected keys."""
        expected_keys = [
            "max_input_tokens",
            "temperature",
            "max_tokens",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "vector_search",
            "rerank",
            "top_k",
            "score_threshold",
            "fetch_k",
            "lambda_mult",
            "embed_alias",
            "chunk_overlap",
            "chunk_size",
            "index_type",
            "distance_metric",
            "model_id",
            "model_provider",
            "model_url",
            "model_api_key",
        ]

        for key in expected_keys:
            assert key in help_text.help_dict, f"Missing expected key: {key}"

    def test_all_values_are_strings(self):
        """All values in help_dict should be strings."""
        for key, value in help_text.help_dict.items():
            assert isinstance(value, str), f"Value for {key} is not a string"

    def test_all_values_are_non_empty(self):
        """All values in help_dict should be non-empty."""
        for key, value in help_text.help_dict.items():
            assert len(value.strip()) > 0, f"Value for {key} is empty"


class TestModelParameters:
    """Tests for model parameter help texts."""

    def test_max_input_tokens_help(self):
        """max_input_tokens help should explain context window."""
        help_text_value = help_text.help_dict["max_input_tokens"]
        assert "token" in help_text_value.lower()
        assert "model" in help_text_value.lower()

    def test_temperature_help(self):
        """temperature help should explain creativity control."""
        help_text_value = help_text.help_dict["temperature"]
        assert "creative" in help_text_value.lower()
        assert "top p" in help_text_value.lower()

    def test_max_tokens_help(self):
        """max_tokens help should explain response length."""
        help_text_value = help_text.help_dict["max_tokens"]
        assert "length" in help_text_value.lower() or "response" in help_text_value.lower()

    def test_top_p_help(self):
        """top_p help should explain probability threshold."""
        help_text_value = help_text.help_dict["top_p"]
        assert "word" in help_text_value.lower()
        assert "temperature" in help_text_value.lower()

    def test_frequency_penalty_help(self):
        """frequency_penalty help should explain repetition control."""
        help_text_value = help_text.help_dict["frequency_penalty"]
        assert "repeat" in help_text_value.lower()

    def test_presence_penalty_help(self):
        """presence_penalty help should explain topic diversity."""
        help_text_value = help_text.help_dict["presence_penalty"]
        assert "topic" in help_text_value.lower() or "new" in help_text_value.lower()


class TestVectorSearchParameters:
    """Tests for vector search parameter help texts."""

    def test_vector_search_help(self):
        """vector_search help should explain the feature."""
        help_text_value = help_text.help_dict["vector_search"]
        assert "vector" in help_text_value.lower()

    def test_rerank_help(self):
        """rerank help should explain document reranking."""
        help_text_value = help_text.help_dict["rerank"]
        assert "document" in help_text_value.lower()
        assert "relevan" in help_text_value.lower()

    def test_top_k_help(self):
        """top_k help should explain document retrieval count."""
        help_text_value = help_text.help_dict["top_k"]
        assert "document" in help_text_value.lower() or "retrieved" in help_text_value.lower()

    def test_score_threshold_help(self):
        """score_threshold help should explain minimum similarity."""
        help_text_value = help_text.help_dict["score_threshold"]
        assert "similarity" in help_text_value.lower() or "threshold" in help_text_value.lower()

    def test_fetch_k_help(self):
        """fetch_k help should explain initial fetch count."""
        help_text_value = help_text.help_dict["fetch_k"]
        assert "document" in help_text_value.lower()
        assert "fetch" in help_text_value.lower()

    def test_lambda_mult_help(self):
        """lambda_mult help should explain diversity."""
        help_text_value = help_text.help_dict["lambda_mult"]
        assert "diversity" in help_text_value.lower()


class TestEmbeddingParameters:
    """Tests for embedding parameter help texts."""

    def test_embed_alias_help(self):
        """embed_alias help should explain aliasing."""
        help_text_value = help_text.help_dict["embed_alias"]
        assert "alias" in help_text_value.lower()
        assert "vector" in help_text_value.lower() or "embed" in help_text_value.lower()

    def test_chunk_overlap_help(self):
        """chunk_overlap help should explain overlap percentage."""
        help_text_value = help_text.help_dict["chunk_overlap"]
        assert "overlap" in help_text_value.lower()
        assert "chunk" in help_text_value.lower()

    def test_chunk_size_help(self):
        """chunk_size help should explain chunk length."""
        help_text_value = help_text.help_dict["chunk_size"]
        assert "chunk" in help_text_value.lower()
        assert "length" in help_text_value.lower()

    def test_index_type_help(self):
        """index_type help should explain HNSW and IVF."""
        help_text_value = help_text.help_dict["index_type"]
        assert "hnsw" in help_text_value.lower()
        assert "ivf" in help_text_value.lower()

    def test_distance_metric_help(self):
        """distance_metric help should explain distance calculation."""
        help_text_value = help_text.help_dict["distance_metric"]
        assert "distance" in help_text_value.lower() or "similar" in help_text_value.lower()


class TestModelConfiguration:
    """Tests for model configuration help texts."""

    def test_model_id_help(self):
        """model_id help should explain model naming."""
        help_text_value = help_text.help_dict["model_id"]
        assert "model" in help_text_value.lower()
        assert "name" in help_text_value.lower()

    def test_model_provider_help(self):
        """model_provider help should explain provider selection."""
        help_text_value = help_text.help_dict["model_provider"]
        assert "provider" in help_text_value.lower()

    def test_model_url_help(self):
        """model_url help should explain API URL."""
        help_text_value = help_text.help_dict["model_url"]
        assert "api" in help_text_value.lower() or "url" in help_text_value.lower()

    def test_model_api_key_help(self):
        """model_api_key help should explain API key."""
        help_text_value = help_text.help_dict["model_api_key"]
        assert "api" in help_text_value.lower()
        assert "key" in help_text_value.lower()
