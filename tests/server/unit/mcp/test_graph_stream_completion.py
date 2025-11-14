"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:disable

from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.types import StreamWriter

from server.mcp.graph import stream_completion, OptimizerState


class TestStreamCompletion:
    """Unit tests for stream_completion function in MCP graph"""

    def setup_method(self):
        """Setup test data"""
        self.base_state = {
            "messages": [HumanMessage(content="Hello")],
            "cleaned_messages": [HumanMessage(content="Hello")],
            "context_input": "",
            "documents": "",
            "vs_metadata": {},
        }

        # Create mock PromptMessage (FastMCP prompt structure)
        mock_prompt_content = MagicMock()
        mock_prompt_content.text = "You are a helpful assistant"
        mock_sys_prompt = MagicMock()
        mock_sys_prompt.content = mock_prompt_content

        self.base_config = {
            "configurable": {
                "thread_id": "test_thread",
                "ll_config": {
                    "model": "gpt-4",
                    "temperature": 0.7,
                    "max_tokens": 4096,
                },
            },
            "metadata": {
                "sys_prompt": mock_sys_prompt,
                "tools": [],
                "use_history": True,
            },
        }

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_basic_streaming_completion(self, mock_acompletion, mock_get_writer):
        """Test basic streaming completion without tools"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Setup streaming response mock
        async def mock_stream():
            # Chunk 1: content
            chunk1 = MagicMock()
            chunk1.choices = [MagicMock()]
            chunk1.choices[0].delta = MagicMock(content="Hello", tool_calls=None)
            chunk1.choices[0].finish_reason = None
            yield chunk1

            # Chunk 2: more content
            chunk2 = MagicMock()
            chunk2.choices = [MagicMock()]
            chunk2.choices[0].delta = MagicMock(content=" there", tool_calls=None)
            chunk2.choices[0].finish_reason = None
            yield chunk2

            # Chunk 3: final chunk
            chunk3 = MagicMock()
            chunk3.choices = [MagicMock()]
            chunk3.choices[0].delta = MagicMock(content="!", tool_calls=None)
            chunk3.choices[0].finish_reason = "stop"
            chunk3.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield chunk3

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert result["messages"][0].content == "Hello there!"

        # Verify stream writer called
        assert mock_writer.call_count >= 3  # At least 3 content chunks

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_streaming_with_tool_calls(self, mock_acompletion, mock_get_writer):
        """Test streaming completion that returns tool calls"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Setup streaming response with tool calls
        async def mock_stream():
            # Chunk 1: tool call start
            chunk1 = MagicMock()
            chunk1.choices = [MagicMock()]
            tool_call_delta = MagicMock()
            tool_call_delta.index = 0
            tool_call_delta.id = "call_123"
            tool_call_delta.function = MagicMock()
            tool_call_delta.function.name = "test_tool"
            tool_call_delta.function.arguments = '{"arg": "'
            chunk1.choices[0].delta = MagicMock(content=None, tool_calls=[tool_call_delta])
            chunk1.choices[0].finish_reason = None
            yield chunk1

            # Chunk 2: tool call arguments continuation
            chunk2 = MagicMock()
            chunk2.choices = [MagicMock()]
            tool_call_delta2 = MagicMock()
            tool_call_delta2.index = 0
            tool_call_delta2.id = None
            tool_call_delta2.function = MagicMock()
            tool_call_delta2.function.name = None
            tool_call_delta2.function.arguments = 'value"}'
            chunk2.choices[0].delta = MagicMock(content=None, tool_calls=[tool_call_delta2])
            chunk2.choices[0].finish_reason = "tool_calls"
            yield chunk2

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert len(result["messages"][0].tool_calls) == 1
        assert result["messages"][0].tool_calls[0]["name"] == "test_tool"
        assert result["messages"][0].tool_calls[0]["args"] == {"arg": "value"}

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_streaming_with_documents_injection(self, mock_acompletion, mock_get_writer):
        """Test that documents are injected into system prompt when present"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Add documents to state
        state_with_docs = self.base_state.copy()
        state_with_docs["documents"] = "Relevant context from vector search"

        # Setup streaming response mock
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content="Response", tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(state_with_docs, self.base_config)

        # Verify acompletion was called with documents in system prompt
        call_args = mock_acompletion.call_args
        messages = call_args.kwargs["messages"]
        system_message = next((m for m in messages if m.get("role") == "system"), None)
        assert system_message is not None
        assert "Relevant context from vector search" in system_message["content"]

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_streaming_with_tools_parameter(self, mock_acompletion, mock_get_writer):
        """Test that tools parameter is passed when tools are present"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Add tools to config
        config_with_tools = self.base_config.copy()
        config_with_tools["metadata"] = config_with_tools["metadata"].copy()
        config_with_tools["metadata"]["tools"] = [
            {"type": "function", "function": {"name": "test_tool"}}
        ]

        # Setup streaming response mock
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content="Response", tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        await stream_completion(self.base_state, config_with_tools)

        # Verify tools were passed to acompletion
        call_args = mock_acompletion.call_args
        assert "tools" in call_args.kwargs
        assert len(call_args.kwargs["tools"]) == 1

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_streaming_without_tools_parameter(self, mock_acompletion, mock_get_writer):
        """Test that tools parameter is omitted when no tools present"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Setup streaming response mock
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content="Response", tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        await stream_completion(self.base_state, self.base_config)

        # Verify tools parameter NOT passed
        call_args = mock_acompletion.call_args
        assert "tools" not in call_args.kwargs

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_empty_response_handling(self, mock_acompletion, mock_get_writer):
        """Test handling of empty response from LLM"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Setup streaming response with no content
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content=None, tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify fallback message
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert "unable to produce a response" in result["messages"][0].content.lower()

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_api_connection_error_handling(self, mock_acompletion, mock_get_writer):
        """Test handling of API connection errors"""
        from litellm.exceptions import APIConnectionError

        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Simulate APIConnectionError (requires llm_provider and model args)
        mock_acompletion.side_effect = APIConnectionError(
            "Connection failed", llm_provider="openai", model="gpt-4"
        )

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify error message
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "problem" in result["messages"][0].content.lower()
        assert "connecting to LLM API" in result["messages"][0].content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_generic_exception_handling(self, mock_acompletion, mock_get_writer):
        """Test handling of generic exceptions"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Simulate generic exception
        mock_acompletion.side_effect = ValueError("Invalid parameter")

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify error message
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "problem" in result["messages"][0].content.lower()
        assert "generating completion" in result["messages"][0].content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_token_usage_emission(self, mock_acompletion, mock_get_writer):
        """Test that token usage is emitted via stream writer"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Setup streaming response with token usage
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content="Response", tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(
                return_value={
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 3,
                        "total_tokens": 8,
                    }
                }
            )
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify token_usage was written to stream
        token_usage_calls = [
            call for call in mock_writer.call_args_list if "token_usage" in str(call)
        ]
        assert len(token_usage_calls) > 0

        # Verify token usage in AIMessage metadata
        assert result["messages"][0].response_metadata["token_usage"]["total_tokens"] == 8

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_vs_metadata_attachment(self, mock_acompletion, mock_get_writer):
        """Test that VS metadata is attached to AIMessage response_metadata"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Add VS metadata to state
        state_with_vs = self.base_state.copy()
        state_with_vs["vs_metadata"] = {
            "searched_tables": ["EMBEDDINGS"],
            "context_input": "rephrased query",
            "num_documents": 3,
        }

        # Setup streaming response mock
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content="Response", tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(state_with_vs, self.base_config)

        # Verify VS metadata in AIMessage response_metadata
        assert "vs_metadata" in result["messages"][0].response_metadata
        assert result["messages"][0].response_metadata["vs_metadata"]["num_documents"] == 3

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_unreliable_function_calling_detection(self, mock_acompletion, mock_get_writer):
        """Test detection of unreliable function calling behavior"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Add tools to config
        config_with_tools = self.base_config.copy()
        config_with_tools["metadata"] = config_with_tools["metadata"].copy()
        config_with_tools["metadata"]["tools"] = [
            {"type": "function", "function": {"name": "test_tool"}}
        ]

        # Setup streaming response that returns JSON as text (unreliable behavior)
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(
                content='{"name": "test_tool", "arguments": {}}', tool_calls=None
            )
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(self.base_state, config_with_tools)

        # Verify error message about unreliable function calling
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert "Function Calling Not Supported" in result["messages"][0].content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_completion_metadata_emission(self, mock_acompletion, mock_get_writer):
        """Test that completion metadata is emitted via stream writer"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Setup streaming response
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content="Response", tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(
                return_value={
                    "id": "chatcmpl-123",
                    "model": "gpt-4",
                    "usage": {"total_tokens": 10},
                }
            )
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        await stream_completion(self.base_state, self.base_config)

        # Verify completion dict was written to stream
        completion_calls = [
            call for call in mock_writer.call_args_list if "completion" in str(call)
        ]
        assert len(completion_calls) > 0

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_message_preparation_with_tool_messages(self, mock_acompletion, mock_get_writer):
        """Test message preparation when state contains ToolMessages"""
        from langchain_core.messages import ToolMessage

        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Add ToolMessage to state
        state_with_tools = self.base_state.copy()
        state_with_tools["messages"] = [
            HumanMessage(content="Hello"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "test", "args": {}, "type": "tool_call"}],
            ),
            ToolMessage(content="Tool result", tool_call_id="call_1"),
        ]

        # Setup streaming response
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content="Response", tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(state_with_tools, self.base_config)

        # Verify messages include ToolMessage (not filtered out)
        call_args = mock_acompletion.call_args
        messages = call_args.kwargs["messages"]
        # Should have: SystemMessage, HumanMessage, AIMessage, ToolMessage
        assert len(messages) >= 3  # At least sys, human, tool result

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_message_preparation_without_tool_messages(self, mock_acompletion, mock_get_writer):
        """Test message preparation uses cleaned_messages when no ToolMessages"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # State without ToolMessages
        state_clean = self.base_state.copy()

        # Setup streaming response
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content="Response", tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(state_clean, self.base_config)

        # Verify messages from cleaned_messages
        call_args = mock_acompletion.call_args
        messages = call_args.kwargs["messages"]
        # Should have: SystemMessage + cleaned_messages
        assert len(messages) >= 2

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_stream_content_chunks(self, mock_acompletion, mock_get_writer):
        """Test that content chunks are streamed individually"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Setup streaming response with multiple content chunks
        async def mock_stream():
            for content in ["Hello", " ", "world", "!"]:
                chunk = MagicMock()
                chunk.choices = [MagicMock()]
                chunk.choices[0].delta = MagicMock(content=content, tool_calls=None)
                chunk.choices[0].finish_reason = None
                yield chunk

            # Final chunk
            final_chunk = MagicMock()
            final_chunk.choices = [MagicMock()]
            final_chunk.choices[0].delta = MagicMock(content=None, tool_calls=None)
            final_chunk.choices[0].finish_reason = "stop"
            final_chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield final_chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify all content chunks were written
        stream_calls = [
            call for call in mock_writer.call_args_list
            if call.args and isinstance(call.args[0], dict) and "stream" in call.args[0]
        ]
        assert len(stream_calls) == 4  # "Hello", " ", "world", "!"

        # Verify final content
        assert result["messages"][0].content == "Hello world!"
