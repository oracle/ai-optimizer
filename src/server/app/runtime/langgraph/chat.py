"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LangGraph chat orchestration — routing, session management, memory, and streaming.
"""
# spell-checker: ignore checkpointer vecsearch agentspec astream litellm

import asyncio
import logging
from collections import defaultdict
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, Optional, Union

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from server.app.agentspec.adapters.mcp import connect_sqlcl_database
from server.app.api.v1.schemas.chat import SqlMetadata, TokenUsage, VsMetadata
from server.app.core.schemas import ClientSettings
from server.app.core.secrets import reveal
from server.app.database.config import resolve_effective_tool_alias
from server.app.mcp.prompts.registry import require_factory_text
from server.app.models.litellm_utils import build_oci_litellm_params, find_model
from server.app.oci.registry import find_oci_profile_by_name
from server.app.runtime.common import (
    CLASSIFIER_PROMPT_NAME,
    ROUTE_PROMPTS,
    SYNTHESIS_PROMPT_NAME,
    HistoryStore,
    LLMConfigurationError,
    Route,
    clean_llm_error,
    fetch_prompt_for_route,
    fetch_prompt_with_fallback,
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


class ChatOrchestrator:
    """Stateful chat orchestrator for the LangGraph runtime."""

    def __init__(
        self,
        server_url: str,
        api_key: Union[str, Callable[[], str]],
        resolve_client: Callable[[str], Any],
    ) -> None:
        self._server_url = server_url
        self._api_key = api_key
        self._resolve_client = resolve_client
        self._session_cache: Dict[tuple, tuple[Any, Dict[str, Any], Dict[str, Any]]] = {}
        self._build_lock = asyncio.Lock()
        self._stream_locks: Dict[tuple, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.history = HistoryStore()

    @property
    def api_key(self) -> str:
        """Return the current API key, invoking the callable if needed."""
        return self._api_key() if callable(self._api_key) else self._api_key

    @staticmethod
    def _validate_llm(cs: Any) -> None:
        """Raise LLMConfigurationError if provider or model ID is missing."""
        if cs.ll_model.provider is None or cs.ll_model.id is None:
            raise LLMConfigurationError(
                "No language model configured. Set a provider and model ID in client settings."
            )

    @staticmethod
    def _build_identity(cs_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Build a cache-identity dict from settings, excluding chat_history.

        For OCI providers, the resolved profile is folded in — every field
        ``build_oci_litellm_params`` consumes — so a credential rotation,
        auth-mode switch, or compartment/region change invalidates the
        cached graph instead of leaving stale ``model_kwargs`` baked in.
        The profile is resolved by the cached client's ``oci.auth_profile``,
        not by whatever CONFIGURED currently points at, so per-client OCI
        pinning is honoured.
        """
        out = cs_dict.copy()
        ll = out.get("ll_model")
        if isinstance(ll, dict):
            out["ll_model"] = {k: v for k, v in ll.items() if k != "chat_history"}
            if ll.get("provider") == "oci":
                oci_section = out.get("oci")
                profile_name = oci_section.get("auth_profile") if isinstance(oci_section, dict) else None
                profile = find_oci_profile_by_name(profile_name)
                out["_oci_resolved"] = (
                    {
                        "auth_profile": profile.auth_profile,
                        "authentication": profile.authentication,
                        "tenancy": profile.tenancy,
                        "user": profile.user,
                        "fingerprint": profile.fingerprint,
                        "key_file": profile.key_file,
                        "genai_compartment_id": profile.genai_compartment_id,
                        "genai_region": profile.genai_region,
                    }
                    if profile is not None
                    else {"auth_profile": profile_name, "resolved": False}
                )
        return out

    def _build_nl2sql_database_connector(
        self, connection_name: str, model: str, thread_id: str
    ) -> Optional[Callable[[], Awaitable[None]]]:
        """Create a per-session connector for the configured SQLcl database."""
        if not connection_name:
            return None

        async def _connect() -> None:
            await connect_sqlcl_database(
                self._server_url,
                self.api_key,
                connection_name,
                model,
                thread_id=thread_id,
            )

        return _connect

    def _keys_for_client(self, client: str) -> list:
        """Return cache keys whose first element is *client*."""
        return [k for k in self._session_cache if k[0] == client]

    def invalidate_session(self, client: str) -> None:
        """Remove all cached sessions for the given client."""
        for k in self._keys_for_client(client):
            del self._session_cache[k]
            self._stream_locks.pop(k, None)

    def clear_history(self, client: str) -> None:
        """Clear conversation history and invalidate sessions for a client."""
        self.history.clear(client)
        self.invalidate_session(client)

    async def _fetch_validated_prompt(
        self,
        prompt_name: str,
        validate: Callable[[str], bool],
    ) -> str:
        """Fetch *prompt_name* from MCP; fall back to the factory entry
        (mcp/prompts/defaults.py) if fetch fails or *validate* rejects."""
        text = await fetch_prompt_with_fallback(self._server_url, self.api_key, prompt_name)
        if not validate(text):
            LOGGER.warning("Prompt %r failed structural validation; using factory default", prompt_name)
            return require_factory_text(prompt_name)
        return text

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
        # Resolve the effective tool alias with the real client id so a Deep Data Security
        # 'connect as' override routes NL2SQL to the end-user connection (and raises
        # DdsConnectionError, surfaced at the chat boundary, when it is unusable).
        connection_name = resolve_effective_tool_alias(client) if client else cs.database.alias
        ll_model = cs.ll_model
        assert ll_model.provider is not None
        assert ll_model.id is not None
        model = f"{ll_model.provider}/{ll_model.id}"
        connect_database = self._build_nl2sql_database_connector(connection_name, model, client)
        graph = await build_nl2sql_graph(cs, self._server_url, self.api_key, checkpointer=MemorySaver())
        return NL2SQLGraphSession(
            graph,
            cs,
            thread_id=client,
            connection_name=connection_name,
            connect_database=connect_database,
        )

    async def _build_combined_session(self, cs: ClientSettings, client: str = "") -> CombinedSession:
        """Build a combined vecsearch + NL2SQL session from client settings."""
        graph = await build_vecsearch_graph(cs, self._server_url, self.api_key)
        vs_session = GraphFlowSession(graph, cs)

        connection_name = resolve_effective_tool_alias(client) if client else cs.database.alias
        ll_model = cs.ll_model
        assert ll_model.provider is not None
        assert ll_model.id is not None
        model = f"{ll_model.provider}/{ll_model.id}"
        connect_database = self._build_nl2sql_database_connector(connection_name, model, client)
        nl2sql_graph = await build_nl2sql_graph(cs, self._server_url, self.api_key, checkpointer=MemorySaver())
        nl2sql_session = NL2SQLGraphSession(
            nl2sql_graph,
            cs,
            thread_id=client,
            connection_name=connection_name,
            connect_database=connect_database,
        )

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
        sql_metadata = None
        token_usage = None
        if isinstance(session, (CombinedSession, GraphFlowSession)):
            vs_metadata = session.last_metadata.vs_metadata
            sql_metadata = session.last_metadata.sql_metadata
            token_usage = session.last_metadata.token_usage
        elif isinstance(session, AgentGraphSession):
            sql_metadata = session.last_metadata.sql_metadata
            token_usage = session.last_metadata.token_usage
        vs_meta_dict = vs_metadata.model_dump(exclude_none=True) if vs_metadata else None
        sql_meta_dict = sql_metadata.model_dump(exclude_none=True) if sql_metadata else None
        tu_dict = token_usage.model_dump() if token_usage else None
        extras = {
            k: v
            for k, v in [
                ("vs_metadata", vs_meta_dict),
                ("sql_metadata", sql_meta_dict),
                ("token_usage", tu_dict),
            ]
            if v
        }

        history_enabled = cs.ll_model.chat_history
        self.history.append(client, "user", question, history_enabled=history_enabled)
        self.history.append(client, "assistant", answer, history_enabled=history_enabled, **extras)

        return {
            "result": answer,
            "route": route,
            "vs_metadata": vs_metadata,
            "sql_metadata": sql_metadata,
            "token_usage": token_usage,
        }

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

    # -- shared streaming pipeline -----------------------------------------

    async def _run_combined_streaming(
        self,
        session: CombinedSession,
        history_text: str,
        history_messages: list,
        question: str,
        client: str,
        queue: asyncio.Queue,
    ) -> None:
        """Run a combined session with streaming, delegating to sub-sessions."""
        await session.execute_streaming(
            query=question,
            thread_id=client,
            history_text=history_text,
            history_messages=history_messages,
            queue=queue,
            stream_flow=self._run_flow_streaming,
            stream_agent=self._run_agent_streaming,
        )

    def _create_streaming_task(
        self,
        session: Any,
        route: Route,
        cs: Any,
        question: str,
        client: str,
        queue: asyncio.Queue,
    ) -> asyncio.Task:
        """Create an asyncio task for the appropriate streaming handler.

        Each route reads only the history representation it consumes, so a
        long conversation doesn't pay to build both forms every turn.
        """
        if isinstance(session, CombinedSession):
            return asyncio.create_task(
                self._run_combined_streaming(
                    session,
                    self._history_text(client, cs),
                    self._history_messages(client, cs),
                    question,
                    client,
                    queue,
                )
            )
        if isinstance(session, AgentGraphSession):
            return asyncio.create_task(
                self._run_agent_streaming(session, self._history_messages(client, cs), question, queue)
            )
        return asyncio.create_task(
            self._run_flow_streaming(
                session, route, question, client, queue, history_text=self._history_text(client, cs)
            )
        )

    @staticmethod
    def _accumulate_token_usage(current: Optional[TokenUsage], event: Dict[str, Any]) -> TokenUsage:
        """Add token counts from an event into the running total."""
        if current is None:
            current = TokenUsage()
        current.prompt_tokens += event.get("prompt_tokens", 0)
        current.completion_tokens += event.get("completion_tokens", 0)
        current.total_tokens += event.get("total_tokens", 0)
        return current

    def _finalize_stream(
        self,
        session: Any,
        question: str,
        client: str,
        collected: list[str],
        token_usage: Optional[TokenUsage],
        route: Route,
        history_enabled: bool,
    ) -> Dict[str, Any]:
        """Persist history and return the final _meta event dict.

        *history_enabled* stamps each appended entry with the chat_history
        setting active for this turn, so turns taken with the toggle off
        are not later replayed when the toggle flips on.
        """
        answer = "".join(collected)
        vs_metadata: Optional[VsMetadata] = None
        sql_metadata: Optional[SqlMetadata] = None
        if isinstance(session, (CombinedSession, GraphFlowSession)):
            vs_metadata = session.last_metadata.vs_metadata
            sql_metadata = session.last_metadata.sql_metadata
        elif isinstance(session, AgentGraphSession):
            sql_metadata = session.last_metadata.sql_metadata
        if isinstance(session, AgentGraphSession) and not isinstance(session, NL2SQLGraphSession):
            token_usage = self._get_agent_token_usage(session) or token_usage
        if answer:
            # Convert to dicts for HistoryStore (consumed by chat/history endpoint)
            vs_meta_dict = vs_metadata.model_dump(exclude_none=True) if vs_metadata else None
            sql_meta_dict = sql_metadata.model_dump(exclude_none=True) if sql_metadata else None
            tu_dict = token_usage.model_dump() if token_usage else None
            extras = {
                k: v
                for k, v in [
                    ("vs_metadata", vs_meta_dict),
                    ("sql_metadata", sql_meta_dict),
                    ("token_usage", tu_dict),
                ]
                if v
            }
            self.history.append(client, "user", question, history_enabled=history_enabled)
            self.history.append(client, "assistant", answer, history_enabled=history_enabled, **extras)
        # Return dict for streaming event — endpoint consumes via event.get()
        vs_meta_dict = vs_metadata.model_dump(exclude_none=True) if vs_metadata else None
        sql_meta_dict = sql_metadata.model_dump(exclude_none=True) if sql_metadata else None
        return {"type": "_meta", "route": route, "vs_metadata": vs_meta_dict, "sql_metadata": sql_meta_dict}

    async def execute_chat_stream(
        self,
        question: str,
        client: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute a streaming chat, yielding event dicts as they arrive."""
        session, route = await self._get_or_create_session(client)
        queue: asyncio.Queue = asyncio.Queue()
        collected: list[str] = []
        token_usage: Optional[TokenUsage] = None

        async with self._stream_locks[(client, route)]:
            cs = self._resolve_client(client)
            task = self._create_streaming_task(session, route, cs, question, client, queue)

            try:
                while True:
                    if task.done() and queue.empty():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    if event.get("type") == "stream":
                        collected.append(event.get("content", ""))
                    elif event.get("type") == "_token_usage":
                        token_usage = self._accumulate_token_usage(token_usage, event)
                    yield event

                exc = task.exception()
                if exc is not None:
                    LOGGER.error("Streaming execution failed: %s", exc)
                    yield {"type": "error", "content": clean_llm_error(exc)}
                    return

            except Exception as exc:
                LOGGER.error("Stream consumer error: %s", exc)
                yield {"type": "error", "content": clean_llm_error(exc)}
                if not task.done():
                    task.cancel()
                return

        yield self._finalize_stream(session, question, client, collected, token_usage, route, cs.ll_model.chat_history)
