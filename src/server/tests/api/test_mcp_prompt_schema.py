"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for MCP PromptResponse schema.
"""

import pytest
from pydantic import ValidationError

from server.app.api.mcp.schemas.prompts import PromptResponse

pytestmark = pytest.mark.unit


class TestPromptResponse:
    """Tests for PromptResponse Pydantic model."""

    def test_valid_construction(self):
        """PromptResponse accepts name and text, defaulting description to empty."""
        p = PromptResponse(name="greet", text="Hello, world!")
        assert p.name == "greet"
        assert p.text == "Hello, world!"
        assert p.description == ""

    def test_required_name(self):
        """Omitting name raises ValidationError."""
        with pytest.raises(ValidationError):
            PromptResponse.model_validate({"text": "some text"})

    def test_required_text(self):
        """Omitting text raises ValidationError."""
        with pytest.raises(ValidationError):
            PromptResponse.model_validate({"name": "greet"})

    def test_description_default_empty_string(self):
        """description defaults to an empty string when not provided."""
        p = PromptResponse(name="test", text="body")
        assert p.description == ""

    def test_custom_description(self):
        """All three fields can be set explicitly."""
        p = PromptResponse(name="summarize", description="Summarizes text", text="Please summarize: {input}")
        assert p.name == "summarize"
        assert p.description == "Summarizes text"
        assert p.text == "Please summarize: {input}"

    def test_serialization_round_trip(self):
        """model_dump → model_validate produces an equivalent instance."""
        original = PromptResponse(name="qa", description="Q&A prompt", text="Answer: {q}")
        data = original.model_dump()
        restored = PromptResponse.model_validate(data)
        assert restored == original
