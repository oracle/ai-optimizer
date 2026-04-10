"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the LangGraph session classes.
"""
# spell-checker: disable

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from server.app.api.v1.schemas.chat import TokenUsage
from server.app.runtime.common import SessionMetadata, _sum_token_usage, parse_grade_relevant
from server.app.runtime.langgraph.adapters.litellm import ChatLiteLLMBridge
from server.app.runtime.langgraph.session import (
    AgentGraphSession,
    GraphFlowSession,
    NL2SQLGraphSession,
    _clear_graph_token_usage,
    _extract_graph_token_usage,
    _extract_llm_instances,
)
from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ as SAMPLE_CLIENT_SETTINGS
from server.tests.runtime.langgraph.helpers import mock_compiled_graph, mock_graph_node, mock_graph_with_llm

# ---------------------------------------------------------------------------
# TestGraphFlowSessionInit
# ---------------------------------------------------------------------------


class TestGraphFlowSessionInit:
    """Tests for GraphFlowSession initialization."""

    def test_model_derived_from_client_settings(self):
        """Verify model string is derived as provider/id from client_settings."""
        graph = mock_compiled_graph()
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        assert session._model == "ollama/qwen3:8b"

    def test_history_starts_empty(self):
        """Verify history starts as empty string."""
        graph = mock_compiled_graph()
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)
        assert session.history == ""

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
                "model": "ollama/qwen3:8b",
                "chat_history": "",
            },
            "messages": [],
        }

    @pytest.mark.anyio
    async def test_history_accumulates_across_calls(self):
        """Verify chat_history grows with each Q&A turn."""
        graph = mock_compiled_graph(
            result={
                "outputs": {"answer": "First answer"},
                "messages": [],
            }
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)

        await session.execute("First question", thread_id="t-1")
        assert "First question" in session.history
        assert "First answer" in session.history

        # Second call should include history
        graph.ainvoke.return_value = {
            "outputs": {"answer": "Second answer"},
            "messages": [],
        }
        await session.execute("Follow-up", thread_id="t-1")
        call_args = graph.ainvoke.call_args[0][0]
        assert "First question" in call_args["inputs"]["chat_history"]

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
    async def test_no_history_sent_when_disabled(self):
        """Verify chat_history input is empty when chat_history=False."""
        graph = mock_compiled_graph(
            result={
                "outputs": {"answer": "first"},
                "messages": [],
            }
        )
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)

        await session.execute("first question", thread_id="t-1", chat_history=False)

        graph.ainvoke.return_value = {
            "outputs": {"answer": "second"},
            "messages": [],
        }
        await session.execute("second question", thread_id="t-1", chat_history=False)

        call_args = graph.ainvoke.call_args[0][0]
        assert call_args["inputs"]["chat_history"] == ""
        # Internal history still accumulates
        assert "first question" in session.history

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
    async def test_extracts_token_usage_from_graph(self):
        """Verify token_usage is extracted from ChatLiteLLMBridge instances."""
        graph, llm = mock_graph_with_llm(
            result={"outputs": {"answer": "answer"}, "messages": []},
            token_usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        )
        # Token usage is set after ainvoke via _extract_graph_token_usage
        # Simulate: graph runs, LLM records usage
        session = GraphFlowSession(graph, SAMPLE_CLIENT_SETTINGS)

        # Need to set token usage after _clear_graph_token_usage runs
        original_ainvoke = graph.ainvoke

        async def ainvoke_with_usage(*args, **kwargs):
            result = await original_ainvoke(*args, **kwargs)
            llm.last_token_usage = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}
            return result

        graph.ainvoke = AsyncMock(side_effect=ainvoke_with_usage)
        await session.execute("test", "t1")
        assert session.last_metadata.token_usage is not None
        assert session.last_metadata.token_usage.model_dump() == {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        }


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
# TestExtractTokenUsage (module-level helpers)
# ---------------------------------------------------------------------------


class TestExtractLlmInstances:
    """Tests for _extract_llm_instances."""

    def test_finds_direct_instance(self):
        """Verify direct ChatLiteLLMBridge node is found via runnable.bound."""
        llm = ChatLiteLLMBridge(model="m")
        graph = MagicMock()
        graph.nodes = {"node": mock_graph_node(llm)}
        assert _extract_llm_instances(graph) == [llm]

    def test_finds_bound_runnable(self):
        """Verify ChatLiteLLMBridge in bound runnable is found."""
        llm = ChatLiteLLMBridge(model="m")
        graph = MagicMock()
        graph.nodes = {"node": mock_graph_node(llm)}
        assert _extract_llm_instances(graph) == [llm]

    def test_finds_nested_subgraph(self):
        """Verify ChatLiteLLMBridge in nested subgraph is found."""
        llm = ChatLiteLLMBridge(model="m")

        subgraph = MagicMock()
        subgraph.nodes = {"sub_node": mock_graph_node(llm)}

        node = MagicMock()
        node.bound = None
        node.runnable = MagicMock()
        node.runnable.bound = None
        node.runnable.graph = subgraph

        graph = MagicMock()
        graph.nodes = {"node": node}
        result = _extract_llm_instances(graph)
        assert llm in result

    def test_empty_graph(self):
        """Verify empty graph returns empty list."""
        graph = MagicMock()
        graph.nodes = {}
        assert not _extract_llm_instances(graph)


class TestExtractLlmInstancesPregelNode:
    """Tests for _extract_llm_instances with real PregelNode-like structures."""

    def test_finds_llm_in_executor(self):
        """Flow graph: PregelNode.bound.func.llm (LlmNodeExecutor pattern)."""
        llm = ChatLiteLLMBridge(model="m")

        # Simulate LlmNodeExecutor with .llm attribute
        executor = MagicMock()
        executor.llm = llm

        # PregelNode: node.bound = RunnableCallable whose func is the executor
        bound = MagicMock()
        bound.func = executor
        bound.afunc = None

        node = MagicMock(spec=[])  # no .runnable attr
        node.bound = bound
        node.subgraphs = []

        graph = MagicMock()
        graph.nodes = {"flow_node": node}
        result = _extract_llm_instances(graph)
        assert result == [llm]

    def test_finds_llm_in_closure(self):
        """Agent graph: PregelNode.bound.func.__closure__ with 'model' var."""
        llm = ChatLiteLLMBridge(model="m")

        # Create a real closure that captures `model`
        def make_closure(model):
            def func():
                return model

            return func

        fn = make_closure(llm)

        bound = MagicMock()
        bound.func = fn
        bound.afunc = None

        node = MagicMock(spec=[])
        node.bound = bound
        node.subgraphs = []

        graph = MagicMock()
        graph.nodes = {"agent_node": node}
        result = _extract_llm_instances(graph)
        assert result == [llm]

    def test_closure_skips_non_llm_model(self):
        """Closure with 'model' that isn't ChatLiteLLMBridge is ignored."""

        def make_closure(model):
            def func():
                return model

            return func

        fn = make_closure("just-a-string")

        bound = MagicMock()
        bound.func = fn
        bound.afunc = None

        node = MagicMock(spec=[])
        node.bound = bound
        node.subgraphs = []

        graph = MagicMock()
        graph.nodes = {"node": node}
        result = _extract_llm_instances(graph)
        assert not result

    def test_pregel_node_direct_llm_bound(self):
        """PregelNode.bound is directly a ChatLiteLLMBridge."""
        llm = ChatLiteLLMBridge(model="m")

        node = MagicMock(spec=[])
        node.bound = llm
        node.subgraphs = []

        graph = MagicMock()
        graph.nodes = {"node": node}
        result = _extract_llm_instances(graph)
        assert result == [llm]


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


