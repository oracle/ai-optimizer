"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for testbed Giskard checks.
"""
# spell-checker:disable

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from giskard.checks import Interaction, Trace

from server.app.testbed.metrics import CustomCorrectnessCheck, build_evaluation_suite, format_conversation


@pytest.mark.unit
def test_format_conversation_single_message():
    assert format_conversation([{"role": "user", "content": "hello"}]) == "<user>hello</user>"


@pytest.mark.unit
def test_format_conversation_multiple_messages():
    messages = [
        {"role": "User", "content": "question"},
        {"role": "Assistant", "content": "answer"},
    ]
    result = format_conversation(messages)
    assert "<user>question</user>" in result
    assert "<assistant>answer</assistant>" in result
    assert "\n\n" in result


@pytest.mark.unit
def test_format_conversation_empty():
    assert format_conversation([]) == ""


def _trace():
    return Trace(
        interactions=[
            Interaction(
                inputs={"question": "What is the answer?"},
                outputs={"answer": "The answer."},
                metadata={
                    "conversation_history": [{"role": "user", "content": "Earlier question"}],
                    "reference_answer": "The answer.",
                },
            )
        ]
    )


def _response(payload: dict):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


@pytest.mark.unit
@pytest.mark.anyio
async def test_correctness_check_passes_equivalent_answer():
    completion = AsyncMock(return_value=_response({"correctness": True, "correctness_reason": "Equivalent"}))
    check = CustomCorrectnessCheck(judge_config={"model": "openai/test"}, system_prompt="Judge carefully.")

    with patch("server.app.testbed.metrics.litellm.acompletion", completion):
        result = await check.run(_trace())

    assert result.passed
    assert result.details["correctness"] is True
    assert completion.await_args is not None
    messages = completion.await_args.kwargs["messages"]
    assert messages[0]["content"] == "Judge carefully."
    assert "Earlier question" in messages[1]["content"]
    assert "The answer." in messages[1]["content"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_correctness_check_fails_with_judge_reason():
    completion = AsyncMock(return_value=_response({"correctness": False, "correctness_reason": "Wrong answer"}))
    check = CustomCorrectnessCheck(judge_config={"model": "openai/test"}, system_prompt="Judge carefully.")

    with patch("server.app.testbed.metrics.litellm.acompletion", completion):
        result = await check.run(_trace())

    assert result.failed
    assert result.message == "Wrong answer"
    assert result.details["correctness_reason"] == "Wrong answer"


@pytest.mark.unit
@pytest.mark.anyio
async def test_correctness_check_rejects_non_boolean_verdict():
    completion = AsyncMock(return_value=_response({"correctness": "yes"}))
    check = CustomCorrectnessCheck(judge_config={"model": "openai/test"}, system_prompt="Judge carefully.")

    with (
        patch("server.app.testbed.metrics.litellm.acompletion", completion),
        pytest.raises(ValueError, match="boolean 'correctness'"),
    ):
        await check.run(_trace())


@pytest.mark.unit
@pytest.mark.anyio
async def test_correctness_check_propagates_provider_errors():
    completion = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    check = CustomCorrectnessCheck(judge_config={"model": "openai/test"}, system_prompt="Judge carefully.")

    with (
        patch("server.app.testbed.metrics.litellm.acompletion", completion),
        pytest.raises(RuntimeError, match="provider unavailable"),
    ):
        await check.run(_trace())


@pytest.mark.unit
@pytest.mark.parametrize("correctness", [True, False])
async def test_evaluation_runs_one_correctness_judge_per_question(correctness):
    from server.app.api.v1.endpoints.testbed import _serialise_report

    questions = []

    async def target(inputs):
        questions.append(inputs["question"])
        return {"answer": "Paris"}

    record = {
        "id": "Q1",
        "question": "Where is the Eiffel Tower?",
        "reference_answer": "Paris",
        "reference_context": "The Eiffel Tower is in Paris.",
        "metadata": {"topic": "Geography"},
    }
    completion = AsyncMock(return_value=_response({"correctness": correctness, "correctness_reason": "Judged"}))
    suite = build_evaluation_suite([record], target, {"model": "openai/test"}, "Judge carefully.")

    with patch("server.app.testbed.metrics.litellm.acompletion", completion):
        result = await suite.run(parallel=False, return_exception=False, verbose=False)

    completion.assert_awaited_once()
    assert questions == [record["question"]]
    payload = _serialise_report(result)
    assert payload["correctness"] == float(correctness)
    assert payload["report"]["correctness"] == {"Q1": correctness}
    assert payload["correct_by_topic"]["correctness"] == {"Geography": float(correctness)}
    assert bool(payload["failures"]) is not correctness
