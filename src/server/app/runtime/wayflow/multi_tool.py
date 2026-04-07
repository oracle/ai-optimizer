"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Combined session — Python-level orchestrator for NL2SQL + VecSearch routing.

Uses a lightweight LLM classification call to route queries to the
appropriate sub-session (VecSearchFlowSession or NL2SQLAgentSession),
or runs both in parallel and synthesizes the results.
"""
# spell-checker: ignore agentspec litellm vecsearch wayflow wayflowcore acompletion ollama

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from server.app.runtime.common import (
    COMBINED_PROMPT_NAME as PROMPT_NAME,
)
from server.app.runtime.common import (
    DEFAULT_COMBINED_INSTRUCTION,
    BaseCombinedSession,
    SessionMetadata,
    _sum_token_usage,
)
from server.app.runtime.wayflow.nl2sql import NL2SQLAgentSession
from server.app.runtime.wayflow.session import FlowSession, _extract_agent_token_usage

LOGGER = logging.getLogger(__name__)

__all__ = ["CombinedSession", "PROMPT_NAME", "DEFAULT_COMBINED_INSTRUCTION"]


class CombinedSession(BaseCombinedSession):
    """Hybrid session that routes queries to VecSearch, NL2SQL, or both.

    Holds a VecSearchFlowSession and an NL2SQLAgentSession, using a
    lightweight LLM classification call for routing.
    """

    def __init__(
        self,
        vs_session: FlowSession,
        nl2sql_session: NL2SQLAgentSession,
        classifier_model: str,
        system_prompt: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
    ) -> None:
        super().__init__(vs_session, nl2sql_session, classifier_model, system_prompt, api_key, api_base)

    async def execute(self, query: str, thread_id: str, chat_history: bool = True) -> str:
        """Route and execute the query through the appropriate sub-session(s)."""
        route, classifier_tu = await self.classify(query)
        self.last_metadata = SessionMetadata()

        if route == "vecsearch":
            answer = await self.vs_session.execute(query, thread_id, chat_history=chat_history)
            self.last_metadata = self.vs_session.last_metadata.model_copy()
            combined_tu = _sum_token_usage(self.last_metadata.token_usage, classifier_tu)
            if combined_tu:
                self.last_metadata.token_usage = combined_tu
        elif route == "nl2sql":
            answer = await self.nl2sql_session.chat(query, chat_history=chat_history)
            self.last_metadata.grade_relevant = "yes"
            combined_tu = _sum_token_usage(_extract_agent_token_usage(self.nl2sql_session), classifier_tu)
            if combined_tu:
                self.last_metadata.token_usage = combined_tu
        else:  # both
            vs_answer, nl2sql_answer = await asyncio.gather(
                self.vs_session.execute(query, thread_id, chat_history=chat_history),
                self.nl2sql_session.chat(query, chat_history=chat_history),
            )
            answer, synth_tu = await self._handle_both_results(query, vs_answer, nl2sql_answer)
            combined_tu = _sum_token_usage(
                classifier_tu,
                self.vs_session.last_metadata.token_usage,
                _extract_agent_token_usage(self.nl2sql_session),
                synth_tu,
            )
            if combined_tu:
                self.last_metadata.token_usage = combined_tu

        return answer

    async def execute_streaming(
        self,
        query: str,
        thread_id: str,
        chat_history: bool,
        queue: asyncio.Queue,
        stream_flow: Callable[..., Awaitable[None]],
        stream_agent: Callable[..., Awaitable[None]],
    ) -> None:
        """Route and execute with streaming, pushing events to *queue*."""
        route, classifier_tu = await self.classify(query)
        self.last_metadata = SessionMetadata()

        if classifier_tu:
            await queue.put({"type": "_token_usage", **classifier_tu.model_dump()})

        if route == "vecsearch":
            await stream_flow(self.vs_session, "vecsearch", query, thread_id, queue, chat_history)
            self.last_metadata = self.vs_session.last_metadata.model_copy()
        elif route == "nl2sql":
            await stream_agent(self.nl2sql_session, chat_history, query, queue)
        else:  # both — run sequentially, stream the synthesis
            vs_answer = await self.vs_session.execute(query, thread_id, chat_history=chat_history)
            nl2sql_answer = await self.nl2sql_session.chat(query, chat_history=chat_history)

            answer, synth_tu = await self._handle_both_results(query, vs_answer, nl2sql_answer)
            await queue.put({"type": "stream", "content": answer})

            for tu in (
                self.vs_session.last_metadata.token_usage,
                _extract_agent_token_usage(self.nl2sql_session),
                synth_tu,
            ):
                if tu:
                    await queue.put({"type": "_token_usage", **tu.model_dump()})
