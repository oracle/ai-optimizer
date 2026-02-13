"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/testbed_metrics.py
Tests for custom testbed evaluation metrics.
"""

# pylint: disable=too-few-public-methods,protected-access

from unittest.mock import patch, MagicMock

import pytest

from giskard.llm.errors import LLMGenerationError

from server.api.utils import testbed_metrics


class TestFormatConversation:
    """Tests for the format_conversation function."""

    def test_format_conversation_single_message(self):
        """Should format single message correctly."""
        conversation = [{"role": "user", "content": "Hello"}]

        result = testbed_metrics.format_conversation(conversation)

        assert result == "<user>Hello</user>"

    def test_format_conversation_multiple_messages(self):
        """Should format multiple messages with double newlines."""
        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        result = testbed_metrics.format_conversation(conversation)

        assert "<user>Hello</user>" in result
        assert "<assistant>Hi there</assistant>" in result
        assert "\n\n" in result

    def test_format_conversation_lowercases_role(self):
        """Should lowercase role names in tags."""
        conversation = [{"role": "USER", "content": "Test"}]

        result = testbed_metrics.format_conversation(conversation)

        assert result == "<user>Test</user>"

    def test_format_conversation_empty_list(self):
        """Should return empty string for empty conversation."""
        result = testbed_metrics.format_conversation([])

        assert result == ""

    def test_format_conversation_preserves_content(self):
        """Should preserve message content including special characters."""
        conversation = [{"role": "user", "content": "What is 2 + 2?\nIs it 4?"}]

        result = testbed_metrics.format_conversation(conversation)

        assert "What is 2 + 2?\nIs it 4?" in result


class TestCorrectnessInputTemplate:
    """Tests for the CORRECTNESS_INPUT_TEMPLATE constant."""

    def test_template_contains_placeholders(self):
        """Template should contain all required placeholders."""
        template = testbed_metrics.CORRECTNESS_INPUT_TEMPLATE

        assert "{description}" in template
        assert "{conversation}" in template
        assert "{answer}" in template
        assert "{reference_answer}" in template

    def test_template_format_works(self):
        """Template should be formattable with all placeholders."""
        result = testbed_metrics.CORRECTNESS_INPUT_TEMPLATE.format(
            description="Test agent",
            conversation="<user>Hello</user>",
            answer="Hi there",
            reference_answer="Hello back",
        )

        assert "Test agent" in result
        assert "<user>Hello</user>" in result
        assert "Hi there" in result
        assert "Hello back" in result


class TestCustomCorrectnessMetricInit:
    """Tests for CustomCorrectnessMetric initialization."""

    def test_init_with_required_params(self):
        """Should initialize with required parameters."""
        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
        )

        assert metric.system_prompt == "You are a judge."
        assert metric.agent_description == "A chatbot answering questions."

    def test_init_with_custom_agent_description(self):
        """Should accept custom agent description."""
        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
            agent_description="A specialized Q&A bot.",
        )

        assert metric.agent_description == "A specialized Q&A bot."

    def test_init_with_llm_client(self):
        """Should accept custom LLM client."""
        mock_client = MagicMock()

        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
            llm_client=mock_client,
        )

        assert metric._llm_client == mock_client


class TestCustomCorrectnessMetricCall:
    """Tests for CustomCorrectnessMetric __call__ method."""

    @patch("server.api.utils.testbed_metrics.get_default_client")
    @patch("server.api.utils.testbed_metrics.parse_json_output")
    def test_call_returns_correctness_result(self, mock_parse, mock_get_client):
        """Should return correctness evaluation result."""
        mock_client = MagicMock()
        mock_client.complete.return_value = MagicMock(content='{"correctness": true}')
        mock_get_client.return_value = mock_client
        mock_parse.return_value = {"correctness": True}

        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
        )

        mock_sample = MagicMock()
        mock_sample.conversation_history = []
        mock_sample.question = "What is AI?"
        mock_sample.reference_answer = "Artificial Intelligence"

        mock_answer = MagicMock()
        mock_answer.message = "AI stands for Artificial Intelligence"

        result = metric(mock_sample, mock_answer)

        assert result == {"correctness": True}
        mock_client.complete.assert_called_once()

    @patch("server.api.utils.testbed_metrics.get_default_client")
    @patch("server.api.utils.testbed_metrics.parse_json_output")
    def test_call_strips_reason_when_correct(self, mock_parse, mock_get_client):
        """Should strip correctness_reason when answer is correct."""
        mock_client = MagicMock()
        mock_client.complete.return_value = MagicMock(content='{}')
        mock_get_client.return_value = mock_client
        mock_parse.return_value = {"correctness": True, "correctness_reason": "Matches exactly"}

        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
        )

        mock_sample = MagicMock()
        mock_sample.conversation_history = []
        mock_sample.question = "Q"
        mock_sample.reference_answer = "A"

        mock_answer = MagicMock()
        mock_answer.message = "A"

        result = metric(mock_sample, mock_answer)

        assert "correctness_reason" not in result

    @patch("server.api.utils.testbed_metrics.get_default_client")
    @patch("server.api.utils.testbed_metrics.parse_json_output")
    def test_call_keeps_reason_when_incorrect(self, mock_parse, mock_get_client):
        """Should keep correctness_reason when answer is incorrect."""
        mock_client = MagicMock()
        mock_client.complete.return_value = MagicMock(content='{}')
        mock_get_client.return_value = mock_client
        mock_parse.return_value = {"correctness": False, "correctness_reason": "Does not match"}

        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
        )

        mock_sample = MagicMock()
        mock_sample.conversation_history = []
        mock_sample.question = "Q"
        mock_sample.reference_answer = "A"

        mock_answer = MagicMock()
        mock_answer.message = "Wrong"

        result = metric(mock_sample, mock_answer)

        assert result["correctness_reason"] == "Does not match"

    @patch("server.api.utils.testbed_metrics.get_default_client")
    @patch("server.api.utils.testbed_metrics.parse_json_output")
    def test_call_raises_on_non_boolean_correctness(self, mock_parse, mock_get_client):
        """Should raise LLMGenerationError if correctness is not boolean."""
        mock_client = MagicMock()
        mock_client.complete.return_value = MagicMock(content='{}')
        mock_get_client.return_value = mock_client
        mock_parse.return_value = {"correctness": "yes"}  # String instead of bool

        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
        )

        mock_sample = MagicMock()
        mock_sample.conversation_history = []
        mock_sample.question = "Q"
        mock_sample.reference_answer = "A"

        mock_answer = MagicMock()
        mock_answer.message = "A"

        with pytest.raises(LLMGenerationError) as exc_info:
            metric(mock_sample, mock_answer)

        assert "Expected boolean" in str(exc_info.value)

    @patch("server.api.utils.testbed_metrics.get_default_client")
    def test_call_reraises_llm_generation_error(self, mock_get_client):
        """Should re-raise LLMGenerationError from LLM client."""
        mock_client = MagicMock()
        mock_client.complete.side_effect = LLMGenerationError("LLM failed")
        mock_get_client.return_value = mock_client

        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
        )

        mock_sample = MagicMock()
        mock_sample.conversation_history = []
        mock_sample.question = "Q"
        mock_sample.reference_answer = "A"

        mock_answer = MagicMock()
        mock_answer.message = "A"

        with pytest.raises(LLMGenerationError):
            metric(mock_sample, mock_answer)

    @patch("server.api.utils.testbed_metrics.get_default_client")
    def test_call_wraps_other_exceptions(self, mock_get_client):
        """Should wrap other exceptions in LLMGenerationError."""
        mock_client = MagicMock()
        mock_client.complete.side_effect = RuntimeError("Unexpected error")
        mock_get_client.return_value = mock_client

        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
        )

        mock_sample = MagicMock()
        mock_sample.conversation_history = []
        mock_sample.question = "Q"
        mock_sample.reference_answer = "A"

        mock_answer = MagicMock()
        mock_answer.message = "A"

        with pytest.raises(LLMGenerationError) as exc_info:
            metric(mock_sample, mock_answer)

        assert "Error while evaluating" in str(exc_info.value)

    @patch("server.api.utils.testbed_metrics.get_default_client")
    @patch("server.api.utils.testbed_metrics.parse_json_output")
    def test_call_uses_provided_llm_client(self, mock_parse, mock_get_client):
        """Should use provided LLM client instead of default."""
        mock_provided_client = MagicMock()
        mock_provided_client.complete.return_value = MagicMock(content='{}')
        mock_parse.return_value = {"correctness": True}

        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
            llm_client=mock_provided_client,
        )

        mock_sample = MagicMock()
        mock_sample.conversation_history = []
        mock_sample.question = "Q"
        mock_sample.reference_answer = "A"

        mock_answer = MagicMock()
        mock_answer.message = "A"

        metric(mock_sample, mock_answer)

        mock_provided_client.complete.assert_called_once()
        mock_get_client.assert_not_called()

    @patch("server.api.utils.testbed_metrics.get_default_client")
    @patch("server.api.utils.testbed_metrics.parse_json_output")
    def test_call_includes_conversation_history(self, mock_parse, mock_get_client):
        """Should include conversation history in the prompt."""
        mock_client = MagicMock()
        mock_client.complete.return_value = MagicMock(content='{}')
        mock_get_client.return_value = mock_client
        mock_parse.return_value = {"correctness": True}

        metric = testbed_metrics.CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
        )

        mock_sample = MagicMock()
        mock_sample.conversation_history = [
            {"role": "user", "content": "Previous question"},
            {"role": "assistant", "content": "Previous answer"},
        ]
        mock_sample.question = "Follow-up question"
        mock_sample.reference_answer = "Expected answer"

        mock_answer = MagicMock()
        mock_answer.message = "Actual answer"

        metric(mock_sample, mock_answer)

        call_args = mock_client.complete.call_args
        user_message = call_args.kwargs["messages"][1].content
        assert "Previous question" in user_message
        assert "Previous answer" in user_message
        assert "Follow-up question" in user_message
