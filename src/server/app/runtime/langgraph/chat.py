"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LangGraph chat orchestration — routing, session management, memory, and streaming.
"""
# spell-checker: ignore checkpointer vecsearch agentspec astream litellm

import asyncio
import logging
from typing import Any, Dict, Optional, Union

from langgraph.checkpoint.memory import MemorySaver

from server.app.agentspec.agent_llm_only import DEFAULT_INSTRUCTION as DEFAULT_LLM_ONLY_INSTRUCTION
from server.app.agentspec.agent_nl2sql import DEFAULT_NL2SQL_INSTRUCTION
from server.app.api.v1.schemas.chat import TokenUsage
from server.app.core.schemas import ClientSettings
from server.app.core.secrets import reveal
from server.app.models.litellm_utils import find_model
from server.app.runtime.common import (
    ROUTE_PROMPTS,
    BaseChatOrchestrator,
    fetch_prompt_for_route,
    resolve_route,
)
from server.app.runtime.langgraph.llm_only import (
    PROMPT_NAME as LLM_ONLY_PROMPT,
)
from server.app.runtime.langgraph.llm_only import (
    build_llm_only_graph,
)
from server.app.runtime.langgraph.multi_tool import (
    DEFAULT_COMBINED_INSTRUCTION,
    CombinedSession,
)
from server.app.runtime.langgraph.multi_tool import (
    PROMPT_NAME as COMBINED_PROMPT,
)
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
    DEFAULT_VECSEARCH_INSTRUCTION,
    build_vecsearch_graph,
)
from server.app.runtime.langgraph.vecsearch import (
    PROMPT_NAME as VECSEARCH_PROMPT,
)

LOGGER = logging.getLogger(__name__)

SessionType = Union[GraphFlowSession, AgentGraphSession, CombinedSession]

# Populate shared route prompts.
ROUTE_PROMPTS.update(
    {
        "llm_only": (LLM_ONLY_PROMPT, DEFAULT_LLM_ONLY_INSTRUCTION),
        "nl2sql": (NL2SQL_PROMPT, DEFAULT_NL2SQL_INSTRUCTION),
        "vecsearch": (VECSEARCH_PROMPT, DEFAULT_VECSEARCH_INSTRUCTION),
        "combined": (COMBINED_PROMPT, DEFAULT_COMBINED_INSTRUCTION),
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

    async def _build_agent_session(self, cs: ClientSettings, checkpointer=None) -> AgentGraphSession:
        """Build an LLM-only agent session from client settings."""
        cp = checkpointer or MemorySaver()
        graph = await build_llm_only_graph(cs, self._server_url, self.api_key, checkpointer=cp)
        return AgentGraphSession(graph, checkpointer=cp)

    async def _build_nl2sql_agent_session(
        self, cs: ClientSettings, client: str = "", checkpointer=None
    ) -> NL2SQLGraphSession:
        """Build an NL2SQL agent session from client settings."""
        cp = checkpointer or MemorySaver()
        graph = await build_nl2sql_graph(cs, self._server_url, self.api_key, checkpointer=cp)
        return NL2SQLGraphSession(graph, cs, thread_id=client, checkpointer=cp)

    async def _build_combined_session(
        self, cs: ClientSettings, client: str = "", nl2sql_checkpointer=None
    ) -> CombinedSession:
        """Build a combined vecsearch + NL2SQL session from client settings."""
        graph = await build_vecsearch_graph(cs, self._server_url, self.api_key)
        vs_session = GraphFlowSession(graph, cs)

        nl2sql_cp = nl2sql_checkpointer or MemorySaver()
        nl2sql_graph = await build_nl2sql_graph(cs, self._server_url, self.api_key, checkpointer=nl2sql_cp)
        nl2sql_session = NL2SQLGraphSession(nl2sql_graph, cs, thread_id=client, checkpointer=nl2sql_cp)

        ll_model = cs.ll_model
        assert ll_model.provider is not None
        assert ll_model.id is not None
        classifier_model = f"{ll_model.provider}/{ll_model.id}"
        model_cfg = find_model(ll_model.provider, ll_model.id, enabled_only=False, case_insensitive=True)

        prompt = await fetch_prompt_for_route("combined", self._server_url, self.api_key)
        system_prompt = prompt or DEFAULT_COMBINED_INSTRUCTION

        return CombinedSession(
            vs_session,
            nl2sql_session,
            classifier_model,
            system_prompt,
            api_key=reveal(model_cfg.api_key) if model_cfg else None,
            api_base=model_cfg.api_base if model_cfg else None,
        )

    async def _build_session(
        self,
        cs: ClientSettings,
        route: str,
        client: str = "",
        checkpointer=None,
        nl2sql_checkpointer=None,
    ) -> SessionType:
        """Dispatch to the appropriate session builder for the given route."""
        if route == "llm_only":
            return await self._build_agent_session(cs, checkpointer=checkpointer)
        if route == "nl2sql":
            return await self._build_nl2sql_agent_session(cs, client=client, checkpointer=checkpointer)
        if route == "combined":
            return await self._build_combined_session(cs, client=client, nl2sql_checkpointer=nl2sql_checkpointer)
        return await self._build_flow_session(cs)

    # -- session cache -----------------------------------------------------

    async def _get_or_create_session(self, client: str) -> tuple[SessionType, str]:
        """Return a cached session or build a new one for the client."""
        cs = self._resolve_client(client)
        self._validate_llm(cs)
        route = resolve_route(cs.tools_enabled)
        key = (client, route)
        cs_dict = cs.model_dump()
        identity = self._build_identity(cs_dict)

        cached = self._session_cache.get(key)
        if cached is not None and self._build_identity(cached[1]) == identity:
            return cached[0], route

        async with self._build_lock:
            cached = self._session_cache.get(key)
            if cached is not None and self._build_identity(cached[1]) == identity:
                return cached[0], route
            old_session = cached[0] if cached is not None else None
            old_checkpointer = None
            old_nl2sql_checkpointer = None
            if old_session is not None:
                if isinstance(old_session, CombinedSession):
                    old_nl2sql_checkpointer = old_session.nl2sql_session.checkpointer
                elif isinstance(old_session, AgentGraphSession):
                    old_checkpointer = old_session.checkpointer
            session = await self._build_session(
                cs,
                route,
                client=client,
                checkpointer=old_checkpointer,
                nl2sql_checkpointer=old_nl2sql_checkpointer,
            )
            if old_session is not None:
                if isinstance(session, GraphFlowSession) and isinstance(old_session, GraphFlowSession):
                    session.history = old_session.history
                elif isinstance(session, AgentGraphSession) and isinstance(old_session, AgentGraphSession):
                    session.conversation_messages = old_session.conversation_messages
                    session.conversation_id = old_session.conversation_id
                elif isinstance(session, CombinedSession) and isinstance(old_session, CombinedSession):
                    session.vs_session.history = old_session.vs_session.history
                    session.nl2sql_session.conversation_messages = old_session.nl2sql_session.conversation_messages
                    session.nl2sql_session.conversation_id = old_session.nl2sql_session.conversation_id
            self._session_cache[key] = (session, cs_dict)
        return session, route

    async def refresh_prompts(self) -> None:
        """Re-fetch prompts and rebuild cached sessions."""
        for key, (session, cs_dict) in list(self._session_cache.items()):
            _client, _ = key
            cs = ClientSettings.model_validate(cs_dict)
            if isinstance(session, CombinedSession):
                new_session = await self._build_combined_session(
                    cs,
                    client=_client,
                    nl2sql_checkpointer=session.nl2sql_session.checkpointer,
                )
                new_session.vs_session.history = session.vs_session.history
                new_session.nl2sql_session.conversation_messages = session.nl2sql_session.conversation_messages
                new_session.nl2sql_session.conversation_id = session.nl2sql_session.conversation_id
                if key in self._session_cache:
                    self._session_cache[key] = (new_session, cs_dict)
            elif isinstance(session, NL2SQLGraphSession):
                old_msgs = session.conversation_messages
                new_session = await self._build_nl2sql_agent_session(
                    cs,
                    client=_client,
                    checkpointer=session.checkpointer,
                )
                new_session.conversation_messages = old_msgs
                if key in self._session_cache:
                    self._session_cache[key] = (new_session, cs_dict)
            elif isinstance(session, AgentGraphSession):
                old_msgs = session.conversation_messages
                new_session = await self._build_agent_session(cs, checkpointer=session.checkpointer)
                new_session.conversation_messages = old_msgs
                new_session.conversation_id = session.conversation_id
                if key in self._session_cache:
                    self._session_cache[key] = (new_session, cs_dict)
            elif isinstance(session, GraphFlowSession):
                saved_history = session.history
                new_session = await self._build_flow_session(cs)
                new_session.history = saved_history
                if key in self._session_cache:
                    self._session_cache[key] = (new_session, cs_dict)

    # -- execute_chat (non-streaming) -------------------------------------

    async def execute_chat(
        self,
        question: str,
        client: str,
    ) -> Dict[str, Any]:
        """Execute a non-streaming chat and return result with metadata."""
        session, route = await self._get_or_create_session(client)

        cs = self._resolve_client(client)
        use_history = cs.ll_model.chat_history
        if isinstance(session, CombinedSession):
            answer = await session.execute(question, thread_id=client, chat_history=use_history)
        elif isinstance(session, AgentGraphSession):
            answer = await session.chat(question, chat_history=use_history)
        else:
            answer = await session.execute(question, thread_id=client, chat_history=use_history)

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

        self.history.append(client, "user", question)
        self.history.append(client, "assistant", answer, **extras)

        return {"result": answer, "route": route, "vs_metadata": vs_metadata, "token_usage": token_usage}

    # -- execute_chat_stream (streaming) ----------------------------------

    async def _run_flow_streaming(
        self,
        session: GraphFlowSession,
        route: str,
        question: str,
        client: str,
        queue: asyncio.Queue,
        chat_history: bool = True,
    ) -> None:
        """Run a flow session with token-by-token streaming via ``astream_events``."""
        LOGGER.debug("Token streaming against route: %s", route)
        await session.execute(question, thread_id=client, chat_history=chat_history, queue=queue)
        token_usage = session.last_metadata.token_usage
        if token_usage:
            await queue.put({"type": "_token_usage", **token_usage.model_dump()})

    async def _run_agent_streaming(
        self,
        session: AgentGraphSession,
        use_history: bool,
        question: str,
        queue: asyncio.Queue,
    ) -> None:
        """Run an agent session with token-by-token streaming via ``astream_events``."""
        await session.chat(question, chat_history=use_history, queue=queue)
        token_usage = session.last_metadata.token_usage
        if token_usage:
            await queue.put({"type": "_token_usage", **token_usage.model_dump()})

    def _get_agent_token_usage(self, session: Any) -> Optional[TokenUsage]:
        """Return token usage from an agent session's last metadata."""
        return session.last_metadata.token_usage
