"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for CPU optimization utilities in common/functions.py

Tests extract_parameter_count() and is_small_model() functions.
"""

import pytest

from common import functions


class TestExtractParameterCount:
    """Tests for extract_parameter_count function."""

    def test_simple_1b_model(self):
        """extract_parameter_count should extract 1B from simple model name."""
        result = functions.extract_parameter_count("llama3.2:1b")
        assert result == 1.0

    def test_simple_3b_model(self):
        """extract_parameter_count should extract 3B from model name."""
        result = functions.extract_parameter_count("llama3.2:3b")
        assert result == 3.0

    def test_uppercase_b(self):
        """extract_parameter_count should handle uppercase B."""
        result = functions.extract_parameter_count("gemma3:1B")
        assert result == 1.0

    def test_decimal_parameter_count(self):
        """extract_parameter_count should handle decimal parameter counts."""
        result = functions.extract_parameter_count("phi4-mini:3.8b")
        assert result == 3.8

    def test_8b_model(self):
        """extract_parameter_count should extract 8B from model name."""
        result = functions.extract_parameter_count("llama3.1:8b")
        assert result == 8.0

    def test_70b_model(self):
        """extract_parameter_count should extract 70B from model name."""
        result = functions.extract_parameter_count("llama3:70b")
        assert result == 70.0

    def test_no_parameter_count(self):
        """extract_parameter_count should return None for models without parameter count."""
        result = functions.extract_parameter_count("gpt-4o")
        assert result is None

    def test_empty_string(self):
        """extract_parameter_count should return None for empty string."""
        result = functions.extract_parameter_count("")
        assert result is None

    def test_none_input(self):
        """extract_parameter_count should return None for None input."""
        result = functions.extract_parameter_count(None)
        assert result is None

    def test_provider_prefix(self):
        """extract_parameter_count should extract from provider/model format."""
        result = functions.extract_parameter_count("ollama/llama3.2:1b")
        assert result == 1.0

    def test_model_without_colon(self):
        """extract_parameter_count should extract from models without colon."""
        result = functions.extract_parameter_count("gemma-7b")
        assert result == 7.0

    def test_does_not_match_base_in_model_name(self):
        """extract_parameter_count should not match 'base' in model names."""
        result = functions.extract_parameter_count("mxbai-embed-large")
        assert result is None

    def test_does_not_match_bytes_notation(self):
        """extract_parameter_count should not match byte notations like '512b'."""
        # Models don't typically have 512B parameters, but we want to ensure
        # the pattern doesn't incorrectly match things that aren't param counts
        result = functions.extract_parameter_count("model-512bytes")
        assert result is None  # 'bytes' has letters after b


class TestIsSmallModel:
    """Tests for is_small_model function."""

    def test_1b_is_small(self):
        """is_small_model should return True for 1B models."""
        assert functions.is_small_model("llama3.2:1b") is True

    def test_3b_is_small(self):
        """is_small_model should return True for 3B models."""
        assert functions.is_small_model("llama3.2:3b") is True

    def test_3_8b_is_small(self):
        """is_small_model should return True for 3.8B models."""
        assert functions.is_small_model("phi4-mini:3.8b") is True

    def test_7b_is_not_small(self):
        """is_small_model should return False for exactly 7B models (threshold)."""
        assert functions.is_small_model("gemma-7b") is False

    def test_8b_is_not_small(self):
        """is_small_model should return False for 8B models."""
        assert functions.is_small_model("llama3.1:8b") is False

    def test_70b_is_not_small(self):
        """is_small_model should return False for 70B models."""
        assert functions.is_small_model("llama3:70b") is False

    def test_unknown_model_is_not_small(self):
        """is_small_model should return False for models without detectable param count."""
        assert functions.is_small_model("gpt-4o") is False

    def test_empty_string_is_not_small(self):
        """is_small_model should return False for empty string."""
        assert functions.is_small_model("") is False

    def test_none_is_not_small(self):
        """is_small_model should return False for None input."""
        assert functions.is_small_model(None) is False

    def test_with_provider_prefix(self):
        """is_small_model should work with provider/model format."""
        assert functions.is_small_model("ollama/llama3.2:1b") is True
        assert functions.is_small_model("ollama/llama3.1:8b") is False

    def test_gemma_1b(self):
        """is_small_model should detect gemma 1b as small."""
        assert functions.is_small_model("gemma3:1b") is True

    def test_threshold_boundary(self):
        """is_small_model should correctly handle values near threshold."""
        assert functions.is_small_model("model:6.9b") is True
        assert functions.is_small_model("model:7b") is False
        assert functions.is_small_model("model:7.1b") is False


class TestSmallModelThreshold:
    """Tests for SMALL_MODEL_THRESHOLD_B constant."""

    def test_threshold_is_7(self):
        """SMALL_MODEL_THRESHOLD_B should be 7."""
        assert functions.SMALL_MODEL_THRESHOLD_B == 7
