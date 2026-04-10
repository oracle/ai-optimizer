"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for chat orchestration.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.app.api.v1.schemas.chat import VsMetadata
from server.app.runtime.common import HistoryStore, LLMConfigurationError, SessionMetadata, resolve_route
from server.app.runtime.wayflow.chat import ChatOrchestrator
from server.app.runtime.wayflow.llm_only import AgentChatSession
from server.tests.runtime.chat_base import (
    ApiKeyLivenessBase,
    CacheBase,
    ExecuteChatBase,
    StreamBase,
)
from server.tests.runtime.shared_helpers import mock_client_settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(cs=None, **cs_kwargs):
    """Build a ChatOrchestrator with a mock resolve_client."""
    if cs is None:
        cs = mock_client_settings(**cs_kwargs)
    return ChatOrchestrator(
        server_url="http://127.0.0.1:8000/mcp",
        api_key="test-key",
        resolve_client=lambda _client: cs,
    )


class _WayFlowChatMixin:
    """Provides shared attributes for WayFlow ChatOrchestrator tests."""

    ChatOrchestratorClass = ChatOrchestrator
    LLMConfigurationError = LLMConfigurationError

    @staticmethod
    def make_orchestrator(**kwargs):
        """Create a WayFlow ChatOrchestrator for testing."""
        return _make_orchestrator(**kwargs)


# ---------------------------------------------------------------------------
# TestResolveRoute
# ---------------------------------------------------------------------------


class TestResolveRoute:
    """Tests for resolve_route."""

    def test_empty_tools(self):
        """Verify empty tools list routes to llm_only."""
        assert resolve_route([]) == "llm_only"

    def test_nl2sql_only(self):
        """Verify nl2sql tool routes to nl2sql."""
        assert resolve_route(["NL2SQL"]) == "nl2sql"

    def test_vecsearch_only(self):
        """Verify vecsearch tool routes to vecsearch."""
        assert resolve_route(["Vector Search"]) == "vecsearch"

    def test_both_tools(self):
        """Verify both tools route to combined."""
        assert resolve_route(["NL2SQL", "Vector Search"]) == "combined"

    def test_both_tools_reversed(self):
        """Verify reversed order still routes to combined."""
        assert resolve_route(["Vector Search", "NL2SQL"]) == "combined"

    def test_unknown_tools_ignored(self):
        """Verify unknown tools fall back to llm_only."""
        assert resolve_route(["something_else"]) == "llm_only"

    def test_nl2sql_with_unknown(self):
        """Verify nl2sql with unknown tool still routes to nl2sql."""
        assert resolve_route(["NL2SQL", "other"]) == "nl2sql"


# ---------------------------------------------------------------------------
# TestHistoryStore
# ---------------------------------------------------------------------------


class TestHistoryStore:
    """Tests for HistoryStore."""

    def test_get_empty(self):
        """Verify get returns empty list for unknown client."""
        store = HistoryStore()
        assert not store.get("unknown")

    def test_append_and_get(self):
        """Verify append stores messages and get retrieves them."""
        store = HistoryStore()
        store.append("c1", "user", "hello")
        store.append("c1", "assistant", "hi")
        history = store.get("c1")
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "hello"}
        assert history[1] == {"role": "assistant", "content": "hi"}

    def test_append_with_kwargs(self):
        """Verify extra kwargs are stored in the message dict."""
        store = HistoryStore()
        store.append(
            "c1",
            "assistant",
            "answer",
            token_usage={"total_tokens": 100},
            vs_metadata={"documents": []},
        )
        msg = store.get("c1")[0]
        assert msg["token_usage"] == {"total_tokens": 100}
        assert msg["vs_metadata"] == {"documents": []}

    def test_get_returns_copy(self):
        """Verify get returns a copy, not the internal list."""
        store = HistoryStore()
        store.append("c1", "user", "test")
        h1 = store.get("c1")
        h1.clear()
        assert len(store.get("c1")) == 1

    def test_clear(self):
        """Verify clear removes all messages for a client."""
        store = HistoryStore()
        store.append("c1", "user", "test")
        store.clear("c1")
        assert not store.get("c1")


