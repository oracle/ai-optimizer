"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Chat orchestration — routing, session management, memory, and streaming.

Provides the same public API as the deleted ``server.app.agents.runtime``
and ``server.app.agents.memory`` modules.  All external dependencies
(settings, client resolution) are injected via ``ChatOrchestrator.__init__``.
"""
# spell-checker: ignore litellm vecsearch wayflow agentspec

import asyncio
import logging
from typing import Any, Dict, Optional, Union

from server.app.agentspec.agent_llm_only import DEFAULT_INSTRUCTION as DEFAULT_LLM_ONLY_INSTRUCTION
from server.app.agentspec.agent_nl2sql import DEFAULT_NL2SQL_INSTRUCTION
from server.app.core.schemas import ClientSettings
from server.app.models.litellm_utils import find_model
from server.app.runtime.common import (
    ROUTE_PROMPTS,
    BaseChatOrchestrator,
    TokenUsage,
    fetch_prompt_for_route,
    resolve_route,
)
from server.app.runtime.wayflow.adapters.litellm import LiteLlmModel
from server.app.runtime.wayflow.adapters.streaming import (
    STREAMING_STEPS,
    StreamingLiteLlmModel,
    swap_llm_for_streaming,
)
from server.app.runtime.wayflow.llm_only import PROMPT_NAME as LLM_ONLY_PROMPT
from server.app.runtime.wayflow.llm_only import AgentChatSession, build_llm_only_agent
from server.app.runtime.wayflow.multi_tool import (
    DEFAULT_COMBINED_INSTRUCTION,
    CombinedSession,
)
from server.app.runtime.wayflow.multi_tool import (
    PROMPT_NAME as COMBINED_PROMPT,
)
from server.app.runtime.wayflow.nl2sql import (
    PROMPT_NAME as NL2SQL_PROMPT,
)
from server.app.runtime.wayflow.nl2sql import (
    NL2SQLAgentSession,
    build_nl2sql_agent,
)
from server.app.runtime.wayflow.session import FlowSession, _extract_agent_token_usage, update_agent_state
from server.app.runtime.wayflow.vecsearch import (
    DEFAULT_VECSEARCH_INSTRUCTION,
    VecSearchFlowSession,
    build_vecsearch_runtime_flow,
)
from server.app.runtime.wayflow.vecsearch import (
    PROMPT_NAME as VECSEARCH_PROMPT,
)

LOGGER = logging.getLogger(__name__)

SessionType = Union[FlowSession, AgentChatSession, CombinedSession]

_SESSION_BUILDERS = {
    "vecsearch": (build_vecsearch_runtime_flow, VecSearchFlowSession),
}

# Populate shared route prompts for this runtime.
ROUTE_PROMPTS.update(
    {
        "llm_only": (LLM_ONLY_PROMPT, DEFAULT_LLM_ONLY_INSTRUCTION),
        "nl2sql": (NL2SQL_PROMPT, DEFAULT_NL2SQL_INSTRUCTION),
        "vecsearch": (VECSEARCH_PROMPT, DEFAULT_VECSEARCH_INSTRUCTION),
        "combined": (COMBINED_PROMPT, DEFAULT_COMBINED_INSTRUCTION),
    }
)


# ---------------------------------------------------------------------------
# ChatOrchestrator
# ---------------------------------------------------------------------------


class ChatOrchestrator(BaseChatOrchestrator):
    """Stateful chat orchestrator with session caching and streaming.

    Parameters
    ----------
    server_url:
        Full URL to the MCP endpoint (e.g. ``"http://127.0.0.1:8000/mcp"``).
    api_key:
        API key for the MCP server, or a callable returning the current key.
    resolve_client:
        Callable that takes a client name and returns a ``ClientSettings``
        pydantic model (must have ``.ll_model``, ``.tools_enabled``, and
        ``.model_dump()``).
    """

    _agent_session_type = AgentChatSession
    _combined_session_type = CombinedSession
    _flow_session_type = FlowSession
    _nl2sql_session_type = NL2SQLAgentSession

    # -- session factory ---------------------------------------------------

    async def _build_flow_session(self, cs: ClientSettings, route: str) -> FlowSession:
        """Build a flow session from client settings."""
        build_fn, session_cls = _SESSION_BUILDERS[route]
        flow = await build_fn(cs, self._server_url, self.api_key)
        return session_cls(flow, cs)

    async def _build_agent_session(self, cs: ClientSettings) -> AgentChatSession:
        """Build an LLM-only agent session from client settings."""
        agent = await build_llm_only_agent(cs, self._server_url, self.api_key)
        return AgentChatSession(agent)

    async def _build_nl2sql_agent_session(self, cs: ClientSettings, client: str = "") -> NL2SQLAgentSession:
        """Build an NL2SQL agent session from client settings."""
        agent = await build_nl2sql_agent(cs, self._server_url, self.api_key)
        return NL2SQLAgentSession(agent, cs, thread_id=client)

    async def _build_combined_session(self, cs: ClientSettings, client: str = "") -> CombinedSession:
        """Build a CombinedSession from a VecSearch flow + NL2SQL agent."""
        vs_flow = await build_vecsearch_runtime_flow(cs, self._server_url, self.api_key)
        vs_session = VecSearchFlowSession(vs_flow, cs)

        nl2sql_agent = await build_nl2sql_agent(cs, self._server_url, self.api_key)
        nl2sql_session = NL2SQLAgentSession(nl2sql_agent, cs, thread_id=client)

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
            api_key=model_cfg.api_key if model_cfg else None,
            api_base=model_cfg.api_base if model_cfg else None,
        )

    async def _build_session(self, cs: ClientSettings, route: str, client: str = "") -> SessionType:
        """Dispatch to the appropriate session builder for the given route."""
        if route == "llm_only":
            return await self._build_agent_session(cs)
        if route == "nl2sql":
            return await self._build_nl2sql_agent_session(cs, client=client)
        if route == "combined":
            return await self._build_combined_session(cs, client=client)
        return await self._build_flow_session(cs, route)

    # -- session cache (non-streaming) ------------------------------------

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
            # Re-check after acquiring lock
            cached = self._session_cache.get(key)
            if cached is not None and self._build_identity(cached[1]) == identity:
                return cached[0], route
            # Capture history from the old session before rebuilding.
            old_session = cached[0] if cached is not None else None
            session = await self._build_session(cs, route, client=client)
            if old_session is not None:
                if isinstance(session, FlowSession) and isinstance(old_session, FlowSession):
                    session.history = old_session.history
                elif isinstance(session, AgentChatSession) and isinstance(old_session, AgentChatSession):
                    old_messages = old_session.conversation.message_list
                    session.conversation = session.agent.start_conversation(
                        messages=old_messages,
                        conversation_id=old_session.conversation_id,
                    )
                elif isinstance(session, CombinedSession) and isinstance(old_session, CombinedSession):
                    # Preserve history in both sub-sessions
                    session.vs_session.history = old_session.vs_session.history
                    old_nl2sql_msgs = old_session.nl2sql_session.conversation.message_list
                    session.nl2sql_session.conversation = session.nl2sql_session.agent.start_conversation(
                        messages=old_nl2sql_msgs,
                        conversation_id=old_session.nl2sql_session.conversation_id,
                    )
            self._session_cache[key] = (session, cs_dict)
        return session, route

    async def refresh_prompts(self) -> None:
        """Re-fetch prompts and update cached sessions in-place.

        For agent sessions the ``custom_instruction`` is patched directly.
        For NL2SQL agent sessions the session is rebuilt (to re-apply
        connection context on top of the new prompt).
        For flow sessions the flow is rebuilt with the new prompt and the
        conversation history string is carried over.
        For combined sessions both sub-sessions are rebuilt.
        """
        for key, (session, cs_dict) in list(self._session_cache.items()):
            _client, route = key
            cs = ClientSettings.model_validate(cs_dict)
            if isinstance(session, CombinedSession):
                # Rebuild both sub-sessions
                new_session = await self._build_combined_session(cs, client=_client)
                new_session.vs_session.history = session.vs_session.history
                old_nl2sql_msgs = session.nl2sql_session.conversation.message_list
                new_session.nl2sql_session.conversation = new_session.nl2sql_session.agent.start_conversation(
                    messages=old_nl2sql_msgs,
                    conversation_id=session.nl2sql_session.conversation_id,
                )
                if key in self._session_cache:
                    self._session_cache[key] = (new_session, cs_dict)
            elif isinstance(session, NL2SQLAgentSession):
                # Rebuild to re-apply connection context on the refreshed prompt.
                old_messages = session.conversation.message_list
                new_session = await self._build_nl2sql_agent_session(cs, client=_client)
                new_session.conversation = new_session.agent.start_conversation(
                    messages=old_messages,
                    conversation_id=session.conversation_id,
                )
                if key in self._session_cache:
                    self._session_cache[key] = (new_session, cs_dict)
            elif isinstance(session, AgentChatSession):
                prompt = await fetch_prompt_for_route(route, self._server_url, self.api_key)
                if prompt is not None and key in self._session_cache:
                    session.agent.custom_instruction = prompt
                    update_agent_state(session.agent)
            elif isinstance(session, FlowSession):
                saved_history = session.history
                new_session = await self._build_flow_session(cs, route)
                new_session.history = saved_history
                # Only write back if the session wasn't invalidated during rebuild.
                if key in self._session_cache:
                    self._session_cache[key] = (new_session, cs_dict)

    # -- execute_chat (non-streaming) -------------------------------------

    async def execute_chat(
        self,
        question: str,
        client: str,
    ) -> Dict[str, Any]:
        """Execute a non-streaming chat.

        Returns ``{"result": str, "route": str, "vs_metadata": ...}``.
        """
        session, route = await self._get_or_create_session(client)

        cs = self._resolve_client(client)
        use_history = cs.ll_model.chat_history
        if isinstance(session, CombinedSession):
            answer = await session.execute(question, thread_id=client, chat_history=use_history)
        elif isinstance(session, AgentChatSession):
            answer = await session.chat(question, chat_history=use_history)
        else:
            answer = await session.execute(question, thread_id=client, chat_history=use_history)

        vs_metadata = None
        token_usage = None
        if isinstance(session, (CombinedSession, FlowSession)):
            vs_metadata = session.last_metadata.vs_metadata
            token_usage = session.last_metadata.token_usage
        elif isinstance(session, AgentChatSession):
            token_usage = _extract_agent_token_usage(session)
        vs_meta_dict = vs_metadata.model_dump(exclude_none=True) if vs_metadata else None
        tu_dict = token_usage.model_dump() if token_usage else None
        extras = {k: v for k, v in [("vs_metadata", vs_meta_dict), ("token_usage", tu_dict)] if v}

        self.history.append(client, "user", question)
        self.history.append(client, "assistant", answer, **extras)

        return {"result": answer, "route": route, "vs_metadata": vs_metadata, "token_usage": token_usage}

    # -- execute_chat_stream (streaming) ----------------------------------

    async def _run_flow_streaming(
        self,
        session: FlowSession,
        route: str,
        question: str,
        client: str,
        queue: asyncio.Queue,
        chat_history: bool = True,
    ) -> None:
        """Run a flow session with streaming."""
        step_names = STREAMING_STEPS.get(route, [])
        originals = swap_llm_for_streaming(session.flow, queue, step_names)
        try:
            result = await session.execute(question, thread_id=client, chat_history=chat_history)
            any_streamed = any(getattr(step.llm, "streamed_text", False) for step, _ in originals)
            if not any_streamed and result:
                await queue.put({"type": "stream", "content": result})
        finally:
            # Restore original LLMs so the cached session is clean for next call
            for step, original_llm in originals:
                step.llm = original_llm

    async def _run_agent_streaming(
        self,
        session: AgentChatSession,
        use_history: bool,
        question: str,
        queue: asyncio.Queue,
    ) -> None:
        """Run an agent session with streaming."""
        agent = session.agent
        original_llm = None
        streaming_llm = None
        if hasattr(agent, "llm") and isinstance(agent.llm, LiteLlmModel):
            original_llm = agent.llm
            streaming_llm = StreamingLiteLlmModel(agent.llm, queue)
            agent.llm = streaming_llm
        try:
            result = await session.chat(question, chat_history=use_history)
            any_streamed = getattr(streaming_llm, "streamed_text", False)
            if not any_streamed and result:
                await queue.put({"type": "stream", "content": result})
        finally:
            if original_llm is not None:
                agent.llm = original_llm

    def _get_agent_token_usage(self, session: Any) -> Optional[TokenUsage]:
        """Return cumulative token usage from an agent session."""
        return _extract_agent_token_usage(session)
