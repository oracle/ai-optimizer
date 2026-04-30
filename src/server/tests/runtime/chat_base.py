"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared base test classes for ChatOrchestrator tests.

Subclasses must define:
    make_orchestrator(**cs_kwargs):  factory returning a ChatOrchestrator.
    ChatOrchestratorClass         : the ChatOrchestrator class (for patch targets).
    LLMConfigurationError         : the LLMConfigurationError exception class.
"""
# spell-checker: disable

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.app.runtime.common import SessionMetadata
from server.tests.runtime.shared_helpers import mock_client_settings

# ---------------------------------------------------------------------------
# Cache base
# ---------------------------------------------------------------------------


class CacheBase:
    """Tests for session caching and invalidation."""

    make_orchestrator: Callable[..., Any]

    def test_invalidate_removes_all_routes(self):
        """Verify invalidate removes all route sessions for a client."""
        orch = self.make_orchestrator()
        orch._session_cache[("c1", "llm_only")] = (MagicMock(), {})
        orch._session_cache[("c1", "nl2sql")] = (MagicMock(), {})
        orch._session_cache[("c2", "llm_only")] = (MagicMock(), {})

        orch.invalidate_session("c1")

        assert ("c1", "llm_only") not in orch._session_cache
        assert ("c1", "nl2sql") not in orch._session_cache
        assert ("c2", "llm_only") in orch._session_cache

    def test_clear_history_invalidates_sessions(self):
        """Verify clear_history also invalidates cached sessions."""
        orch = self.make_orchestrator()
        orch._session_cache[("c1", "llm_only")] = (MagicMock(), {})
        orch.history.append("c1", "user", "test")

        orch.clear_history("c1")

        assert not orch.history.get("c1")
        assert ("c1", "llm_only") not in orch._session_cache


# ---------------------------------------------------------------------------
# Execute chat base
# ---------------------------------------------------------------------------


class ExecuteChatBase:
    """Shared tests for ChatOrchestrator.execute_chat."""

    make_orchestrator: Callable[..., Any]
    LLMConfigurationError: type

    def _mock_llm_session(self):
        """Create a mock session with .chat. Override for runtime-specific specs."""
        session = MagicMock()
        session.chat = AsyncMock(return_value="hello back")
        session.last_metadata = SessionMetadata()
        return session

    @pytest.mark.anyio
    async def test_llm_only_route(self):
        """Verify LLM-only route calls session.chat."""
        orch = self.make_orchestrator()
        mock_session = self._mock_llm_session()

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            result = await orch.execute_chat("hi", "test_client")

        assert result["result"] == "hello back"
        assert result["route"] == "llm_only"

    @pytest.mark.anyio
    async def test_unconfigured_model_raises(self):
        """Verify missing provider raises LLMConfigurationError."""
        orch = self.make_orchestrator(provider=None, model_id=None)

        with pytest.raises(self.LLMConfigurationError):
            await orch.execute_chat("hi", "test_client")

    @pytest.mark.anyio
    async def test_session_rebuilt_on_settings_change(self):
        """Verify changing ll_model settings rebuilds the session."""
        cs = mock_client_settings(chat_history=True)
        orch = self.make_orchestrator(cs=cs)
        mock_session = self._mock_settings_change_session()

        build_mock = AsyncMock(return_value=mock_session)

        with patch.object(orch, "_build_session", build_mock):
            await orch.execute_chat("q1", "c1")

            # Change a setting
            cs.model_dump.return_value = {
                **cs.model_dump(),
                "ll_model": {
                    **cs.model_dump()["ll_model"],
                    "temperature": 0.99,
                },
            }

            await orch.execute_chat("q2", "c1")

        assert build_mock.await_count == 2

    def _mock_settings_change_session(self):
        """Create a mock session for settings change test. Override if needed."""
        return self._mock_llm_session()

    @pytest.mark.anyio
    async def test_populates_history(self):
        """Verify execute_chat appends user and assistant messages to history."""
        orch = self.make_orchestrator()
        mock_session = self._mock_llm_session()
        mock_session.chat = AsyncMock(return_value="the answer")

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            await orch.execute_chat("the question", "c1")

        history = orch.history.get("c1")
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "the question"}
        assert history[1] == {"role": "assistant", "content": "the answer"}

    @pytest.mark.anyio
    async def test_llm_only_returns_none_vs_metadata(self):
        """Verify LLM-only route returns None for vs_metadata."""
        orch = self.make_orchestrator()
        mock_session = self._mock_llm_session()
        mock_session.chat = AsyncMock(return_value="hello")
        mock_session.last_metadata = SessionMetadata()

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            result = await orch.execute_chat("hi", "c1")

        assert result["vs_metadata"] is None


# ---------------------------------------------------------------------------
# Stream base
# ---------------------------------------------------------------------------


class StreamBase:
    """Shared tests for ChatOrchestrator.execute_chat_stream."""

    make_orchestrator: Callable[..., Any]
    ChatOrchestratorClass: type
    LLMConfigurationError: type

    def _mock_agent_session(self):
        """Create a mock session for agent streaming. Override for runtime-specific specs."""
        session = MagicMock()
        session.last_metadata = SessionMetadata()
        return session

    @pytest.mark.anyio
    async def test_yields_stream_and_meta_events(self):
        """Verify stream chunks and _meta event are yielded."""
        orch = self.make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = self._mock_agent_session()

        async def fake_run_agent(_self, _session, _use_history, _question, queue):
            await queue.put({"type": "stream", "content": "Hello"})
            await queue.put({"type": "stream", "content": " world"})

        with (
            patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session),
            patch.object(self.ChatOrchestratorClass, "_run_agent_streaming", fake_run_agent),
        ):
            events = []
            async for event in orch.execute_chat_stream("test", "c1"):
                events.append(event)

        stream_events = [e for e in events if e["type"] == "stream"]
        meta_events = [e for e in events if e["type"] == "_meta"]

        assert len(stream_events) == 2
        assert stream_events[0]["content"] == "Hello"
        assert stream_events[1]["content"] == " world"
        assert len(meta_events) == 1
        assert meta_events[0]["route"] == "nl2sql"

    @pytest.mark.anyio
    async def test_error_event_on_failure(self):
        """Verify task exceptions yield an error event."""
        orch = self.make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = self._mock_agent_session()

        async def failing_run(_self, _session, _use_history, _question, _queue):
            raise RuntimeError("boom")

        with (
            patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session),
            patch.object(self.ChatOrchestratorClass, "_run_agent_streaming", failing_run),
        ):
            events = []
            async for event in orch.execute_chat_stream("test", "c1"):
                events.append(event)

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert "boom" in error_events[0]["content"]

    @pytest.mark.anyio
    async def test_combined_route_streams(self):
        """Verify combined route streams via _run_combined_streaming."""
        orch = self.make_orchestrator(tools_enabled=["NL2SQL", "Vector Search"])

        async def fake_combined(_self, _session, _use_history, _question, _client, queue):
            await queue.put({"type": "stream", "content": "subflow "})
            await queue.put({"type": "stream", "content": "answer"})

        mock_session = self._mock_combined_session()

        with (
            patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session),
            patch.object(self.ChatOrchestratorClass, "_run_combined_streaming", fake_combined),
        ):
            events = []
            async for event in orch.execute_chat_stream("test", "c1"):
                events.append(event)

        stream_events = [e for e in events if e["type"] == "stream"]
        meta_events = [e for e in events if e["type"] == "_meta"]

        assert len(stream_events) == 2
        assert meta_events[0]["route"] == "combined"

    def _mock_combined_session(self):
        """Create a mock CombinedSession. Override for runtime-specific specs."""
        session = MagicMock()
        session.last_metadata = SessionMetadata()
        return session

    @pytest.mark.anyio
    async def test_streaming_reuses_cached_session(self):
        """Verify streaming reuses cached session across calls."""
        orch = self.make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = self._mock_cached_stream_session()

        build_mock = AsyncMock(return_value=mock_session)

        with patch.object(orch, "_build_session", build_mock):
            async for _ in orch.execute_chat_stream("q1", "c1"):
                pass
            async for _ in orch.execute_chat_stream("q2", "c1"):
                pass

        assert build_mock.await_count == 1

    def _mock_cached_stream_session(self):
        """Create a mock session for caching test. Override for runtime-specific setup."""
        session = self._mock_agent_session()
        session.chat = AsyncMock(return_value="answer")
        return session

    @pytest.mark.anyio
    async def test_vs_metadata_in_meta_event(self):
        """Verify _meta event includes vs_metadata from flow session."""
        orch = self.make_orchestrator(tools_enabled=["Vector Search"])
        mock_session = self._mock_vs_metadata_session()

        with patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session):
            events = []
            async for event in orch.execute_chat_stream("test", "c1"):
                events.append(event)

        meta_events = [e for e in events if e["type"] == "_meta"]
        assert len(meta_events) == 1
        assert meta_events[0]["vs_metadata"] == {"documents": [{"searched_tables": ["t1"]}]}

    def _mock_vs_metadata_session(self):
        """Create a mock session with vs_metadata. Override for runtime-specific specs."""
        from server.app.api.v1.schemas.chat import VsMetadata

        session = MagicMock()
        session.execute = AsyncMock(return_value="answer")
        session.last_metadata = SessionMetadata(vs_metadata=VsMetadata(documents=[{"searched_tables": ["t1"]}]))
        return session

    @pytest.mark.anyio
    async def test_populates_history_after_streaming(self):
        """Verify execute_chat_stream populates history after streaming."""
        orch = self.make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = self._mock_agent_session()

        async def fake_run(_self, _session, _use_history, _question, queue):
            await queue.put({"type": "stream", "content": "Hello"})
            await queue.put({"type": "stream", "content": " world"})

        with (
            patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session),
            patch.object(self.ChatOrchestratorClass, "_run_agent_streaming", fake_run),
        ):
            async for _ in orch.execute_chat_stream("the question", "c1"):
                pass

        history = orch.history.get("c1")
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "the question"}
        assert history[1] == {"role": "assistant", "content": "Hello world"}

    @pytest.mark.anyio
    async def test_token_usage_event_passthrough(self):
        """Verify _token_usage events from the queue are yielded."""
        orch = self.make_orchestrator(tools_enabled=["NL2SQL"])
        mock_session = self._mock_agent_session()

        async def fake_run(_self, _session, _use_history, _question, queue):
            await queue.put({"type": "stream", "content": "hello"})
            await queue.put(
                {
                    "type": "_token_usage",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                }
            )

        with (
            patch.object(orch, "_build_session", new_callable=AsyncMock, return_value=mock_session),
            patch.object(self.ChatOrchestratorClass, "_run_agent_streaming", fake_run),
        ):
            events = []
            async for event in orch.execute_chat_stream("test", "c1"):
                events.append(event)

        usage_events = [e for e in events if e["type"] == "_token_usage"]
        assert len(usage_events) == 1
        assert usage_events[0]["prompt_tokens"] == 10

    @pytest.mark.anyio
    async def test_unconfigured_model_raises(self):
        """Verify missing provider raises LLMConfigurationError for streaming."""
        orch = self.make_orchestrator(provider=None, model_id=None)

        with pytest.raises(self.LLMConfigurationError):
            async for _ in orch.execute_chat_stream("hi", "c1"):
                pass


# ---------------------------------------------------------------------------
# API key liveness base
# ---------------------------------------------------------------------------


class ApiKeyLivenessBase:
    """Verify the orchestrator uses the *current* API key."""

    ChatOrchestratorClass: type

    def test_api_key_reflects_update(self):
        """Rotating the key after init must be visible."""
        key_holder = {"key": "original-key"}
        orch = self.ChatOrchestratorClass(
            server_url="http://127.0.0.1:8000/mcp",
            api_key=lambda: key_holder["key"],
            resolve_client=lambda _: mock_client_settings(),
        )
        key_holder["key"] = "rotated-key"
        assert orch.api_key == "rotated-key"

    def test_plain_string_api_key_still_works(self):
        """Plain string api_key still works."""
        orch = self.ChatOrchestratorClass(
            server_url="http://127.0.0.1:8000/mcp",
            api_key="static-key",
            resolve_client=lambda _: mock_client_settings(),
        )
        assert orch.api_key == "static-key"