class TestExtractGraphTokenUsage:
    """Tests for _extract_graph_token_usage and _clear_graph_token_usage."""

    def test_extracts_cumulative_usage(self):
        """Verify cumulative usage from all LLM instances."""
        llm1 = ChatLiteLLMBridge(model="m")
        llm1.last_token_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        llm2 = ChatLiteLLMBridge(model="m")
        llm2.last_token_usage = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}

        graph = MagicMock()
        node1 = MagicMock()
        node1.bound = None
        node1.runnable = MagicMock()
        node1.runnable.bound = llm1
        node1.runnable.graph = None
        node2 = MagicMock()
        node2.bound = None
        node2.runnable = MagicMock()
        node2.runnable.bound = llm2
        node2.runnable.graph = None
        graph.nodes = {"n1": node1, "n2": node2}

        result = _extract_graph_token_usage(graph)
        assert result == TokenUsage(prompt_tokens=30, completion_tokens=15, total_tokens=45)

    def test_returns_none_when_no_usage(self):
        """Verify returns None when no LLM has usage."""
        llm = ChatLiteLLMBridge(model="m")
        llm.last_token_usage = None

        graph = MagicMock()
        graph.nodes = {"n": mock_graph_node(llm)}

        assert _extract_graph_token_usage(graph) is None

    def test_clear_resets_all_instances(self):
        """Verify _clear_graph_token_usage resets all instances."""
        llm1 = ChatLiteLLMBridge(model="m")
        llm1.last_token_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        llm2 = ChatLiteLLMBridge(model="m")
        llm2.last_token_usage = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}

        graph = MagicMock()
        node1 = MagicMock()
        node1.bound = None
        node1.runnable = MagicMock()
        node1.runnable.bound = llm1
        node1.runnable.graph = None
        node2 = MagicMock()
        node2.bound = None
        node2.runnable = MagicMock()
        node2.runnable.bound = llm2
        node2.runnable.graph = None
        graph.nodes = {"n1": node1, "n2": node2}

        _clear_graph_token_usage(graph)
        assert llm1.last_token_usage is None
        assert llm2.last_token_usage is None


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
    async def test_tracks_conversation_messages(self):
        """Verify conversation_messages accumulates when chat_history=True."""
        graph = mock_compiled_graph(
            result={
                "messages": [AIMessage(content="reply")],
            }
        )
        session = AgentGraphSession(graph)
        await session.chat("hello", chat_history=True)

        assert len(session.conversation_messages) == 2
        assert isinstance(session.conversation_messages[0], HumanMessage)
        assert isinstance(session.conversation_messages[1], AIMessage)

    @pytest.mark.anyio
    async def test_skips_conversation_messages_when_no_history(self):
        """Verify conversation_messages not updated when chat_history=False."""
        graph = mock_compiled_graph(
            result={
                "messages": [AIMessage(content="reply")],
            }
        )
        session = AgentGraphSession(graph)
        await session.chat("hello", chat_history=False)
        assert len(session.conversation_messages) == 0

    @pytest.mark.anyio
    async def test_error_propagates(self):
        """Verify error re-raises after logging."""
        graph = mock_compiled_graph(side_effect=RuntimeError("agent failed"))
        session = AgentGraphSession(graph)
        with pytest.raises(RuntimeError, match="agent failed"):
            await session.chat("boom")

    @pytest.mark.anyio
    async def test_chat_clears_checkpoint_on_error(self):
        """Verify checkpointer state is cleared when graph.ainvoke() fails."""
        graph = mock_compiled_graph(side_effect=RuntimeError("agent failed"))
        checkpointer = MagicMock()
        session = AgentGraphSession(graph, conversation_id="thread-1", checkpointer=checkpointer)
        with pytest.raises(RuntimeError, match="agent failed"):
            await session.chat("boom")
        checkpointer.delete_thread.assert_called_once_with("thread-1")

    @pytest.mark.anyio
    async def test_chat_clears_checkpoint_ignores_delete_failure(self):
        """Verify chat() still raises original error if delete_thread itself fails."""
        graph = mock_compiled_graph(side_effect=RuntimeError("agent failed"))
        checkpointer = MagicMock()
        checkpointer.delete_thread.side_effect = RuntimeError("delete failed")
        session = AgentGraphSession(graph, conversation_id="thread-1", checkpointer=checkpointer)
        with pytest.raises(RuntimeError, match="agent failed"):
            await session.chat("boom")

    @pytest.mark.anyio
    async def test_token_usage_extracted_after_chat(self):
        """Verify token usage is extracted from graph after chat."""
        graph, llm = mock_graph_with_llm(
            result={"messages": [AIMessage(content="reply")]},
        )
        session = AgentGraphSession(graph)

        original_ainvoke = graph.ainvoke

        async def ainvoke_with_usage(*args, **kwargs):
            result = await original_ainvoke(*args, **kwargs)
            llm.last_token_usage = {"prompt_tokens": 15, "completion_tokens": 8, "total_tokens": 23}
            return result

        graph.ainvoke = AsyncMock(side_effect=ainvoke_with_usage)
        await session.chat("hello")
        assert session.last_metadata.token_usage is not None
        assert session.last_metadata.token_usage.model_dump() == {
            "prompt_tokens": 15,
            "completion_tokens": 8,
            "total_tokens": 23,
        }

    @pytest.mark.anyio
    async def test_conversation_id_generated(self):
        """Verify conversation_id is auto-generated when not provided."""
        graph = mock_compiled_graph()
        session = AgentGraphSession(graph)
        assert session.conversation_id  # non-empty UUID string

    @pytest.mark.anyio
    async def test_conversation_id_preserved(self):
        """Verify conversation_id is preserved when provided."""
        graph = mock_compiled_graph()
        session = AgentGraphSession(graph, conversation_id="custom-id")
        assert session.conversation_id == "custom-id"