# ---------------------------------------------------------------------------
# TestChatOrchestratorCache
# ---------------------------------------------------------------------------


class TestChatOrchestratorCache(_WayFlowChatMixin, CacheBase):
    """Tests for session caching and invalidation."""


# ---------------------------------------------------------------------------
# TestExecuteChat
# ---------------------------------------------------------------------------


class TestExecuteChat(_WayFlowChatMixin, ExecuteChatBase):
    """Tests for ChatOrchestrator.execute_chat."""

    def _mock_llm_session(self):
        """Create a mock LLM session."""
        session = MagicMock(spec=AgentChatSession)
        session.chat = AsyncMock(return_value="hello back")
        session.last_metadata = SessionMetadata()
        return session

    @pytest.mark.anyio
    async def test_nl2sql_route(self):
        """Verify NL2SQL route calls FlowSession.execute."""
        orch = _make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value="sql result")

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            result = await orch.execute_chat("show tables", "test_client")

        assert result["result"] == "sql result"
        assert result["route"] == "nl2sql"

    @pytest.mark.anyio
    async def test_session_cached(self):
        """Verify second call reuses cached session."""
        orch = _make_orchestrator()
        mock_session = MagicMock(spec=AgentChatSession)
        mock_session.chat = AsyncMock(return_value="cached")

        build_mock = AsyncMock(return_value=mock_session)

        with patch.object(orch, "_build_session", build_mock):
            await orch.execute_chat("q1", "c1")
            await orch.execute_chat("q2", "c1")

        assert build_mock.await_count == 1

    def _mock_settings_change_session(self):
        session = MagicMock(spec=AgentChatSession)
        session.chat = AsyncMock(return_value="reply")
        mock_agent = MagicMock()
        mock_agent.start_conversation = MagicMock(return_value=MagicMock())
        session.agent = mock_agent
        session._conversation = MagicMock()
        session._conversation.message_list = MagicMock()
        session.conversation_id = "test-conv"
        return session


# ---------------------------------------------------------------------------
# TestExecuteChatStream
# ---------------------------------------------------------------------------


