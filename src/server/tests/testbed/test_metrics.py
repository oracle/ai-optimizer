"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for testbed custom correctness metric.
"""
# spell-checker:disable

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from server.app.testbed.metrics import (
    CustomCorrectnessMetric,
    format_conversation,
)

# ---------------------------------------------------------------------------
# format_conversation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_format_conversation_single_message():
    """Single message produces one XML-like tag."""
    result = format_conversation([{"role": "user", "content": "hello"}])
    assert result == "<user>hello</user>"


@pytest.mark.unit
def test_format_conversation_multiple_messages():
    """Multiple messages are separated by double newlines."""
    msgs = [
        {"role": "User", "content": "question"},
        {"role": "Assistant", "content": "answer"},
    ]
    result = format_conversation(msgs)
    assert "<user>question</user>" in result
    assert "<assistant>answer</assistant>" in result
    assert "\n\n" in result


@pytest.mark.unit
def test_format_conversation_empty():
    """Empty conversation returns empty string."""
    assert format_conversation([]) == ""


# ---------------------------------------------------------------------------
# CustomCorrectnessMetric — helpers
# ---------------------------------------------------------------------------


@dataclass
class _QuestionSample:
    """Typed stand-in for a Giskard question sample row."""

    question: str = "What?"
    reference_answer: str = "The answer."
    conversation_history: list[dict[str, Any]] = field(default_factory=list)


def _make_question_sample(question="What?", reference="The answer.", history=None):
    """Create a typed question sample mimicking a Giskard testset row."""
    return _QuestionSample(
        question=question,
        reference_answer=reference,
        conversation_history=history or [],
    )


def _make_mock_answer(message="The answer."):
    """Create a mock AgentAnswer without importing giskard."""
    return SimpleNamespace(message=message)


class _LLMGenerationError(Exception):
    """Stand-in for giskard.llm.errors.LLMGenerationError in tests."""


@pytest.fixture()
def giskard_mocks():
    """Patch giskard symbols on metrics module so tests control LLM behavior."""
    mock_parse_json = MagicMock()
    with (
        patch("server.app.testbed.metrics.ChatMessage", MagicMock),
        patch("server.app.testbed.metrics.get_default_client", MagicMock()),
        patch("server.app.testbed.metrics.LLMGenerationError", _LLMGenerationError),
        patch("server.app.testbed.metrics.parse_json_output", mock_parse_json),
    ):
        yield mock_parse_json


# ---------------------------------------------------------------------------
# CustomCorrectnessMetric — tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_metric_correct_answer(giskard_mocks):
    """Metric returns correctness=True for a correct answer."""
    mock_client = MagicMock()
    mock_client.complete.return_value = MagicMock(content='{"correctness": true, "correctness_reason": "matches"}')
    giskard_mocks.return_value = {
        "correctness": True,
        "correctness_reason": "matches",
    }

    metric = CustomCorrectnessMetric(
        name="correctness",
        system_prompt="You are a judge.",
        llm_client=mock_client,
    )
    result = metric(_make_question_sample(), _make_mock_answer())

    assert result["correctness"] is True
    assert "correctness_reason" not in result  # stripped when correct


@pytest.mark.unit
def test_metric_incorrect_answer(giskard_mocks):
    """Metric returns correctness=False with reason."""
    mock_client = MagicMock()
    mock_client.complete.return_value = MagicMock(
        content='{"correctness": false, "correctness_reason": "wrong answer"}'
    )
    giskard_mocks.return_value = {
        "correctness": False,
        "correctness_reason": "wrong answer",
    }

    metric = CustomCorrectnessMetric(
        name="correctness",
        system_prompt="You are a judge.",
        llm_client=mock_client,
    )
    result = metric(_make_question_sample(), _make_mock_answer("wrong"))

    assert result["correctness"] is False
    assert result["correctness_reason"] == "wrong answer"


@pytest.mark.unit
def test_metric_non_boolean_correctness(giskard_mocks):
    """Metric raises LLMGenerationError when correctness is not a boolean."""
    mock_client = MagicMock()
    mock_client.complete.return_value = MagicMock(content='{"correctness": "yes"}')
    giskard_mocks.return_value = {
        "correctness": "yes",
        "correctness_reason": "",
    }

    with pytest.raises(_LLMGenerationError, match="Expected boolean"):
        metric = CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
            llm_client=mock_client,
        )
        metric(_make_question_sample(), _make_mock_answer())


@pytest.mark.usefixtures("giskard_mocks")
@pytest.mark.unit
def test_metric_wraps_unexpected_exception():
    """Unexpected exceptions are wrapped in LLMGenerationError."""
    mock_client = MagicMock()
    mock_client.complete.side_effect = RuntimeError("boom")

    with pytest.raises(_LLMGenerationError, match="Error while evaluating"):
        metric = CustomCorrectnessMetric(
            name="correctness",
            system_prompt="You are a judge.",
            llm_client=mock_client,
        )
        metric(_make_question_sample(), _make_mock_answer())


@pytest.mark.unit
def test_metric_default_description():
    """Default agent description is used when none is provided."""
    metric = CustomCorrectnessMetric(name="correctness", system_prompt="judge")
    assert metric.agent_description == "A chatbot answering questions."


@pytest.mark.unit
def test_metric_custom_description():
    """Custom agent description is preserved."""
    metric = CustomCorrectnessMetric(name="correctness", system_prompt="judge", agent_description="My custom bot")
    assert metric.agent_description == "My custom bot"
