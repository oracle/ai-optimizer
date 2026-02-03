"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/mcp/graph.py (refactored version)

Tests the LangGraph-based RAG orchestration system including:
- Helper functions for message creation and error handling
- Routing logic for tool orchestration
- Message building with history management
"""

import json
import decimal
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from server.mcp.graph import (
    _build_messages_for_llm,
    _create_error_message,
    _create_tool_message,
    _create_ai_message_with_tool_calls,
    _build_text_response,
    route_tools,
    DecimalEncoder,
    OptimizerState,
)


class TestDecimalEncoder:
    """Tests for DecimalEncoder JSON serialization."""

    def test_decimal_encoding(self):
        """Test that Decimal objects are serialized to strings."""
        data = {
            "value": decimal.Decimal("123.45"),
            "count": decimal.Decimal("10"),
        }
        result = json.dumps(data, cls=DecimalEncoder)
        expected = '{"value": "123.45", "count": "10"}'
        assert result == expected

    def test_regular_types_unaffected(self):
        """Test that non-Decimal types are serialized normally."""
        data = {
            "string": "test",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
        }
        result = json.dumps(data, cls=DecimalEncoder)
        parsed = json.loads(result)
        assert parsed == data


class TestBuildMessagesForLLM:
    """Tests for _build_messages_for_llm function."""

    @pytest.fixture
    def mock_sys_prompt(self):
        """Create a mock system prompt."""
        mock_prompt = MagicMock()
        mock_prompt.content.text = "You are a helpful assistant."
        return mock_prompt

    def test_with_history_enabled(self, mock_sys_prompt):
        """Test message building with history enabled."""
        state = {
            "messages": [
                SystemMessage(content="Old system prompt"),  # Should be filtered
                HumanMessage(content="First question"),
                AIMessage(content="First answer"),
                HumanMessage(content="Second question"),
            ]
        }

        result = _build_messages_for_llm(state, mock_sys_prompt, use_history=True)

        # Should have: new system prompt + all non-system messages
        assert len(result) == 4
        assert isinstance(result[0], SystemMessage)
        assert result[0].content == "You are a helpful assistant."
        assert isinstance(result[1], HumanMessage)
        assert result[1].content == "First question"
        assert isinstance(result[2], AIMessage)
        assert result[2].content == "First answer"
        assert isinstance(result[3], HumanMessage)
        assert result[3].content == "Second question"

    def test_with_history_disabled(self, mock_sys_prompt):
        """Test message building with history disabled."""
        state = {
            "messages": [
                HumanMessage(content="Old question"),
                AIMessage(content="Old answer"),
                HumanMessage(content="Latest question"),
                AIMessage(content="", tool_calls=[{"id": "call_123", "name": "tool", "args": {}}]),
                ToolMessage(content="Tool result", tool_call_id="call_123"),
            ]
        }

        result = _build_messages_for_llm(state, mock_sys_prompt, use_history=False)

        # Should have: system prompt + flattened context + latest user message
        assert len(result) == 3
        assert isinstance(result[0], SystemMessage)
        # ToolMessage should be flattened to HumanMessage
        assert isinstance(result[1], HumanMessage)
        assert "Tool result" in result[1].content
        assert isinstance(result[2], HumanMessage)
        assert result[2].content == "Latest question"

    def test_history_disabled_only_includes_latest_human_message(self, mock_sys_prompt):
        """Test that with history disabled, only the latest user message is included."""
        state = {
            "messages": [
                HumanMessage(content="Old question 1"),
                AIMessage(content="Old answer 1"),
                HumanMessage(content="Old question 2"),
                AIMessage(content="Old answer 2"),
                HumanMessage(content="Current question"),
            ]
        }

        result = _build_messages_for_llm(state, mock_sys_prompt, use_history=False)

        # Should have: system prompt + latest HumanMessage only
        assert len(result) == 2
        assert isinstance(result[0], SystemMessage)
        assert isinstance(result[1], HumanMessage)
        assert result[1].content == "Current question"

    def test_history_disabled_flattens_tool_messages(self, mock_sys_prompt):
        """Test that ToolMessages are flattened to HumanMessage for OCI compatibility."""
        state = {
            "messages": [
                HumanMessage(content="Current question"),
                AIMessage(content="", tool_calls=[
                    {"id": "call_1", "name": "tool1", "args": {}},
                    {"id": "call_2", "name": "tool2", "args": {}},
                ]),
                ToolMessage(content="Tool 1 result", tool_call_id="call_1"),
                ToolMessage(content="Tool 2 result", tool_call_id="call_2"),
            ]
        }

        result = _build_messages_for_llm(state, mock_sys_prompt, use_history=False)

        # Should have: system prompt + flattened context HumanMessage + user question
        assert len(result) == 3
        assert isinstance(result[0], SystemMessage)
        # ToolMessages should be flattened into a single HumanMessage with context
        assert isinstance(result[1], HumanMessage)
        assert "relevant context from the knowledge base" in result[1].content
        assert "Tool 1 result" in result[1].content
        assert "Tool 2 result" in result[1].content
        # User question should be last
        assert isinstance(result[2], HumanMessage)
        assert result[2].content == "Current question"

    def test_history_disabled_when_latest_is_tool_message(self, mock_sys_prompt):
        """Test when latest message is a ToolMessage (post-orchestration state).

        This is the actual state shape after vs_orchestrate runs - the state ends
        with AIMessage(tool_calls) + ToolMessage, not a HumanMessage.
        """
        state = {
            "messages": [
                HumanMessage(content="User question"),
                AIMessage(content="", tool_calls=[{"id": "vs_retriever", "name": "retriever", "args": {}}]),
                ToolMessage(content='{"formatted_text": "Retrieved docs"}', tool_call_id="vs_retriever"),
            ]
        }

        result = _build_messages_for_llm(state, mock_sys_prompt, use_history=False)

        # Should NOT include raw ToolMessages (OCI rejects orphaned tool messages)
        tool_messages = [m for m in result if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 0, "Raw ToolMessages should be flattened, not included directly"

        # Should have: system prompt + flattened context + user question
        assert len(result) == 3
        assert isinstance(result[0], SystemMessage)
        # Flattened tool content as HumanMessage
        assert isinstance(result[1], HumanMessage)
        assert "relevant context" in result[1].content
        assert "Retrieved docs" in result[1].content
        # Original user question
        assert isinstance(result[2], HumanMessage)
        assert result[2].content == "User question"


class TestCreateErrorMessage:
    """Tests for _create_error_message function."""

    def test_simple_exception(self):
        """Test error message creation from simple exception."""
        exception = ValueError("Invalid input value")
        result = _create_error_message(exception)

        assert isinstance(result, AIMessage)
        assert "I'm sorry, I've run into a problem" in result.content
        assert "Invalid input value" in result.content
        assert "github.com/oracle/ai-optimizer/issues" in result.content

    def test_exception_with_context(self):
        """Test error message creation with context."""
        exception = ConnectionError("Failed to connect")
        result = _create_error_message(exception, "connecting to database")

        assert "I'm sorry, I've run into a problem connecting to database" in result.content
        assert "Failed to connect" in result.content

    def test_exception_with_traceback(self):
        """Test that traceback is stripped from error message."""
        exception_msg = "Error occurred\nTraceback (most recent call last):\n  File ...\nValueError: Bad value"
        exception = ValueError(exception_msg)
        result = _create_error_message(exception)

        # Should only show the error message before traceback
        assert "Error occurred" in result.content
        assert "Traceback" not in result.content


class TestCreateToolMessage:
    """Tests for _create_tool_message function."""

    def test_string_content(self):
        """Test ToolMessage creation with string content."""
        result = _create_tool_message("Tool result", "call_123", "my_tool")

        assert isinstance(result, ToolMessage)
        assert result.content == "Tool result"
        assert result.tool_call_id == "call_123"
        assert result.name == "my_tool"

    def test_dict_content_without_serialization(self):
        """Test ToolMessage creation with dict content (no serialization)."""
        content = {"status": "success", "count": 42}
        result = _create_tool_message(content, "call_123", serialize_json=False)

        # Should be converted to string via str()
        assert isinstance(result.content, str)
        assert result.tool_call_id == "call_123"

    def test_dict_content_with_json_serialization(self):
        """Test ToolMessage creation with JSON serialization."""
        content = {"status": "success", "count": 42, "value": decimal.Decimal("123.45")}
        result = _create_tool_message(content, "call_123", serialize_json=True)

        # Should be JSON serialized with DecimalEncoder
        assert isinstance(result.content, str)
        parsed = json.loads(result.content)
        assert parsed["status"] == "success"
        assert parsed["count"] == 42
        assert parsed["value"] == "123.45"  # Decimal serialized to string


class TestCreateAIMessageWithToolCalls:
    """Tests for _create_ai_message_with_tool_calls function."""

    def test_with_dict_tool_calls(self):
        """Test AIMessage creation with pre-formatted dict tool calls."""
        tool_calls = [
            {"id": "call_1", "name": "tool_a", "args": {"param": "value"}},
            {"id": "call_2", "name": "tool_b", "args": {"count": 5}},
        ]

        result = _create_ai_message_with_tool_calls("Calling tools", tool_calls)

        assert isinstance(result, AIMessage)
        assert result.content == "Calling tools"
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0]["id"] == "call_1"
        assert result.tool_calls[0]["name"] == "tool_a"
        assert result.tool_calls[1]["name"] == "tool_b"

    def test_with_raw_litellm_tool_calls(self):
        """Test AIMessage creation with raw LiteLLM tool call objects."""
        # Mock LiteLLM tool call objects
        mock_tc1 = MagicMock()
        mock_tc1.id = "call_1"
        mock_tc1.function.name = "tool_a"
        mock_tc1.function.arguments = '{"param": "value"}'

        mock_tc2 = MagicMock()
        mock_tc2.id = "call_2"
        mock_tc2.function.name = "tool_b"
        mock_tc2.function.arguments = '{"count": 5}'

        result = _create_ai_message_with_tool_calls("", [mock_tc1, mock_tc2])

        assert len(result.tool_calls) == 2
        assert result.tool_calls[0]["id"] == "call_1"
        assert result.tool_calls[0]["name"] == "tool_a"
        assert result.tool_calls[0]["args"] == {"param": "value"}
        assert result.tool_calls[1]["id"] == "call_2"


class TestBuildTextResponse:
    """Tests for _build_text_response function."""

    @pytest.fixture
    def mock_writer(self):
        """Create a mock stream writer."""
        return MagicMock()

    @pytest.fixture
    def mock_state(self):
        """Create a mock state."""
        return {"vs_metadata": {"num_documents": 5, "searched_tables": ["table1"]}}

    def test_with_full_response(self, mock_writer, mock_state):
        """Test building response with full LLM response chunks."""
        # Mock response chunks
        chunk = MagicMock()
        chunk.object = "chat.completion.chunk"
        chunk.choices = [MagicMock()]
        chunk.choices[0].finish_reason = "stop"
        chunk.choices[0].delta = MagicMock()
        chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 100}})

        full_response = [chunk]
        full_text = "This is the complete response"

        result = _build_text_response(full_text, full_response, mock_writer, mock_state)

        assert isinstance(result, AIMessage)
        assert result.content == "This is the complete response"
        assert "token_usage" in result.response_metadata
        assert "vs_metadata" in result.response_metadata
        assert result.response_metadata["vs_metadata"]["num_documents"] == 5

        # Verify writer was called
        mock_writer.assert_any_call({"token_usage": {"total_tokens": 100}})
        mock_writer.assert_any_call({"vs_metadata": mock_state["vs_metadata"]})

    def test_with_empty_response(self, mock_writer):
        """Test building response with no chunks."""
        state = {}
        result = _build_text_response("Test content", [], mock_writer, state)

        assert isinstance(result, AIMessage)
        assert result.content == "Test content"


class TestRouteTools:
    """Tests for route_tools function."""

    def test_no_tools_routes_to_completion(self):
        """Test routing when no tools are configured."""
        config = {"metadata": {"tools": []}}
        state = {}

        result = route_tools(state, config)

        assert result == "stream_completion"

    def test_optimizer_only_routes_to_vs_orchestrate(self):
        """Test routing with only optimizer VS tools."""
        config = {
            "metadata": {
                "tools": [
                    {"function": {"name": "optimizer_vs-retriever"}},
                    {"function": {"name": "optimizer_vs-storage"}},
                ]
            }
        }
        state = {}

        result = route_tools(state, config)

        assert result == "vs_orchestrate"

    def test_sqlcl_only_routes_to_sqlcl_orchestrate(self):
        """Test routing with only SQL tools."""
        config = {
            "metadata": {
                "tools": [
                    {"function": {"name": "sqlcl_query"}},
                    {"function": {"name": "sqlcl_list_tables"}},
                ]
            }
        }
        state = {}

        result = route_tools(state, config)

        assert result == "sqlcl_orchestrate"

    def test_both_tools_routes_to_multitool(self):
        """Test routing with both VS and SQL tools."""
        config = {
            "metadata": {
                "tools": [
                    {"function": {"name": "optimizer_vs-retriever"}},
                    {"function": {"name": "sqlcl_query"}},
                ]
            }
        }
        state = {}

        result = route_tools(state, config)

        assert result == "multitool"

    def test_unrecognized_tools_routes_to_completion(self):
        """Test routing with unrecognized tool names."""
        config = {
            "metadata": {
                "tools": [
                    {"function": {"name": "unknown_tool"}},
                    {"function": {"name": "another_unknown"}},
                ]
            }
        }
        state = {}

        result = route_tools(state, config)

        assert result == "stream_completion"

    def test_empty_metadata_routes_to_completion(self):
        """Test routing when metadata is empty."""
        config = {"metadata": {}}
        state = {}

        # Should handle missing tools in metadata gracefully
        result = route_tools(state, config)

        assert result == "stream_completion"


class TestOptimizerState:
    """Tests for OptimizerState type."""

    def test_state_creation(self):
        """Test that OptimizerState can be created with required fields."""
        state: OptimizerState = {
            "messages": [HumanMessage(content="test")],
            "vs_metadata": {"num_documents": 3},
        }

        assert len(state["messages"]) == 1
        assert state["vs_metadata"]["num_documents"] == 3

    def test_state_with_empty_vs_metadata(self):
        """Test state with empty vs_metadata."""
        state: OptimizerState = {
            "messages": [],
            "vs_metadata": {},
        }

        assert not state["vs_metadata"]
