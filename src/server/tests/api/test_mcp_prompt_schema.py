"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for MCP PromptResponse schema.
"""

import pytest

from server.app.api.mcp.schemas.prompts import PromptResponse

pytestmark = pytest.mark.unit


class TestPromptResponse:
    """Tests for PromptResponse Pydantic model."""

    def test_serialization_round_trip(self):
        """model_dump → model_validate produces an equivalent instance."""
        original = PromptResponse(name="qa", description="Q&A prompt", text="Answer: {q}")
        data = original.model_dump()
        restored = PromptResponse.model_validate(data)
        assert restored == original