class TestExecuteChatStream(_WayFlowChatMixin, StreamBase):
    """Tests for ChatOrchestrator.execute_chat_stream."""

    def _mock_agent_session(self):
        """Create a mock agent session."""
        session = MagicMock(spec=AgentChatSession)
        session.agent = MagicMock()
        session.agent.llm = MagicMock()  # not LiteLlmModel
        session.last_metadata = SessionMetadata()
        return session

    def _mock_combined_session(self):
        """Create a mock combined session."""
        from server.app.runtime.wayflow.multi_tool import CombinedSession

        session = MagicMock(spec=CombinedSession)
        session.last_metadata = SessionMetadata()
        return session

    def _mock_cached_stream_session(self):
        """Create a mock cached stream session."""
        session = MagicMock()
        session.execute = AsyncMock(return_value="answer")
        session.flow = MagicMock()
        session.flow.steps = {}
        session.chat = AsyncMock(return_value="answer")
        session.last_metadata = SessionMetadata()
        return session

    def _mock_vs_metadata_session(self):
        """Create a mock vs metadata session."""
        from server.app.runtime.wayflow.session import FlowSession

        session = MagicMock(spec=FlowSession)
        session.execute = AsyncMock(return_value="answer")
        session.flow = MagicMock()
        session.flow.steps = {}
        session.last_metadata = SessionMetadata(
            vs_metadata=VsMetadata(documents=[{"searched_tables": ["t1"]}]),
        )
        return session

    @pytest.mark.anyio
    async def test_streaming_restores_llm_after_execution(self):
        """Verify swapped LLMs are restored after streaming completes."""
        from server.app.runtime.wayflow.adapters.litellm import LiteLlmModel

        orch = _make_orchestrator(tools_enabled=["NL2SQL"])

        original_llm = MagicMock(spec=LiteLlmModel)
        step = MagicMock()
        step.llm = original_llm

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value="answer")
        mock_session.flow = MagicMock()
        mock_session.flow.steps = {"format_answer": step}

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            async for _ in orch.execute_chat_stream("q", "c1"):
                pass

        # After streaming completes, the original LLM should be restored
        assert step.llm is original_llm

    @pytest.mark.anyio
    async def test_fallback_text_surfaced_when_no_chunks(self):
        """Verify fallback error text is enqueued when execution pushes no chunks."""
        orch = _make_orchestrator(tools_enabled=["NL2SQL"])

        async def silent_run(_self, _cs_dict, _route, _question, _client, queue, **_kwargs):
            # Simulates session.execute returning fallback text without pushing chunks
            await queue.put({"type": "stream", "content": "An error occurred"})

        with patch.object(ChatOrchestrator, "_run_flow_streaming", silent_run):
            events = []
            async for event in orch.execute_chat_stream("test", "c1"):
                events.append(event)

        stream_events = [e for e in events if e["type"] == "stream"]
        assert len(stream_events) == 1
        assert "error occurred" in stream_events[0]["content"]

    @pytest.mark.anyio
    async def test_fallback_fires_when_only_token_usage_in_queue(self):
        """Verify fallback fires when queue has _token_usage but no stream events."""
        orch = _make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = MagicMock(spec=AgentChatSession)
        mock_session.agent = MagicMock()
        mock_session.agent.llm = MagicMock()

        async def run_with_usage_only(_self, _session, _use_history, _question, queue):
            await queue.put(
                {
                    "type": "_token_usage",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                }
            )
            await queue.put({"type": "stream", "content": "fallback answer"})

        with (
            patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session),
            patch.object(ChatOrchestrator, "_run_agent_streaming", run_with_usage_only),
        ):
            events = []
            async for event in orch.execute_chat_stream("test", "c1"):
                events.append(event)

        stream_events = [e for e in events if e["type"] == "stream"]
        assert len(stream_events) == 1
        assert stream_events[0]["content"] == "fallback answer"

    @pytest.mark.anyio
    async def test_execute_chat_returns_vs_metadata(self):
        """Verify execute_chat returns vs_metadata from flow session."""
        from server.app.runtime.wayflow.session import FlowSession

        orch = _make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = MagicMock(spec=FlowSession)
        mock_session.execute = AsyncMock(return_value="result")
        mock_session.last_metadata = SessionMetadata(
            vs_metadata=VsMetadata(documents=[{"num_documents": 3}]),
        )

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            result = await orch.execute_chat("test", "c1")

        assert result["vs_metadata"] == VsMetadata(documents=[{"num_documents": 3}])

    @pytest.mark.anyio
    async def test_execute_chat_returns_token_usage(self):
        """Verify execute_chat returns token_usage from flow session."""
        from server.app.api.v1.schemas.chat import TokenUsage as _TokenUsage
        from server.app.runtime.wayflow.session import FlowSession

        orch = _make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = MagicMock(spec=FlowSession)
        mock_session.execute = AsyncMock(return_value="result")
        mock_session.last_metadata = SessionMetadata(
            token_usage=_TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        )

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            result = await orch.execute_chat("test", "c1")

        assert result["token_usage"] == _TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)


# ---------------------------------------------------------------------------
# TestHistoryMetadataPersistence
# ---------------------------------------------------------------------------