# ---------------------------------------------------------------------------
# TestNL2SQLGraphSession
# ---------------------------------------------------------------------------


class TestNL2SQLGraphSession:
    """Tests for NL2SQLGraphSession."""

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
        assert "model: ollama/qwen3:8b" in msg_content
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
        assert "model: ollama/qwen3:8b" in msg_content

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


# ---------------------------------------------------------------------------
# TestCheckpointerStorage
# ---------------------------------------------------------------------------


class TestCheckpointerStorage:
    """Tests for checkpointer storage on session classes."""

    def test_checkpointer_stored_and_accessible(self):
        """Verify checkpointer property returns stored checkpointer."""
        sentinel = object()
        graph = mock_compiled_graph()
        session = AgentGraphSession(graph, checkpointer=sentinel)
        assert session.checkpointer is sentinel

    def test_checkpointer_defaults_to_none(self):
        """Verify checkpointer defaults to None when not provided."""
        graph = mock_compiled_graph()
        session = AgentGraphSession(graph)
        assert session.checkpointer is None

    def test_nl2sql_checkpointer_passed_through(self):
        """Verify NL2SQL passes checkpointer to parent."""
        sentinel = object()
        graph = mock_compiled_graph()
        session = NL2SQLGraphSession(graph, SAMPLE_CLIENT_SETTINGS, checkpointer=sentinel)
        assert session.checkpointer is sentinel
