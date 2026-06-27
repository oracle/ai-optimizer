"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared base test classes for CombinedSession tests.

Subclasses must define:
    PATCH_PATH: dotted module path for ``litellm.acompletion`` (e.g.
                  ``"server.app.runtime.langgraph.multi_tool"``).
    make_session(**kwargs): factory returning a CombinedSession.
    mock_response(content, usage): factory returning a litellm-style response.
"""
# spell-checker: disable

import asyncio
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Classification base
# ---------------------------------------------------------------------------


class ClassificationBase:
    """Tests for the classify() method."""

    PATCH_PATH: str
    make_session: Callable[..., Any]
    mock_response: Callable[..., Any]

    @pytest.mark.anyio
    async def test_classify_vecsearch(self):
        """Verify 'vecsearch' classification."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("vecsearch")
            session = self.make_session()
            decision, _ = await session.classify("What is data redaction?")
            assert decision == "vecsearch"

    @pytest.mark.anyio
    async def test_classify_nl2sql(self):
        """Verify 'nl2sql' classification."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("nl2sql")
            session = self.make_session()
            decision, _ = await session.classify("How many tables?")
            assert decision == "nl2sql"

    @pytest.mark.anyio
    async def test_classify_both(self):
        """Verify 'both' classification."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("both")
            session = self.make_session()
            decision, _ = await session.classify("Is redo log configured correctly?")
            assert decision == "both"

    @pytest.mark.anyio
    async def test_classify_strips_whitespace_and_quotes(self):
        """Verify classification strips whitespace and quotes."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("  'nl2sql' \n")
            session = self.make_session()
            decision, _ = await session.classify("test query")
            assert decision == "nl2sql"

    @pytest.mark.anyio
    async def test_classify_defaults_to_both_on_unexpected(self):
        """Verify default to 'both' when classifier returns garbage."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("unknown_route")
            session = self.make_session()
            decision, _ = await session.classify("test query")
            assert decision == "both"

    @pytest.mark.anyio
    async def test_classify_defaults_to_both_on_error(self):
        """Verify default to 'both' when LLM call fails."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.side_effect = Exception("LLM unavailable")
            session = self.make_session()
            decision, tu = await session.classify("test query")
            assert decision == "both"
            assert tu is None


# ---------------------------------------------------------------------------
# Routing base
# ---------------------------------------------------------------------------


class RoutingBase:
    """Tests for execute() routing to the correct sub-session."""

    PATCH_PATH: str
    make_session: Callable[..., Any]
    mock_response: Callable[..., Any]

    @pytest.mark.anyio
    async def test_vecsearch_route(self):
        """Verify vecsearch route calls vs_session.execute."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("vecsearch")
            session = self.make_session(vs_answer="doc result")
            result = await session.execute("What is data redaction?", thread_id="t-1")
            assert result == "doc result"

    @pytest.mark.anyio
    async def test_nl2sql_route(self):
        """Verify nl2sql route calls nl2sql_session.chat."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("nl2sql")
            session = self.make_session(nl2sql_answer="sql result")
            result = await session.execute("How many tables?", thread_id="t-1")
            assert result == "sql result"

    @pytest.mark.anyio
    async def test_both_route_calls_synthesize(self):
        """Verify 'both' route calls both sessions then synthesizes."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.side_effect = [
                self.mock_response("both"),
                self.mock_response("synthesized answer"),
            ]
            session = self.make_session(vs_answer="doc answer", nl2sql_answer="sql answer")
            result = await session.execute("Is redo log right?", thread_id="t-1")
            assert result == "synthesized answer"
            assert mock_acompletion.await_count == 2


# ---------------------------------------------------------------------------
# Credentials base
# ---------------------------------------------------------------------------


