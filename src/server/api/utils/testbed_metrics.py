"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Custom metrics for testbed evaluation.

This module provides a customizable correctness metric for evaluating chatbot answers
against reference answers. Unlike Giskard's default CorrectnessMetric which has a
hardcoded prompt, this allows the system prompt to be configured via MCP prompts.
"""
# spell-checker:ignore giskard

from giskard.rag.metrics import CorrectnessMetric
from giskard.llm.client import ChatMessage, LLMClient, get_default_client
from giskard.llm.errors import LLMGenerationError
from giskard.rag.base import AgentAnswer
from giskard.rag.question_generators.utils import parse_json_output


def format_conversation(conversation: list[dict]) -> str:
    """Format conversation history for the evaluation prompt."""
    return "\n\n".join([f"<{msg['role'].lower()}>{msg['content']}</{msg['role'].lower()}>" for msg in conversation])


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


class CustomCorrectnessMetric(CorrectnessMetric):  # pylint: disable=too-few-public-methods
    """Custom correctness metric with configurable system prompt."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        llm_client: LLMClient = None,
        agent_description: str = None,
    ):
        """Initialize the custom correctness metric.

        Args:
            name: The metric name (typically "correctness").
            system_prompt: The system prompt for the judge LLM.
            llm_client: Optional LLM client. If not provided, uses Giskard's default.
            agent_description: Description of the agent being evaluated.
        """
        # Call parent with name and llm_client only (CorrectnessMetric signature)
        super().__init__(name=name, llm_client=llm_client)
        self.system_prompt = system_prompt
        self.agent_description = agent_description or "A chatbot answering questions."

    def __call__(self, question_sample: dict, answer: AgentAnswer) -> dict:
        """Evaluate correctness of agent answer vs reference."""
        llm_client = self._llm_client or get_default_client()
        try:
            out = llm_client.complete(
                messages=[
                    ChatMessage(role="system", content=self.system_prompt),
                    ChatMessage(
                        role="user",
                        content=CORRECTNESS_INPUT_TEMPLATE.format(
                            conversation=format_conversation(
                                question_sample.conversation_history
                                + [{"role": "user", "content": question_sample.question}]
                            ),
                            answer=answer.message,
                            reference_answer=question_sample.reference_answer,
                            description=self.agent_description,
                        ),
                    ),
                ],
                temperature=0,
            )

            json_output = parse_json_output(
                out.content,
                llm_client=llm_client,
                keys=["correctness", "correctness_reason"],
                caller_id=self.__class__.__name__,
            )

            if "correctness" in json_output and not isinstance(json_output["correctness"], bool):
                raise LLMGenerationError(
                    f"Error in correctness evaluation: {json_output['correctness']}. "
                    "Expected boolean value for 'correctness' key."
                )

            # Strip correctness_reason when correct (LLM sometimes includes it anyway)
            if json_output.get("correctness") is True:
                json_output.pop("correctness_reason", None)

            return json_output

        except LLMGenerationError:
            raise
        except Exception as err:
            raise LLMGenerationError("Error while evaluating the agent") from err
