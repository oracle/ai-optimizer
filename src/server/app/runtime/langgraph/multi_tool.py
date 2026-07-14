"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Combined session for LangGraph runtime — Python-level orchestrator
for NL2SQL + VecSearch routing.

Uses a lightweight LLM classification call to route queries to the
appropriate sub-session, or runs both in parallel and synthesizes.
"""
# spell-checker: ignore vecsearch langgraph litellm acompletion ainvoke

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage

from server.app.api.v1.schemas.chat import TokenUsage
from server.app.mcp.prompts.registry import require_factory_text
from server.app.runtime.common import (
    CLASSIFIER_PROMPT_NAME,
    SYNTHESIS_PROMPT_NAME,
    ClassifierDecision,
    Route,
    SessionMetadata,
    _sum_token_usage,
)
from server.app.runtime.common import (
    COMBINED_PROMPT_NAME as PROMPT_NAME,
)
from server.app.runtime.langgraph.adapters.litellm import (
    OracleChatLiteLLM,
    extract_response_text,
    usage_metadata_to_token_usage,
)
from server.app.runtime.langgraph.session import (
    GraphFlowSession,
    NL2SQLGraphSession,
)

LOGGER = logging.getLogger(__name__)

__all__ = ["CombinedSession", "PROMPT_NAME"]


class CombinedSession:
    """Hybrid session that routes queries to VecSearch, NL2SQL, or both."""

    def __init__(
        self,
        vs_session: GraphFlowSession,
        nl2sql_session: NL2SQLGraphSession,
        classifier_model: str,
        system_prompt: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_kwargs: Optional[Dict[str, Any]] = None,
        classifier_prompt: Optional[str] = None,
        synthesis_template: Optional[str] = None,
    ) -> None:
        self.vs_session = vs_session
        self.nl2sql_session = nl2sql_session
        self._classifier_model = classifier_model
        self._system_prompt = system_prompt
        self._api_key = api_key
        self._api_base = api_base
        self._model_kwargs: Dict[str, Any] = dict(model_kwargs) if model_kwargs else {}
        self._classifier_prompt = classifier_prompt or require_factory_text(CLASSIFIER_PROMPT_NAME)
        self._synthesis_template = synthesis_template or require_factory_text(SYNTHESIS_PROMPT_NAME)
        self.last_metadata = SessionMetadata()

    async def _handle_both_results(
        self, query: str, vs_answer: str, nl2sql_answer: str
    ) -> tuple[str, Optional[TokenUsage]]:
        """Post-process the 'both' route: check grade_relevant, optionally synthesize."""
        vs_relevant = self.vs_session.last_metadata.grade_relevant
        synth_tu = None
        self.last_metadata = self.vs_session.last_metadata.model_copy()
        self.last_metadata.sql_metadata = self.nl2sql_session.last_metadata.sql_metadata
        if vs_relevant == "no":
            answer = nl2sql_answer
        else:
            answer, synth_tu = await self.synthesize(query, vs_answer, nl2sql_answer)
        return answer, synth_tu

    async def _ainvoke_text(
        self,
        prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> tuple[str, Optional[TokenUsage]]:
        """Single-prompt completion via ``OracleChatLiteLLM``; return (text, usage)."""
        llm = OracleChatLiteLLM(
            model=self._classifier_model,
            api_key=self._api_key,
            api_base=self._api_base,
            temperature=temperature,
            max_tokens=max_tokens,
            model_kwargs=self._model_kwargs,
        )
        result = await llm.ainvoke([HumanMessage(content=prompt)])
        text = extract_response_text(result.content)
        usage_metadata = result.usage_metadata if isinstance(result, AIMessage) else None
        return text, usage_metadata_to_token_usage(usage_metadata)

    async def classify(self, query: str) -> tuple[ClassifierDecision, Optional[TokenUsage]]:
        """Classify a query as nl2sql, vecsearch, or both."""
        prompt = self._classifier_prompt.replace("{{query}}", query)
        try:
            text, usage = await self._ainvoke_text(prompt, temperature=0.0, max_tokens=10)
        except Exception:
            LOGGER.exception("Classification failed, defaulting to %s", ClassifierDecision.BOTH)
            return ClassifierDecision.BOTH, None
        try:
            return ClassifierDecision(text.strip().lower().strip("'\".,!")), usage
        except ValueError:
            LOGGER.warning("Classifier returned unexpected value %r, defaulting to %s", text, ClassifierDecision.BOTH)
            return ClassifierDecision.BOTH, usage

    async def synthesize(
        self,
        query: str,
        vs_answer: str,
        nl2sql_answer: str,
    ) -> tuple[str, Optional[TokenUsage]]:
        """Synthesize answers from both sources into a single response."""
        prompt = self._synthesis_template.format(
            system_prompt=self._system_prompt,
            query=query,
            sql_answer=nl2sql_answer,
            search_answer=vs_answer,
        )
        try:
            return await self._ainvoke_text(prompt)
        except Exception:
            LOGGER.exception("Synthesis failed, returning concatenated answers")
            return f"Database result:\n{nl2sql_answer}\n\nDocument result:\n{vs_answer}", None

    async def execute(
        self,
        query: str,
        thread_id: str,
        history_text: str = "",
        history_messages: Optional[list] = None,
    ) -> str:
        """Route and execute the query."""
        route, classifier_tu = await self.classify(query)
        self.last_metadata = SessionMetadata()
        history_messages = history_messages or []

        if route == ClassifierDecision.VECSEARCH:
            answer = await self.vs_session.execute(query, thread_id, history_text=history_text)
            self.last_metadata = self.vs_session.last_metadata.model_copy()
            combined_tu = _sum_token_usage(self.last_metadata.token_usage, classifier_tu)
            if combined_tu:
                self.last_metadata.token_usage = combined_tu
        elif route == ClassifierDecision.NL2SQL:
            answer = await self.nl2sql_session.chat(query, history_messages=history_messages)
            self.last_metadata.grade_relevant = "yes"
            self.last_metadata.sql_metadata = self.nl2sql_session.last_metadata.sql_metadata
            combined_tu = _sum_token_usage(self.nl2sql_session.last_metadata.token_usage, classifier_tu)
            if combined_tu:
                self.last_metadata.token_usage = combined_tu
        else:
            vs_answer, nl2sql_answer = await asyncio.gather(
                self.vs_session.execute(query, thread_id, history_text=history_text),
                self.nl2sql_session.chat(query, history_messages=history_messages),
            )
            answer, synth_tu = await self._handle_both_results(query, vs_answer, nl2sql_answer)
            combined_tu = _sum_token_usage(
                classifier_tu,
                self.vs_session.last_metadata.token_usage,
                self.nl2sql_session.last_metadata.token_usage,
                synth_tu,
            )
            if combined_tu:
                self.last_metadata.token_usage = combined_tu

        return answer

    async def execute_streaming(
        self,
        query: str,
        thread_id: str,
        history_text: str,
        history_messages: list,
        queue: asyncio.Queue,
        stream_flow: Callable[..., Awaitable[None]],
        stream_agent: Callable[..., Awaitable[None]],
    ) -> None:
        """Route and execute with streaming, pushing events to *queue*."""
        route, classifier_tu = await self.classify(query)
        self.last_metadata = SessionMetadata()

        if classifier_tu:
            await queue.put({"type": "_token_usage", **classifier_tu.model_dump()})

        if route == ClassifierDecision.VECSEARCH:
            await stream_flow(self.vs_session, Route.VECSEARCH, query, thread_id, queue, history_text)
            self.last_metadata = self.vs_session.last_metadata.model_copy()
        elif route == ClassifierDecision.NL2SQL:
            await stream_agent(self.nl2sql_session, history_messages, query, queue)
            self.last_metadata.grade_relevant = "yes"
            self.last_metadata.sql_metadata = self.nl2sql_session.last_metadata.sql_metadata
        else:
            # Synthesis requires both branches' answers, so we can't stream tokens
            # before the synthesis. Run the branches in parallel and emit the
            # synthesized answer as a single stream event below.
            vs_answer, nl2sql_answer = await asyncio.gather(
                self.vs_session.execute(query, thread_id, history_text=history_text),
                self.nl2sql_session.chat(query, history_messages=history_messages),
            )
            answer, synth_tu = await self._handle_both_results(query, vs_answer, nl2sql_answer)
            await queue.put({"type": "stream", "content": answer})

            for tu in (
                self.vs_session.last_metadata.token_usage,
                self.nl2sql_session.last_metadata.token_usage,
                synth_tu,
            ):
                if tu:
                    await queue.put({"type": "_token_usage", **tu.model_dump()})
