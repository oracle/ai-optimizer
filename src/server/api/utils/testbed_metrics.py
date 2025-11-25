"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Custom metrics for testbed evaluation.

This module provides a customizable correctness metric for evaluating chatbot answers
against reference answers. Unlike Giskard's default CorrectnessMetric which has a
hardcoded prompt, this allows the system prompt to be configured via MCP prompts.
"""
# spell-checker:ignore giskard

from giskard.rag.metrics.base import Metric
from giskard.llm.client import ChatMessage, LLMClient, get_default_client
from giskard.llm.errors import LLMGenerationError
from giskard.rag.base import AgentAnswer
from giskard.rag.question_generators.utils import parse_json_output


def format_conversation(conversation: list[dict]) -> str:
    """Format conversation history for the evaluation prompt.

    Args:
        conversation: List of message dicts with 'role' and 'content' keys.

    Returns:
        Formatted string with XML-style role tags.
    """
    return "\n\n".join(
        [f"<{msg['role'].lower()}>{msg['content']}</{msg['role'].lower()}>" for msg in conversation]
    )


CORRECTNESS_INPUT_TEMPLATE = """
### AGENT DESCRIPTION
{description}

### CONVERSATION
{conversation}

### AGENT ANSWER
{answer}

### REFERENCE ANSWER
{reference_answer}
"""


class CustomCorrectnessMetric(Metric):  # pylint: disable=too-few-public-methods
    """Custom correctness metric with configurable system prompt.

    This metric evaluates whether an agent's answer correctly matches a reference answer.
    Unlike Giskard's built-in CorrectnessMetric, this allows the evaluation prompt to be
    customized, enabling different levels of strictness for different use cases.

    The default prompt (configured via MCP) is more lenient than Giskard's default:
    - Allows additional context beyond the reference answer
    - Only marks incorrect if essential information is missing or contradicted
    - Treats "I don't know" responses as incorrect (important for RAG evaluation)
    """

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
        super().__init__(name=name, llm_client=llm_client)
        self.system_prompt = system_prompt
        self.agent_description = agent_description or "A chatbot answering questions."

    def __call__(self, question_sample: dict, answer: AgentAnswer) -> dict:
        """Evaluate correctness of agent answer vs reference.

        Args:
            question_sample: A question sample from a QATestset containing:
                - question: The question asked
                - reference_answer: The expected correct answer
                - conversation_history: Prior conversation context
            answer: The agent's answer (AgentAnswer object with .message attribute).

        Returns:
            Dict with 'correctness' (bool) and optionally 'correctness_reason' (str).

        Raises:
            LLMGenerationError: If the evaluation fails.
        """
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
                format="json_object",
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

            return json_output

        except LLMGenerationError:
            raise
        except Exception as err:
            raise LLMGenerationError("Error while evaluating the agent") from err
