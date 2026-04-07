"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Base flow session for WayFlow runtime.

Provides the common pattern for flow sessions that accumulate Q&A turns
and pass them to the flow when chat_history is enabled.
"""
# spell-checker: ignore executionstatus spanprocessor subflows wayflow wayflowcore

import logging
from typing import Any, Dict, Optional, Sequence

from wayflowcore.executors.executionstatus import FinishedStatus
from wayflowcore.flow import Flow as RuntimeFlow
from wayflowcore.tracing.spanprocessor import SpanProcessor

from server.app.api.v1.schemas.chat import TokenUsage
from server.app.core.schemas import ClientSettings
from server.app.runtime.common import SessionMetadata, parse_grade_relevant, parse_vs_metadata
from server.app.runtime.wayflow.adapters.streaming import _collect_all_step_dicts
from server.app.runtime.wayflow.tracing import maybe_trace

LOGGER = logging.getLogger(__name__)


def _extract_agent_token_usage(session: Any) -> Optional[TokenUsage]:
    """Read cumulative token usage from an agent conversation."""
    conv = getattr(session, "conversation", None)
    if conv is None:
        return None
    tu = getattr(conv, "token_usage", None)
    if tu is None:
        return None
    input_t = getattr(tu, "input_tokens", 0) or 0
    output_t = getattr(tu, "output_tokens", 0) or 0
    total_t = getattr(tu, "total_tokens", 0) or 0
    if not isinstance(input_t, (int, float)) or not (input_t or output_t or total_t):
        return None
    return TokenUsage(
        prompt_tokens=int(input_t),
        completion_tokens=int(output_t),
        total_tokens=int(total_t or (input_t + output_t)),
    )


def update_agent_state(agent: Any) -> None:
    """Rebuild agent internal state after modifying custom_instruction.

    Required after setting ``agent.custom_instruction`` on a wayflowcore
    RuntimeAgent.
    """
    getattr(agent, "_update_internal_state")()


class FlowSession:
    """Base session for flow execution with conversation history.

    Reads the chat_history toggle from client_settings, accumulates
    Q&A turns when enabled, and provides the core execute loop.
    Subclasses override build_inputs to supply flow-specific inputs.

    Parameters
    ----------
    flow:
        A WayFlow Flow instance.
    client_settings:
        ClientSettings object with ll_model config including chat_history toggle.
    """

    def __init__(
        self,
        flow: RuntimeFlow,
        client_settings: ClientSettings,
        span_processors: Optional[Sequence[SpanProcessor]] = None,
    ):
        self.flow = flow
        ll_model = client_settings.ll_model
        self._model = f"{ll_model.provider}/{ll_model.id}"
        self._history: str = ""
        self._span_processors = span_processors
        self.last_metadata = SessionMetadata()

    @property
    def history(self) -> str:
        """Conversation history accumulated across turns."""
        return self._history

    @history.setter
    def history(self, value: str) -> None:
        self._history = value

    def build_inputs(self, query: str, thread_id: str, chat_history: bool = True) -> Dict[str, Any]:
        """Build the inputs dict for the flow. Override in subclasses."""
        return {
            "query": query,
            "thread_id": thread_id,
            "model": self._model,
            "chat_history": self._history if chat_history else "",
        }

    async def execute(self, query: str, thread_id: str, chat_history: bool = True) -> str:
        """Execute the flow with the given query.

        Parameters
        ----------
        query:
            Natural language question.
        thread_id:
            Session/thread identifier for MCP tool calls.
        chat_history:
            If True, include prior conversation turns in the flow input.

        Returns
        -------
        str
            Natural language answer from the flow.
        """
        inputs = self.build_inputs(query, thread_id, chat_history=chat_history)

        conversation = self.flow.start_conversation(inputs=inputs)
        self._clear_token_usage()
        self.last_metadata = SessionMetadata()

        try:
            with maybe_trace("flow_execute", self._span_processors):
                status = await conversation.execute_async()
        except Exception:
            LOGGER.exception("Flow execution failed for query: %s", query)
            return "An error occurred while processing your request."

        # Prefer flow output values (works with send_message=False),
        # fall back to last conversation message.
        answer = ""
        if isinstance(status, FinishedStatus) and status.output_values:
            answer_value = status.output_values.get("answer")
            answer = str(answer_value) if answer_value is not None else ""
            # Parse grade_relevant to determine if vecsearch results are useful.
            grade_relevant = parse_grade_relevant(status.output_values.get("grade_relevant"))
            self.last_metadata.grade_relevant = grade_relevant

            vs_meta = parse_vs_metadata(status.output_values)
            if vs_meta and grade_relevant == "no":
                vs_meta.documents = []
            self.last_metadata.vs_metadata = vs_meta
        token_usage = self._extract_token_usage()
        if token_usage:
            self.last_metadata.token_usage = TokenUsage(
                prompt_tokens=token_usage.input_tokens,
                completion_tokens=token_usage.output_tokens,
                total_tokens=(
                    getattr(token_usage, "total_tokens", 0) or (token_usage.input_tokens + token_usage.output_tokens)
                ),
            )

        if not answer:
            last = conversation.get_last_message()
            answer = (last.content or "") if last else ""

        self._history += f"User: {query}\nAssistant: {answer}\n"

        return answer

    def _clear_token_usage(self):
        """Reset last_token_usage on all step LLMs before a new execution."""
        steps = getattr(self.flow, "steps", None)
        if not steps:
            return
        for step_dict in _collect_all_step_dicts(self.flow):
            for step in step_dict.values():
                llm = getattr(step, "llm", None)
                if llm is not None and hasattr(llm, "last_token_usage"):
                    llm.last_token_usage = None

    def _extract_token_usage(self):
        """Find the most recent token_usage from any LiteLlmModel step.

        Checks each step-dict level in order (top-level first, then nested
        subflows) but reverses within each dict so later steps are preferred.
        This means a top-level ``synthesize`` step (which runs after parallel
        subflows in the "both" branch) is found before a nested
        ``format_answer`` step, while single-branch flows still find the
        nested ``format_answer`` correctly.
        """
        steps = getattr(self.flow, "steps", None)
        if not steps:
            return None
        for step_dict in _collect_all_step_dicts(self.flow):
            for step in reversed(list(step_dict.values())):
                llm = getattr(step, "llm", None)
                if llm is not None and hasattr(llm, "last_token_usage") and llm.last_token_usage:
                    return llm.last_token_usage
        return None
