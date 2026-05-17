"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LangGraph chat orchestration — routing, session management, memory, and streaming.
"""
# spell-checker: ignore checkpointer vecsearch agentspec astream litellm

import asyncio
import logging
from typing import Any, Dict, Optional, Union

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from server.app.api.v1.schemas.chat import TokenUsage
from server.app.core.schemas import ClientSettings
from server.app.core.secrets import reveal
from server.app.models.litellm_utils import build_oci_litellm_params, find_model
from server.app.oci.registry import find_oci_profile_by_name
from server.app.runtime.common import (
    CLASSIFIER_PROMPT_NAME,
    ROUTE_PROMPTS,
    SYNTHESIS_PROMPT_NAME,
    BaseChatOrchestrator,
    Route,
    fetch_prompt_for_route,
    format_history_text,
    resolve_route,
    validate_classifier_prompt,
    validate_synthesis_template,
)
from server.app.runtime.langgraph.llm_only import (
    PROMPT_NAME as LLM_ONLY_PROMPT,
)
from server.app.runtime.langgraph.llm_only import (
    build_llm_only_graph,
)
from server.app.runtime.langgraph.multi_tool import (
    PROMPT_NAME as COMBINED_PROMPT,
)
from server.app.runtime.langgraph.multi_tool import CombinedSession
from server.app.runtime.langgraph.nl2sql import (
    PROMPT_NAME as NL2SQL_PROMPT,
)
from server.app.runtime.langgraph.nl2sql import (
    build_nl2sql_graph,
)
from server.app.runtime.langgraph.session import (
    AgentGraphSession,
    GraphFlowSession,
    NL2SQLGraphSession,
)
from server.app.runtime.langgraph.vecsearch import (
    PROMPT_NAME as VECSEARCH_PROMPT,
)
from server.app.runtime.langgraph.vecsearch import build_vecsearch_graph

LOGGER = logging.getLogger(__name__)

SessionType = Union[GraphFlowSession, AgentGraphSession, CombinedSession]

ROUTE_PROMPTS.update(
    {
        Route.LLM_ONLY: LLM_ONLY_PROMPT,
        Route.NL2SQL: NL2SQL_PROMPT,
        Route.VECSEARCH: VECSEARCH_PROMPT,
        Route.COMBINED: COMBINED_PROMPT,
    }
)


class ChatOrchestrator(BaseChatOrchestrator):
    """Stateful chat orchestrator for the LangGraph runtime."""

    _agent_session_type = AgentGraphSession
    _combined_session_type = CombinedSession
    _flow_session_type = GraphFlowSession
    _nl2sql_session_type = NL2SQLGraphSession

    # -- session factory ---------------------------------------------------

    async def _build_flow_session(self, cs: ClientSettings) -> GraphFlowSession:
        """Build a vecsearch flow session from client settings."""
        graph = await build_vecsearch_graph(cs, self._server_url, self.api_key)
        return GraphFlowSession(graph, cs)

    async def _build_agent_session(self, cs: ClientSettings) -> AgentGraphSession:
        """Build an LLM-only agent session from client settings."""
        graph = await build_llm_only_graph(cs, self._server_url, self.api_key, checkpointer=MemorySaver())
        return AgentGraphSession(graph)

    async def _build_nl2sql_agent_session(
        self, cs: ClientSettings, client: str = ""
    ) -> NL2SQLGraphSession:
        """Build an NL2SQL agent session from client settings."""
        graph = await build_nl2sql_graph(cs, self._server_url, self.api_key, checkpointer=MemorySaver())
        return NL2SQLGraphSession(graph, cs, thread_id=client)

    async def _build_combined_session(self, cs: ClientSettings, client: str = "") -> CombinedSession:
        """Build a combined vecsearch + NL2SQL session from client settings."""
        graph = await build_vecsearch_graph(cs, self._server_url, self.api_key)
        vs_session = GraphFlowSession(graph, cs)

        nl2sql_graph = await build_nl2sql_graph(cs, self._server_url, self.api_key, checkpointer=MemorySaver())
        nl2sql_session = NL2SQLGraphSession(nl2sql_graph, cs, thread_id=client)

        ll_model = cs.ll_model
        assert ll_model.provider is not None
        assert ll_model.id is not None
        classifier_model = f"{ll_model.provider}/{ll_model.id}"
        model_cfg = find_model(ll_model.provider, ll_model.id, enabled_only=False, case_insensitive=True)

        # OCI auth must reach OracleChatLiteLLM via model_kwargs — LiteLLM's
        # OCI provider validates these at request-build time, not via env vars.
        model_kwargs: Dict[str, Any] = {}
        if ll_model.provider == "oci":
            oci_profile = find_oci_profile_by_name(cs.oci.auth_profile)
            if oci_profile:
                model_kwargs.update(build_oci_litellm_params(oci_profile))

        system_prompt, classifier_prompt, synthesis_template = await asyncio.gather(
            fetch_prompt_for_route(Route.COMBINED, self._server_url, self.api_key),
            self._fetch_validated_prompt(CLASSIFIER_PROMPT_NAME, validate_classifier_prompt),
            self._fetch_validated_prompt(SYNTHESIS_PROMPT_NAME, validate_synthesis_template),
        )

        return CombinedSession(
            vs_session,
            nl2sql_session,
            classifier_model,
            system_prompt,
            api_key=reveal(model_cfg.api_key) if model_cfg else None,
            api_base=model_cfg.api_base if model_cfg else None,
            model_kwargs=model_kwargs,
            classifier_prompt=classifier_prompt,
            synthesis_template=synthesis_template,
        )

    async def _build_session(
        self,
        cs: ClientSettings,
        route: Route,
        client: str = "",
    ) -> SessionType:
        """Dispatch to the appropriate session builder for the given route."""
        if route == Route.LLM_ONLY:
            return await self._build_agent_session(cs)
        if route == Route.NL2SQL:
            return await self._build_nl2sql_agent_session(cs, client=client)
        if route == Route.COMBINED:
            return await self._build_combined_session(cs, client=client)
        return await self._build_flow_session(cs)

    # -- session cache -----------------------------------------------------

    async def _get_or_create_session(self, client: str) -> tuple[SessionType, Route]:
        """Return a cached session or build a new one for the client.

        Sessions carry no conversation state — the orchestrator-owned
        ``HistoryStore`` is the source of truth — so route changes only
        require building a new session under the new key. No migration.
        """
        cs = self._resolve_client(client)
        self._validate_llm(cs)
        route = resolve_route(cs.tools_enabled)
        key = (client, route)
        cs_dict = cs.model_dump()
        identity = self._build_identity(cs_dict)

        cached = self._session_cache.get(key)
        if cached is not None and cached[2] == identity:
            return cached[0], route

        async with self._build_lock:
            cached = self._session_cache.get(key)
            if cached is not None and cached[2] == identity:
                return cached[0], route
            session = await self._build_session(cs, route, client=client)
            self._session_cache[key] = (session, cs_dict, identity)
        return session, route

    async def refresh_prompts(self) -> None:
        """Re-fetch prompts and rebuild cached sessions."""
        for key, (session, cs_dict, _old_identity) in list(self._session_cache.items()):
            _client, _ = key
            cs = ClientSettings.model_validate(cs_dict)
            # Rebuilds read live OCI state; the old identity would file the
            # new graph under stale metadata and let a rollback re-match it.
            new_identity = self._build_identity(cs_dict)
            new_session: Optional[SessionType] = None
            if isinstance(session, CombinedSession):
                new_session = await self._build_combined_session(cs, client=_client)
            elif isinstance(session, NL2SQLGraphSession):
                new_session = await self._build_nl2sql_agent_session(cs, client=_client)
            elif isinstance(session, AgentGraphSession):
                new_session = await self._build_agent_session(cs)
            elif isinstance(session, GraphFlowSession):
                new_session = await self._build_flow_session(cs)
            if new_session is not None and key in self._session_cache:
                self._session_cache[key] = (new_session, cs_dict, new_identity)

    # -- history feed ------------------------------------------------------

    def _replayable_entries(self, client: str) -> list:
        """``HistoryStore`` entries safe to feed back into the LLM.

        Skips turns stamped ``history_enabled=False`` so a session that
        chats with chat_history off and later toggles it on doesn't
        resurface the off-turn as context.
        """
        return [
            e for e in self.history.get(client)
            if e.get("history_enabled", True) and e.get("role") in ("user", "assistant")
        ]

    def _history_text(self, client: str, cs: Any) -> str:
        """``HistoryStore`` rendered as ``"User: q\\nAssistant: a\\n..."``."""
        if not cs.ll_model.chat_history:
            return ""
        return format_history_text(self._replayable_entries(client))

    def _history_messages(self, client: str, cs: Any) -> list:
        """``HistoryStore`` rendered as LangChain ``HumanMessage``/``AIMessage``."""
        if not cs.ll_model.chat_history:
            return []
        messages: list[Any] = []
        for entry in self._replayable_entries(client):
            content = entry.get("content", "")
            if entry["role"] == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))
        return messages

    # -- execute_chat (non-streaming) -------------------------------------

    async def execute_chat(
        self,
        question: str,
        client: str,
    ) -> Dict[str, Any]:
        """Execute a non-streaming chat and return result with metadata."""
        session, route = await self._get_or_create_session(client)

        cs = self._resolve_client(client)
        if isinstance(session, CombinedSession):
            answer = await session.execute(
                question,
                thread_id=client,
                history_text=self._history_text(client, cs),
                history_messages=self._history_messages(client, cs),
            )
        elif isinstance(session, AgentGraphSession):
            answer = await session.chat(question, history_messages=self._history_messages(client, cs))
        else:
            answer = await session.execute(question, thread_id=client, history_text=self._history_text(client, cs))

        vs_metadata = None
        token_usage = None
        if isinstance(session, (CombinedSession, GraphFlowSession)):
            vs_metadata = session.last_metadata.vs_metadata
            token_usage = session.last_metadata.token_usage
        elif isinstance(session, AgentGraphSession):
            token_usage = session.last_metadata.token_usage
        vs_meta_dict = vs_metadata.model_dump(exclude_none=True) if vs_metadata else None
        tu_dict = token_usage.model_dump() if token_usage else None
        extras = {k: v for k, v in [("vs_metadata", vs_meta_dict), ("token_usage", tu_dict)] if v}

        history_enabled = cs.ll_model.chat_history
        self.history.append(client, "user", question, history_enabled=history_enabled)
        self.history.append(client, "assistant", answer, history_enabled=history_enabled, **extras)

        return {"result": answer, "route": route, "vs_metadata": vs_metadata, "token_usage": token_usage}

    # -- execute_chat_stream (streaming) ----------------------------------

    async def _run_flow_streaming(
        self,
        session: GraphFlowSession,
        route: Route,
        question: str,
        client: str,
        queue: asyncio.Queue,
        history_text: str = "",
    ) -> None:
        """Run a flow session with token-by-token streaming via ``astream_events``."""
        LOGGER.debug("Token streaming against route: %s", route)
        await session.execute(question, thread_id=client, history_text=history_text, queue=queue)
        token_usage = session.last_metadata.token_usage
        if token_usage:
            await queue.put({"type": "_token_usage", **token_usage.model_dump()})

    async def _run_agent_streaming(
        self,
        session: AgentGraphSession,
        history_messages: list,
        question: str,
        queue: asyncio.Queue,
    ) -> None:
        """Run an agent session with token-by-token streaming via ``astream_events``."""
        await session.chat(question, history_messages=history_messages, queue=queue)
        token_usage = session.last_metadata.token_usage
        if token_usage:
            await queue.put({"type": "_token_usage", **token_usage.model_dump()})

    def _get_agent_token_usage(self, session: Any) -> Optional[TokenUsage]:
        """Return token usage from an agent session's last metadata."""
        return session.last_metadata.token_usage
