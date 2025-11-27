"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# pylint: disable=protected-access

import pytest
from server.api.v1.embed import _extract_provider_error_message


class TestExtractProviderErrorMessage:
    """Test _extract_provider_error_message function"""

    def test_exception_with_message(self):
        """Test extraction of exception with message"""
        error = Exception("Something went wrong")
        result = _extract_provider_error_message(error)
        assert result == "Something went wrong"

    def test_exception_without_message(self):
        """Test extraction of exception without message"""
        error = ValueError()
        result = _extract_provider_error_message(error)
        assert result == "Error: ValueError"

    def test_openai_quota_exceeded(self):
        """Test extraction of OpenAI quota exceeded error message"""
        error_msg = (
            "Error code: 429 - {'error': {'message': 'You exceeded your current quota, "
            "please check your plan and billing details.', 'type': 'insufficient_quota'}}"
        )
        error = Exception(error_msg)
        result = _extract_provider_error_message(error)
        assert result == error_msg

    def test_openai_rate_limit(self):
        """Test extraction of OpenAI rate limit error message"""
        error_msg = "Rate limit exceeded. Please try again later."
        error = Exception(error_msg)
        result = _extract_provider_error_message(error)
        assert result == error_msg

    def test_complex_error_message(self):
        """Test extraction of complex multi-line error message"""
        error_msg = "Connection failed\nTimeout: 30s\nHost: api.example.com"
        error = Exception(error_msg)
        result = _extract_provider_error_message(error)
        assert result == error_msg

    @pytest.mark.parametrize(
        "error_message",
        [
            "OpenAI API key is invalid",
            "Cohere API error occurred",
            "OCI service error",
            "Database connection failed",
            "Rate limit exceeded for model xyz",
        ],
    )
    def test_various_error_messages(self, error_message):
        """Test that various error messages are passed through correctly"""
        error = Exception(error_message)
        result = _extract_provider_error_message(error)
        assert result == error_message
