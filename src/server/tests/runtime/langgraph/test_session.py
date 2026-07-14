"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the LangGraph session classes.
"""
# spell-checker: disable

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from server.app.api.v1.schemas.chat import SqlMetadata, TokenUsage
from server.app.runtime.common import SessionMetadata, _sum_token_usage, parse_grade_relevant
from server.app.runtime.langgraph.session import (
    AgentGraphSession,
    GraphFlowSession,
    NL2SQLGraphSession,
    _aggregate_usage_callback,
)
from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ as SAMPLE_CLIENT_SETTINGS
from server.tests.constants import TEST_OLLAMA_MODEL_KEY
from server.tests.runtime.langgraph.helpers import mock_compiled_graph

# ---------------------------------------------------------------------------
# TestGraphFlowSessionInit
# ---------------------------------------------------------------------------


class TestGraphFlowSessionInit:
    """Tests for GraphFlowSession initialization."""

    def test_model_derived_from_client_settings(self):
        """Verify model string is derived as provider/id from client_settings."""
        graph = mock_compiled_graph()
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        assert session._model == TEST_OLLAMA_MODEL_KEY

    def test_last_metadata_starts_empty(self):
        """Verify last_metadata starts as empty SessionMetadata."""
        graph = mock_compiled_graph()
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        assert session.last_metadata == SessionMetadata()


# ---------------------------------------------------------------------------
# TestGraphFlowSessionExecute
# ---------------------------------------------------------------------------


class TestGraphFlowSessionExecute:
    """Tests for GraphFlowSession execute and history accumulation."""

    @pytest.mark.anyio
    async def test_execute_returns_answer(self):
        """Verify execute returns the answer from graph result outputs."""
        graph = mock_compiled_graph(
            result={
                "outputs": {"answer": "The answer is 42."},
                "messages": [],
            }
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        result = await session.execute("What is X?", thread_id="t-123")
        assert result == "The answer is 42."

    @pytest.mark.anyio
    async def test_execute_passes_flow_inputs(self):
        """Verify execute passes correct flow input format."""
        graph = mock_compiled_graph()
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        await session.execute("What is X?", thread_id="t-123")

        graph.ainvoke.assert_awaited_once()
        call_args = graph.ainvoke.call_args[0][0]
        assert call_args == {
            "inputs": {
                "query": "What is X?",
                "thread_id": "t-123",
                "model": TEST_OLLAMA_MODEL_KEY,
                "chat_history": "",
            },
            "messages": [],
        }

    @pytest.mark.anyio
    async def test_history_text_passed_through_to_flow_input(self):
        """Verify the caller-supplied history_text reaches the flow input."""
        graph = mock_compiled_graph()
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)

        await session.execute(
            "Follow-up",
            thread_id="t-1",
            history_text="User: First question\nAssistant: First answer\n",
        )
        call_args = graph.ainvoke.call_args[0][0]
        assert "First question" in call_args["inputs"]["chat_history"]
        assert "First answer" in call_args["inputs"]["chat_history"]

    @pytest.mark.anyio
    async def test_falls_back_to_last_ai_message(self):
        """When answer is None, fall back to last AIMessage."""
        graph = mock_compiled_graph(
            result={
                "outputs": {"answer": None},
                "messages": [
                    HumanMessage(content="test"),
                    AIMessage(content="fallback text"),
                ],
            }
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        result = await session.execute("test", thread_id="t1")
        assert result == "fallback text"

    @pytest.mark.anyio
    async def test_empty_history_text_default(self):
        """Verify a missing history_text yields an empty chat_history input."""
        graph = mock_compiled_graph()
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        await session.execute("question", thread_id="t-1")
        call_args = graph.ainvoke.call_args[0][0]
        assert call_args["inputs"]["chat_history"] == ""

    @pytest.mark.anyio
    async def test_execute_flow_inputs_shape_matches_start_node_contract(self):
        """Flat inputs shape is required by pyagentspec StartNodeExecutor.

        StartNodeExecutor._get_inputs() expects state["inputs"] to have plain
        string keys (not UUID-wrapped), extracting them via isinstance(key, str).
        Wrapping under a start-node UUID would break the StartNode.
        """
        graph = mock_compiled_graph()
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        await session.execute("hello", thread_id="t-1")

        call_args = graph.ainvoke.call_args[0][0]
        flow_inputs = call_args["inputs"]

        # All keys must be plain strings (matching StartNodeExecutor contract)
        assert all(isinstance(k, str) for k in flow_inputs)
        # Must NOT be UUID-wrapped (would break StartNodeExecutor)
        import re

        uuid_pattern = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-")
        assert not any(uuid_pattern.match(k) for k in flow_inputs), (
            "Inputs must use plain string keys, not UUID-wrapped keys"
        )
        # Required fields present
        assert "query" in flow_inputs
        assert "thread_id" in flow_inputs
        assert "model" in flow_inputs

    @pytest.mark.anyio
    async def test_error_propagates(self):
        """A failing graph re-raises the exception after logging."""
        graph = mock_compiled_graph(side_effect=RuntimeError("graph failed"))
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        with pytest.raises(RuntimeError, match="graph failed"):
            await session.execute("boom", "t1")


# ---------------------------------------------------------------------------
# TestGraphFlowSessionMetadata
# ---------------------------------------------------------------------------


class TestGraphFlowSessionMetadata:
    """Tests for metadata extraction from GraphFlowSession."""

    @pytest.mark.anyio
    async def test_extracts_grade_relevant(self):
        """Verify grade_relevant is extracted from outputs."""
        graph = mock_compiled_graph(
            result={
                "outputs": {"answer": "doc answer", "grade_relevant": "yes"},
                "messages": [],
            }
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        await session.execute("test", "t1")
        assert session.last_metadata.grade_relevant == "yes"

    @pytest.mark.anyio
    async def test_extracts_vs_metadata_json_string(self):
        """Verify vs_metadata is parsed from JSON string."""
        graph = mock_compiled_graph(
            result={
                "outputs": {
                    "answer": "doc answer",
                    "grade_relevant": "yes",
                    "vs_metadata": '{"documents": [{"page_content": "doc1"}]}',
                },
                "messages": [],
            }
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        await session.execute("test", "t1")
        assert session.last_metadata.vs_metadata is not None
        assert session.last_metadata.vs_metadata.model_dump(exclude_none=True) == {
            "documents": [{"page_content": "doc1"}]
        }

    @pytest.mark.anyio
    async def test_normalizes_vs_metadata_list_to_dict(self):
        """A raw list of documents is normalized to dict with 'documents' key."""
        graph = mock_compiled_graph(
            result={
                "outputs": {
                    "answer": "answer",
                    "grade_relevant": "yes",
                    "vs_metadata": '[{"page_content": "text"}]',
                },
                "messages": [],
            }
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        await session.execute("test", "t1")
        assert session.last_metadata.vs_metadata is not None
        assert session.last_metadata.vs_metadata.model_dump(exclude_none=True) == {
            "documents": [{"page_content": "text"}]
        }

    @pytest.mark.anyio
    async def test_clears_documents_when_irrelevant(self):
        """Verify vs_metadata is preserved with empty documents when grade_relevant='no'."""
        grade_json = '{"relevant": "no", "formatted_documents": ""}'
        inner_json = json.dumps(
            {
                "documents": [{"page_content": "doc1"}],
                "searched_tables": ["TABLE_A"],
                "context_input": "What is X?",
            }
        )
        graph = mock_compiled_graph(
            result={
                "outputs": {
                    "answer": "doc answer",
                    "grade_relevant": grade_json,
                    "vs_metadata": inner_json,
                },
                "messages": [],
            }
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        await session.execute("test", "t1")
        assert session.last_metadata.vs_metadata is not None
        dumped = session.last_metadata.vs_metadata.model_dump(exclude_none=True)
        assert dumped["documents"] == []
        assert dumped["searched_tables"] == ["TABLE_A"]
        assert dumped["context_input"] == "What is X?"

    @pytest.mark.anyio
    async def test_parses_full_vector_search_response(self):
        """Verify searched_tables and context_input are extracted from LangChain content blocks."""
        inner_json = json.dumps(
            {
                "documents": [{"page_content": "doc1"}],
                "searched_tables": ["TABLE_A", "TABLE_B"],
                "context_input": "What is X?",
                "num_documents": 1,
                "status": "success",
            }
        )
        # LangGraph wraps MCP results in content blocks
        content_blocks = json.dumps([{"type": "text", "text": inner_json, "id": "lc_test"}])
        graph = mock_compiled_graph(
            result={
                "outputs": {
                    "answer": "doc answer",
                    "grade_relevant": "yes",
                    "vs_metadata": content_blocks,
                },
                "messages": [],
            }
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        await session.execute("test", "t1")
        assert session.last_metadata.vs_metadata is not None
        dumped = session.last_metadata.vs_metadata.model_dump(exclude_none=True)
        assert dumped["documents"] == [{"page_content": "doc1"}]
        assert dumped["searched_tables"] == ["TABLE_A", "TABLE_B"]
        assert dumped["context_input"] == "What is X?"

    @pytest.mark.anyio
    async def test_extracts_token_usage_from_callback(self):
        """Verify token_usage is aggregated from the UsageMetadataCallbackHandler injected into ainvoke."""
        graph = mock_compiled_graph(
            result={"outputs": {"answer": "answer"}, "messages": []},
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        await session.execute("test", "t1")
        assert session.last_metadata.token_usage == TokenUsage(
            prompt_tokens=20, completion_tokens=10, total_tokens=30
        )

    @pytest.mark.anyio
    async def test_streaming_forwards_chunks_to_queue(self):
        """When a queue is supplied, execute drives ``astream_events`` and forwards chunks."""
        graph = mock_compiled_graph(
            result={"outputs": {"answer": "doc answer"}, "messages": []},
            stream_chunks=["hello ", "world"],
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        queue: asyncio.Queue = asyncio.Queue()
        await session.execute("q", "t1", queue=queue)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert events == [
            {"type": "stream", "content": "hello "},
            {"type": "stream", "content": "world"},
        ]

    @pytest.mark.anyio
    async def test_streaming_fallback_when_no_chunks_emitted(self):
        """If astream_events emits no chat-model chunks but a final answer exists, deliver it once."""
        graph = mock_compiled_graph(
            result={"outputs": {"answer": "final"}, "messages": []},
            stream_chunks=[],
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        queue: asyncio.Queue = asyncio.Queue()
        await session.execute("q", "t1", queue=queue)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert events == [{"type": "stream", "content": "final"}]

    @pytest.mark.anyio
    async def test_node_failure_propagates_without_retry(self):
        """Application/tool errors raised by graph nodes must propagate, not trigger ``ainvoke``.

        A retriever or MCP tool call failing before the answer LLM runs is *not*
        a streaming-setup error. Retrying the whole graph via ``ainvoke`` would
        re-execute the failed node (duplicate DB queries, duplicate MCP calls)
        and almost certainly fail again with the same error. The session must
        surface the original exception so the caller can handle it.
        """
        graph = mock_compiled_graph(result={"outputs": {"answer": "should-not-see"}, "messages": []})
        original_ainvoke = graph.ainvoke

        async def retriever_fails(*_args, **_kwargs):
            raise RuntimeError("retriever MCP call failed")
            yield  # pragma: no cover

        graph.astream_events = retriever_fails
        ainvoke_call_count = 0

        async def counting_ainvoke(*args, **kwargs):
            nonlocal ainvoke_call_count
            ainvoke_call_count += 1
            return await original_ainvoke(*args, **kwargs)

        graph.ainvoke = counting_ainvoke
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        queue: asyncio.Queue = asyncio.Queue()

        with pytest.raises(RuntimeError, match="retriever MCP call failed"):
            await session.execute("q", "t1", queue=queue)

        # No retry — re-running the graph would duplicate the failed node's side effects.
        assert ainvoke_call_count == 0

    @pytest.mark.anyio
    async def test_streaming_normalizes_v1_content_blocks_to_text(self):
        """LangChain v1 output mode delivers chunk.content as typed blocks, not strings.

        With ``LC_OUTPUT_VERSION=v1`` (or ``output_version="v1"``),
        ``AIMessageChunk.content`` becomes a ``list[{"type": "text", "text": ...}, ...]``.
        Enqueueing that list verbatim breaks the streaming finalizer's
        ``"".join(collected)`` call and would also send non-string content
        over SSE. The helper must extract plain text before queueing.
        """
        from langchain_core.messages import AIMessageChunk

        graph = mock_compiled_graph(result={"outputs": {"answer": "answer"}, "messages": []})

        async def v1_block_stream(*_args, **_kwargs):
            yield {"event": "on_chain_start", "name": "MockGraph", "run_id": "r1", "data": {}}
            yield {
                "event": "on_chat_model_stream",
                "name": "MockChatModel",
                "run_id": "rmodel",
                "data": {"chunk": AIMessageChunk(content=[{"type": "text", "text": "hello "}])},
            }
            yield {
                "event": "on_chat_model_stream",
                "name": "MockChatModel",
                "run_id": "rmodel",
                "data": {"chunk": AIMessageChunk(content=[{"type": "text", "text": "world"}])},
            }
            yield {
                "event": "on_chain_end",
                "name": "MockGraph",
                "run_id": "r1",
                "data": {"output": {"outputs": {"answer": "answer"}, "messages": []}},
            }

        graph.astream_events = v1_block_stream
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        queue: asyncio.Queue = asyncio.Queue()
        await session.execute("q", "t1", queue=queue)

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert events == [
            {"type": "stream", "content": "hello "},
            {"type": "stream", "content": "world"},
        ]
        for event in events:
            assert isinstance(event["content"], str), "queue must carry plain strings, not content blocks"


# ---------------------------------------------------------------------------
# TestParseGradeRelevant
# ---------------------------------------------------------------------------


class TestParseGradeRelevant:
    """Tests for parse_grade_relevant (common utility)."""

    def test_none_returns_yes(self):
        """Verify None → 'yes'."""
        assert parse_grade_relevant(None) == "yes"

    def test_json_dict_extracts_relevant(self):
        """Verify JSON dict → extracts 'relevant' key."""
        raw = json.dumps({"relevant": "no", "formatted_documents": ""})
        assert parse_grade_relevant(raw) == "no"

    def test_plain_yes(self):
        """Verify plain 'yes' string."""
        assert parse_grade_relevant("yes") == "yes"

    def test_plain_no(self):
        """Verify plain 'no' string."""
        assert parse_grade_relevant("no") == "no"

    def test_unknown_returns_yes(self):
        """Verify unknown value → 'yes'."""
        assert parse_grade_relevant("maybe") == "yes"

    def test_whitespace_stripped(self):
        """Verify whitespace is stripped."""
        assert parse_grade_relevant("  yes  ") == "yes"


# ---------------------------------------------------------------------------
# TestSumTokenUsage / TestAggregateUsageCallback
# ---------------------------------------------------------------------------


class TestSumTokenUsage:
    """Tests for _sum_token_usage."""

    def test_sums_multiple(self):
        """Verify multiple TokenUsage objects are summed."""
        u1 = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        u2 = TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        result = _sum_token_usage(u1, u2)
        assert result == TokenUsage(prompt_tokens=30, completion_tokens=15, total_tokens=45)

    def test_returns_none_when_all_empty(self):
        """Verify returns None when all usages are None."""
        assert _sum_token_usage(None, None) is None

    def test_skips_none_values(self):
        """Verify None values are skipped."""
        u1 = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        result = _sum_token_usage(u1, None)
        assert result == u1


def _fire_callback(callback: UsageMetadataCallbackHandler, *, model_name: str, **usage: int) -> None:
    """Drive *callback* with a synthetic on_llm_end carrying *usage* metadata."""
    msg = AIMessage(content="", usage_metadata=usage, response_metadata={"model_name": model_name})
    callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]))


class TestAggregateUsageCallback:
    """Tests for _aggregate_usage_callback."""

    def test_returns_none_for_empty_callback(self):
        """A handler with no events returns None."""
        assert _aggregate_usage_callback(UsageMetadataCallbackHandler()) is None

    def test_sums_single_model(self):
        """Single model usage is mapped from input/output_tokens to prompt/completion_tokens."""
        cb = UsageMetadataCallbackHandler()
        _fire_callback(cb, model_name="m1", input_tokens=20, output_tokens=10, total_tokens=30)
        assert _aggregate_usage_callback(cb) == TokenUsage(
            prompt_tokens=20, completion_tokens=10, total_tokens=30
        )

    def test_sums_across_models(self):
        """Per-model usage is summed into a single TokenUsage."""
        cb = UsageMetadataCallbackHandler()
        _fire_callback(cb, model_name="m1", input_tokens=10, output_tokens=5, total_tokens=15)
        _fire_callback(cb, model_name="m2", input_tokens=20, output_tokens=10, total_tokens=30)
        assert _aggregate_usage_callback(cb) == TokenUsage(
            prompt_tokens=30, completion_tokens=15, total_tokens=45
        )

    def test_total_falls_back_to_sum(self):
        """When total_tokens is missing, fall back to prompt+completion."""
        cb = UsageMetadataCallbackHandler()
        _fire_callback(cb, model_name="m", input_tokens=7, output_tokens=3, total_tokens=0)
        result = _aggregate_usage_callback(cb)
        assert result is not None and result.total_tokens == 10


# ---------------------------------------------------------------------------
# TestAgentGraphSession
# ---------------------------------------------------------------------------


class TestAgentGraphSession:
    """Tests for AgentGraphSession."""

    @pytest.mark.anyio
    async def test_chat_returns_last_non_tool_ai_message(self):
        """Verify chat returns the last non-tool AIMessage content."""
        graph = mock_compiled_graph(
            result={
                "messages": [
                    HumanMessage(content="hello"),
                    AIMessage(content="", tool_calls=[{"id": "c1", "name": "f", "args": {}}]),
                    ToolMessage(content="result", tool_call_id="c1"),
                    AIMessage(content="final answer"),
                ],
            }
        )
        session = AgentGraphSession(graph)
        result = await session.chat("hello")
        assert result == "final answer"

    @pytest.mark.anyio
    async def test_chat_prepends_history_messages_to_graph_inputs(self):
        """Caller-supplied history_messages must precede the new user message."""
        graph = mock_compiled_graph(
            result={"messages": [AIMessage(content="reply")]},
        )
        session = AgentGraphSession(graph)
        history = [HumanMessage(content="prior q"), AIMessage(content="prior a")]
        await session.chat("new q", history_messages=history)

        passed = graph.ainvoke.call_args[0][0]["messages"]
        assert [m.content for m in passed] == ["prior q", "prior a", "new q"]

    @pytest.mark.anyio
    async def test_error_propagates(self):
        """Verify error re-raises after logging."""
        graph = mock_compiled_graph(side_effect=RuntimeError("agent failed"))
        session = AgentGraphSession(graph)
        with pytest.raises(RuntimeError, match="agent failed"):
            await session.chat("boom")

    @pytest.mark.anyio
    async def test_token_usage_extracted_after_chat(self):
        """Verify token usage from the callback handler is recorded on session metadata."""
        graph = mock_compiled_graph(
            result={"messages": [AIMessage(content="reply")]},
            usage_metadata={"input_tokens": 15, "output_tokens": 8, "total_tokens": 23},
        )
        session = AgentGraphSession(graph)
        await session.chat("hello")
        assert session.last_metadata.token_usage == TokenUsage(
            prompt_tokens=15, completion_tokens=8, total_tokens=23
        )

    @pytest.mark.anyio
    async def test_chat_extracts_sql_metadata_from_tool_calls(self):
        """SQL tool calls should be exposed in session metadata for downstream responses."""
        graph = mock_compiled_graph(
            result={
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "sqlcl_sql_run",
                                "args": {"sql": "SELECT team_name FROM teams WHERE team_id = 10"},
                                "id": "call_1",
                                "type": "tool_call",
                            }
                        ],
                    ),
                    ToolMessage(content="[{\"TEAM_NAME\": \"Team 10\"}]", tool_call_id="call_1"),
                    AIMessage(content="You are on Team 10."),
                ]
            }
        )
        session = AgentGraphSession(graph)

        await session.chat("Which team am I on?")

        assert session.last_metadata.sql_metadata == SqlMetadata(
            executed_sql=["SELECT team_name FROM teams WHERE team_id = 10"]
        )

    @pytest.mark.anyio
    async def test_chat_extracts_sql_metadata_from_hyphenated_tool_name(self):
        """Hyphenated MCP tool names should still populate executed SQL metadata."""
        graph = mock_compiled_graph(
            result={
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "sqlcl_run-sql",
                                "args": {"sql": "SELECT team_name FROM teams WHERE team_id = 10"},
                                "id": "call_1",
                                "type": "tool_call",
                            }
                        ],
                    ),
                    ToolMessage(content="[{\"TEAM_NAME\": \"Team 10\"}]", tool_call_id="call_1"),
                    AIMessage(content="You are on Team 10."),
                ]
            }
        )
        session = AgentGraphSession(graph)

        await session.chat("Which team am I on?")

        assert session.last_metadata.sql_metadata == SqlMetadata(
            executed_sql=["SELECT team_name FROM teams WHERE team_id = 10"]
        )

    @pytest.mark.anyio
    async def test_chat_streaming_forwards_chunks_to_queue(self):
        """When a queue is supplied, chat drives ``astream_events`` and forwards chunks."""
        graph = mock_compiled_graph(
            result={"messages": [AIMessage(content="response")]},
            stream_chunks=["resp", "onse"],
        )
        session = AgentGraphSession(graph)
        queue: asyncio.Queue = asyncio.Queue()
        await session.chat("hello", queue=queue)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert events == [
            {"type": "stream", "content": "resp"},
            {"type": "stream", "content": "onse"},
        ]

    @pytest.mark.anyio
    async def test_chat_streaming_fallback_when_no_chunks_emitted(self):
        """If astream_events emits no chat-model chunks, deliver the final answer once."""
        graph = mock_compiled_graph(
            result={"messages": [AIMessage(content="response")]},
            stream_chunks=[],
        )
        session = AgentGraphSession(graph)
        queue: asyncio.Queue = asyncio.Queue()
        await session.chat("hello", queue=queue)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert events == [{"type": "stream", "content": "response"}]

# ---------------------------------------------------------------------------
# TestNL2SQLGraphSession
# ---------------------------------------------------------------------------


class TestNL2SQLGraphSession:
    """Tests for NL2SQLGraphSession."""

    @pytest.mark.anyio
    async def test_connects_database_before_turn(self):
        """The configured database connection must be established before chat starts."""
        events: list[str] = []

        async def connect_database():
            events.append("connect")

        graph = mock_compiled_graph(
            result={
                "messages": [AIMessage(content="sql result")],
            }
        )

        async def fake_ainvoke(*_args, **_kwargs):
            events.append("graph")
            return {"messages": [AIMessage(content="sql result")]}

        graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)

        session = NL2SQLGraphSession(
            graph,
            SAMPLE_CLIENT_SETTINGS,
            thread_id="t-1",
            connect_database=connect_database,
        )
        await session.chat("How many tables?")

        assert events == ["connect", "graph"]

    @pytest.mark.anyio
    async def test_db_context_prepended(self):
        """Verify DB context is prepended to messages."""
        graph = mock_compiled_graph(
            result={
                "messages": [AIMessage(content="sql result")],
            }
        )
        session = NL2SQLGraphSession(graph, SAMPLE_CLIENT_SETTINGS, thread_id="t-1")
        await session.chat("How many tables?")

        call_args = graph.ainvoke.call_args[0][0]
        msg_content = call_args["messages"][0].content
        assert f"model: {TEST_OLLAMA_MODEL_KEY}" in msg_content
        assert "thread_id: t-1" in msg_content
        assert "connection_name: CORE" in msg_content
        assert "How many tables?" in msg_content

    @pytest.mark.anyio
    async def test_model_injected(self):
        """Verify model is in the DB context."""
        graph = mock_compiled_graph(
            result={
                "messages": [AIMessage(content="result")],
            }
        )
        session = NL2SQLGraphSession(graph, SAMPLE_CLIENT_SETTINGS)
        await session.chat("test")

        call_args = graph.ainvoke.call_args[0][0]
        msg_content = call_args["messages"][0].content
        assert f"model: {TEST_OLLAMA_MODEL_KEY}" in msg_content

    @pytest.mark.anyio
    async def test_no_connection_name_when_alias_empty(self):
        """Verify connection_name is omitted when alias is empty."""
        from server.app.core.schemas import DatabaseSettings

        settings = SAMPLE_CLIENT_SETTINGS.model_copy(update={"database": DatabaseSettings(alias="")})
        graph = mock_compiled_graph(
            result={
                "messages": [AIMessage(content="result")],
            }
        )
        session = NL2SQLGraphSession(graph, settings)
        await session.chat("test")

        call_args = graph.ainvoke.call_args[0][0]
        msg_content = call_args["messages"][0].content
        assert "connection_name" not in msg_content

    @pytest.mark.anyio
    async def test_no_thread_id_when_not_provided(self):
        """Verify thread_id is omitted when empty."""
        graph = mock_compiled_graph(
            result={
                "messages": [AIMessage(content="result")],
            }
        )
        session = NL2SQLGraphSession(graph, SAMPLE_CLIENT_SETTINGS, thread_id="")
        await session.chat("test")

        call_args = graph.ainvoke.call_args[0][0]
        msg_content = call_args["messages"][0].content
        assert "thread_id" not in msg_content

    @pytest.mark.anyio
    async def test_history_messages_pass_through_unchanged(self):
        """Past turns must come through clean; DB context only on new message."""
        graph = mock_compiled_graph(
            result={"messages": [AIMessage(content="result")]},
        )
        session = NL2SQLGraphSession(graph, SAMPLE_CLIENT_SETTINGS, thread_id="t-1")
        history = [HumanMessage(content="prior"), AIMessage(content="prior reply")]
        await session.chat("new", history_messages=history)

        passed = graph.ainvoke.call_args[0][0]["messages"]
        assert passed[0].content == "prior"
        assert passed[1].content == "prior reply"
        assert f"model: {TEST_OLLAMA_MODEL_KEY}" in passed[2].content
        assert "new" in passed[2].content
        assert "prior" not in passed[2].content
