"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Giskard checks for testbed evaluation.
"""
# spell-checker:ignore giskard litellm

import json
from typing import Any, cast

import litellm
from giskard.checks import AnswerRelevance, Check, CheckResult, Groundedness, LLMChatJudge, Scenario, Suite

from server.app.testbed.giskard_models import giskard_generator

CORRECTNESS_INPUT_TEMPLATE = """
### AGENT DESCRIPTION
{description}

### CONVERSATION
{conversation}

### AGENT ANSWER
{answer}

### EXPECTED ANSWER
{reference_answer}

You MUST respond with ONLY a valid JSON object (no markdown, no extra text) with exactly these keys:
{{"correctness": true/false, "correctness_reason": "your explanation"}}
"""


def format_conversation(conversation: list[dict]) -> str:
    """Format conversation history as XML-like tags for the evaluation prompt."""
    return "\n\n".join(f"<{msg['role'].lower()}>{msg['content']}</{msg['role'].lower()}>" for msg in conversation)


def _record_value(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _parse_json_object(content: str) -> dict:
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The judge returned invalid JSON")
    try:
        result = json.loads(content[start : end + 1])
    except json.JSONDecodeError as ex:
        raise ValueError("The judge returned invalid JSON") from ex
    if not isinstance(result, dict):
        raise ValueError("The judge returned an invalid result")
    return result


@Check.register("testbed_correctness")
class CustomCorrectnessCheck(Check):
    """Judge whether an agent answer matches the reference answer."""

    judge_config: dict[str, Any]
    system_prompt: str
    agent_description: str = "A chatbot answering questions."

    async def run(self, trace: Any) -> CheckResult:
        interaction = trace.last
        if interaction is None:
            return CheckResult.error(message="The evaluation scenario has no interaction")

        question = interaction.inputs["question"]
        answer = interaction.outputs["answer"]
        history = interaction.metadata.get("conversation_history", [])
        conversation = format_conversation(history + [{"role": "user", "content": question}])
        user_message = CORRECTNESS_INPUT_TEMPLATE.format(
            conversation=conversation,
            answer=answer,
            reference_answer=interaction.metadata["reference_answer"],
            description=self.agent_description,
        )
        request = {
            **self.judge_config,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        response = await litellm.acompletion(**request)
        result = _parse_json_object(cast(litellm.ModelResponse, response).choices[0].message.content or "")
        correctness = result.get("correctness")
        if not isinstance(correctness, bool):
            raise ValueError("Expected a boolean 'correctness' value from the judge")

        if correctness:
            return CheckResult.success(details={"correctness": True})

        reason = str(result.get("correctness_reason") or "The answer does not match the reference answer.").strip()
        return CheckResult.failure(
            message=reason,
            details={"correctness": False, "correctness_reason": reason},
        )


def build_evaluation_suite(
    qa_records: list[Any],
    target,
    judge_config: dict,
    judge_prompt: str,
) -> Suite:
    """Create correctness, groundedness, and relevance checks for each Q&A record."""
    suite = Suite(name="Testbed evaluation", target=target)
    judge = LLMChatJudge(generator=giskard_generator(judge_config))
    for index, record in enumerate(qa_records):
        question = _record_value(record, "question", "")
        history = _record_value(record, "conversation_history", []) or []
        reference_answer = _record_value(record, "reference_answer", "")
        metadata = _record_value(record, "metadata", {}) or {}
        scenario = Scenario(name=f"question-{index + 1}")
        scenario.interact(
            inputs={"question": question},
            metadata={
                "id": _record_value(record, "id", str(index)),
                "conversation_history": history,
                "reference_answer": reference_answer,
                "reference_context": _record_value(record, "reference_context", ""),
                "metadata": metadata,
            },
        )
        scenario.check(
            CustomCorrectnessCheck(name="correctness", judge_config=judge_config, system_prompt=judge_prompt)
        )
        if reference_context := _record_value(record, "reference_context", ""):
            scenario.check(
                Groundedness(
                    name="groundedness",
                    target_key="trace.last.outputs.answer",
                    context=reference_context,
                    judge=judge,
                )
            )
        scenario.check(
            AnswerRelevance(
                name="answer_relevance",
                question_key="trace.last.inputs.question",
                target_key="trace.last.outputs.answer",
                include_history=False,
                judge=judge,
            )
        )
        suite.append(scenario)
    return suite