class TestHistoryMetadataPersistence:
    """Tests for vs_metadata and token_usage persistence in chat history."""

    @pytest.mark.anyio
    async def test_execute_chat_stores_vs_metadata_in_history(self):
        """Verify execute_chat persists vs_metadata in the assistant history entry."""
        from server.app.runtime.wayflow.session import FlowSession

        orch = _make_orchestrator(tools_enabled=["Vector Search"])
        mock_session = MagicMock(spec=FlowSession)
        mock_session.execute = AsyncMock(return_value="search result")
        mock_session.last_metadata = SessionMetadata(
            vs_metadata=VsMetadata(documents=[{"page_content": "x"}]),
        )

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            await orch.execute_chat("find docs", "c1")

        history = orch.history.get("c1")
        assert len(history) == 2
        assert history[1]["vs_metadata"]["documents"] == [{"page_content": "x"}]

    @pytest.mark.anyio
    async def test_execute_chat_stores_token_usage_in_history(self):
        """Verify execute_chat persists token_usage in the assistant history entry."""
        from server.app.api.v1.schemas.chat import TokenUsage as _TokenUsage
        from server.app.runtime.wayflow.session import FlowSession

        orch = _make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = MagicMock(spec=FlowSession)
        mock_session.execute = AsyncMock(return_value="answer")
        mock_session.last_metadata = SessionMetadata(
            token_usage=_TokenUsage(prompt_tokens=15, completion_tokens=8, total_tokens=23),
        )

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            await orch.execute_chat("question", "c1")

        history = orch.history.get("c1")
        assert len(history) == 2
        assert history[1]["token_usage"] == {"prompt_tokens": 15, "completion_tokens": 8, "total_tokens": 23}

    @pytest.mark.anyio
    async def test_execute_chat_no_metadata_for_llm_only(self):
        """Verify LLM-only history entries have no metadata keys."""
        orch = _make_orchestrator()
        mock_session = MagicMock(spec=AgentChatSession)
        mock_session.chat = AsyncMock(return_value="hello")

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            await orch.execute_chat("hi", "c1")

        assistant_msg = orch.history.get("c1")[1]
        assert "vs_metadata" not in assistant_msg
        assert "token_usage" not in assistant_msg

    @pytest.mark.anyio
    async def test_stream_stores_vs_metadata_and_token_usage_in_history(self):
        """Verify execute_chat_stream persists both vs_metadata and token_usage."""
        from server.app.runtime.wayflow.session import FlowSession

        orch = _make_orchestrator(tools_enabled=["Vector Search"])
        mock_session = MagicMock(spec=FlowSession)
        mock_session.execute = AsyncMock(return_value="answer")
        mock_session.flow = MagicMock()
        mock_session.flow.steps = {}
        mock_session.last_metadata = SessionMetadata(
            vs_metadata=VsMetadata(documents=[{"page_content": "doc"}]),
        )

        async def fake_run(_self, _session, _route, _question, _client, queue, **_kwargs):
            await queue.put({"type": "stream", "content": "streamed "})
            await queue.put({"type": "stream", "content": "answer"})
            await queue.put(
                {
                    "type": "_token_usage",
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                }
            )

        with (
            patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session),
            patch.object(ChatOrchestrator, "_run_flow_streaming", fake_run),
        ):
            async for _ in orch.execute_chat_stream("find docs", "c1"):
                pass

        history = orch.history.get("c1")
        assert len(history) == 2
        assistant_msg = history[1]
        assert assistant_msg["content"] == "streamed answer"
        assert assistant_msg["vs_metadata"]["documents"] == [{"page_content": "doc"}]
        assert assistant_msg["token_usage"]["total_tokens"] == 30

    @pytest.mark.anyio
    async def test_stream_no_metadata_for_llm_only(self):
        """Verify LLM-only streaming history has no metadata keys."""
        orch = _make_orchestrator()
        mock_session = MagicMock(spec=AgentChatSession)
        mock_session.chat = AsyncMock(return_value="hello")
        mock_session.agent = MagicMock()
        mock_session.agent.llm = MagicMock()  # not LiteLlmModel

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            async for _ in orch.execute_chat_stream("hi", "c1"):
                pass

        history = orch.history.get("c1")
        # Agent streaming fallback should still store the message
        assert len(history) == 2
        assistant_msg = history[1]
        assert "vs_metadata" not in assistant_msg
        assert "token_usage" not in assistant_msg


# ---------------------------------------------------------------------------
# TestApiKeyLiveness
# ---------------------------------------------------------------------------


class TestApiKeyLiveness(_WayFlowChatMixin, ApiKeyLivenessBase):
    """Verify the orchestrator uses the *current* API key, not a stale one."""