class CredentialsBase:
    """Tests for api_key/api_base forwarding to litellm calls."""

    PATCH_PATH: str
    make_session: Callable[..., Any]
    mock_response: Callable[..., Any]

    @pytest.mark.anyio
    async def test_classify_forwards_credentials(self):
        """Verify classify() passes api_key and api_base to litellm."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("vecsearch")
            session = self.make_session(api_key="sk-test-123", api_base="https://my-llm.example.com")
            await session.classify("test query")
            call_kwargs = mock_acompletion.call_args
            assert call_kwargs.kwargs.get("api_key") == "sk-test-123"
            assert call_kwargs.kwargs.get("api_base") == "https://my-llm.example.com"

    @pytest.mark.anyio
    async def test_synthesize_forwards_credentials(self):
        """Verify synthesize() passes api_key and api_base to litellm."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("synthesized")
            session = self.make_session(api_key="sk-test-456", api_base="https://api.example.com")
            await session.synthesize("query", "vs answer", "sql answer")
            call_kwargs = mock_acompletion.call_args
            assert call_kwargs.kwargs.get("api_key") == "sk-test-456"
            assert call_kwargs.kwargs.get("api_base") == "https://api.example.com"

    @pytest.mark.anyio
    async def test_no_credentials_when_none(self):
        """Verify no api_key/api_base kwargs when not configured."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("vecsearch")
            session = self.make_session()
            await session.classify("test query")
            call_kwargs = mock_acompletion.call_args
            assert "api_key" not in call_kwargs.kwargs
            assert "api_base" not in call_kwargs.kwargs


# ---------------------------------------------------------------------------
# Streaming base
# ---------------------------------------------------------------------------


class StreamingBase:
    """Tests for execute_streaming() routing and queue events."""

    PATCH_PATH: str
    make_session: Callable[..., Any]
    mock_response: Callable[..., Any]

    @pytest.mark.anyio
    async def test_streaming_vecsearch_delegates_to_stream_flow(self):
        """Verify vecsearch route delegates to stream_flow callback."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("vecsearch")
            session = self.make_session(vs_answer="doc result")
            queue: asyncio.Queue = asyncio.Queue()

            stream_flow = AsyncMock()
            stream_agent = AsyncMock()

            await session.execute_streaming(
                "What is X?",
                "t-1",
                "history-text",
                [],
                queue,
                stream_flow=stream_flow,
                stream_agent=stream_agent,
            )
            stream_flow.assert_awaited_once_with(
                session.vs_session, "vecsearch", "What is X?", "t-1", queue, "history-text"
            )
            stream_agent.assert_not_awaited()

    @pytest.mark.anyio
    async def test_streaming_nl2sql_delegates_to_stream_agent(self):
        """Verify nl2sql route delegates to stream_agent callback."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("nl2sql")
            session = self.make_session(nl2sql_answer="sql result")
            queue: asyncio.Queue = asyncio.Queue()

            stream_flow = AsyncMock()
            stream_agent = AsyncMock()

            history_messages: list = []
            await session.execute_streaming(
                "How many tables?",
                "t-1",
                "",
                history_messages,
                queue,
                stream_flow=stream_flow,
                stream_agent=stream_agent,
            )
            stream_agent.assert_awaited_once_with(
                session.nl2sql_session, history_messages, "How many tables?", queue
            )
            stream_flow.assert_not_awaited()

    @pytest.mark.anyio
    async def test_streaming_both_pushes_synthesized_answer(self):
        """Verify 'both' route synthesizes and pushes answer to queue."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.side_effect = [
                self.mock_response("both"),
                self.mock_response("synthesized answer"),
            ]
            session = self.make_session(vs_answer="doc answer", nl2sql_answer="sql answer")
            queue: asyncio.Queue = asyncio.Queue()

            await session.execute_streaming(
                "Is redo log right?",
                "t-1",
                "",
                [],
                queue,
                stream_flow=AsyncMock(),
                stream_agent=AsyncMock(),
            )
            events = []
            while not queue.empty():
                events.append(await queue.get())
            stream_events = [e for e in events if e.get("type") == "stream"]
            assert len(stream_events) == 1
            assert stream_events[0]["content"] == "synthesized answer"

    @pytest.mark.anyio
    async def test_streaming_both_skips_synthesis_when_irrelevant(self):
        """Verify 'both' streaming returns only nl2sql answer when grade_relevant='no'."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("both")
            session = self.make_session_irrelevant()
            queue: asyncio.Queue = asyncio.Queue()

            await session.execute_streaming(
                "list connections",
                "t-1",
                "",
                [],
                queue,
                stream_flow=AsyncMock(),
                stream_agent=AsyncMock(),
            )
            events = []
            while not queue.empty():
                events.append(await queue.get())
            stream_events = [e for e in events if e.get("type") == "stream"]
            assert len(stream_events) == 1
            assert stream_events[0]["content"] == "sql result"
            # Only classify call, no synthesis
            assert mock_acompletion.await_count == 1

    def make_session_irrelevant(self):
        """Build a session for irrelevant grade tests. Override if setup differs."""
        return self.make_session(
            nl2sql_answer="sql result",
            grade_relevant='{"relevant": "no", "formatted_documents": ""}',
        )


# ---------------------------------------------------------------------------
# Metadata base
# ---------------------------------------------------------------------------


class MetadataBase:
    """Tests for vs_metadata propagation through CombinedSession."""

    PATCH_PATH: str
    make_session: Callable[..., Any]
    mock_response: Callable[..., Any]

    def make_vs_metadata_session(self, documents):
        """Build a session with vs_metadata. Override for runtime-specific setup."""
        return self.make_session(vs_answer="doc answer", vs_metadata={"documents": documents})

    @pytest.mark.anyio
    async def test_vecsearch_propagates_vs_metadata(self):
        """Verify vs_metadata is returned when vecsearch is used."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("vecsearch")
            session = self.make_vs_metadata_session([{"id": "doc1"}])
            await session.execute("What is X?", thread_id="t-1")
            vs = session.last_metadata.vs_metadata
            assert vs is not None
            assert vs.model_dump(exclude_none=True) == {"documents": [{"id": "doc1"}]}

    @pytest.mark.anyio
    async def test_nl2sql_has_no_vs_metadata(self):
        """Verify no vs_metadata for nl2sql route."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = self.mock_response("nl2sql")
            session = self.make_session()
            await session.execute("How many tables?", thread_id="t-1")
            assert session.last_metadata.vs_metadata is None

    @pytest.mark.anyio
    async def test_both_propagates_vs_metadata(self):
        """Verify vs_metadata from vecsearch is propagated for 'both' route."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.side_effect = [
                self.mock_response("both"),
                self.mock_response("synthesized"),
            ]
            session = self.make_vs_metadata_session([{"id": "doc2"}])
            await session.execute("Is this configured right?", thread_id="t-1")
            vs = session.last_metadata.vs_metadata
            assert vs is not None
            assert vs.model_dump(exclude_none=True) == {"documents": [{"id": "doc2"}]}
