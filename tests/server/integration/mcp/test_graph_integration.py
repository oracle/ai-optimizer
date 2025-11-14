"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:disable

from unittest.mock import patch, MagicMock
import pytest

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.types import StreamWriter

from server.mcp.graph import stream_completion, OptimizerState


class TestStreamCompletionIntegration:
    """Integration tests for stream_completion with real-ish scenarios"""

    def setup_method(self):
        """Setup test data"""
        self.base_state = {
            "messages": [HumanMessage(content="What is the capital of France?")],
            "cleaned_messages": [HumanMessage(content="What is the capital of France?")],
            "context_input": "",
            "documents": "",
            "vs_metadata": {},
        }

        # Create mock PromptMessage (FastMCP prompt structure)
        mock_prompt_content = MagicMock()
        mock_prompt_content.text = "You are a helpful geography assistant"
        mock_sys_prompt = MagicMock()
        mock_sys_prompt.content = mock_prompt_content

        self.base_config = {
            "configurable": {
                "thread_id": "integration_test_thread",
                "ll_config": {
                    "model": "gpt-4",
                    "temperature": 0.7,
                    "max_tokens": 4096,
                    "top_p": 1.0,
                    "frequency_penalty": 0.0,
                    "presence_penalty": 0.0,
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
    async def test_complete_conversation_flow(self, mock_acompletion, mock_get_writer):
        """Test a complete conversation flow with multiple messages"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Simulate a realistic streaming response
        async def mock_stream():
            response_chunks = ["The", " capital", " of", " France", " is", " Paris", "."]
            for i, content in enumerate(response_chunks):
                chunk = MagicMock()
                chunk.choices = [MagicMock()]
                chunk.choices[0].delta = MagicMock(content=content, tool_calls=None)
                chunk.choices[0].finish_reason = None if i < len(response_chunks) - 1 else "stop"
                if i == len(response_chunks) - 1:
                    chunk.model_dump = MagicMock(
                        return_value={
                            "id": "chatcmpl-abc123",
                            "model": "gpt-4",
                            "usage": {
                                "prompt_tokens": 15,
                                "completion_tokens": 8,
                                "total_tokens": 23,
                            },
                        }
                    )
                yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify complete response
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert result["messages"][0].content == "The capital of France is Paris."

        # Verify metadata
        assert "token_usage" in result["messages"][0].response_metadata
        assert result["messages"][0].response_metadata["token_usage"]["total_tokens"] == 23

        # Verify streaming occurred
        stream_calls = [
            call for call in mock_writer.call_args_list
            if call.args and isinstance(call.args[0], dict) and "stream" in call.args[0]
        ]
        assert len(stream_calls) == 7  # One for each chunk

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_vector_search_with_documents(self, mock_acompletion, mock_get_writer):
        """Test completion with vector search documents injected"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Create state with vector search results
        state_with_vs = {
            "messages": [HumanMessage(content="What are the product features?")],
            "cleaned_messages": [HumanMessage(content="What are the product features?")],
            "context_input": "What are the product features?",
            "documents": "Document 1: The product has AI capabilities.\nDocument 2: It supports multiple languages.",
            "vs_metadata": {
                "searched_tables": ["PRODUCT_DOCS"],
                "context_input": "What are the product features?",
                "num_documents": 2,
            },
        }

        # Simulate streaming response
        async def mock_stream():
            response = "Based on the documentation, the product has AI capabilities and supports multiple languages."
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content=response, tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(
                return_value={
                    "usage": {
                        "prompt_tokens": 50,  # Higher due to injected documents
                        "completion_tokens": 15,
                        "total_tokens": 65,
                    }
                }
            )
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(state_with_vs, self.base_config)

        # Verify documents were injected into system prompt
        call_args = mock_acompletion.call_args
        messages = call_args.kwargs["messages"]
        system_message = next((m for m in messages if m.get("role") == "system"), None)
        assert system_message is not None
        assert "AI capabilities" in system_message["content"]
        assert "multiple languages" in system_message["content"]
        assert "Relevant Context:" in system_message["content"]

        # Verify VS metadata in response
        assert "vs_metadata" in result["messages"][0].response_metadata
        assert result["messages"][0].response_metadata["vs_metadata"]["num_documents"] == 2

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_tool_calling_flow(self, mock_acompletion, mock_get_writer):
        """Test flow when LLM decides to call a tool"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Add tools to config
        config_with_tools = self.base_config.copy()
        config_with_tools["metadata"] = self.base_config["metadata"].copy()
        config_with_tools["metadata"]["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"}
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

        # Update state with weather question
        state_weather = self.base_state.copy()
        state_weather["messages"] = [HumanMessage(content="What's the weather in Paris?")]
        state_weather["cleaned_messages"] = [HumanMessage(content="What's the weather in Paris?")]

        # Simulate tool call response
        async def mock_stream():
            # Tool call chunk 1: id and function name
            chunk1 = MagicMock()
            chunk1.choices = [MagicMock()]
            tool_call_delta1 = MagicMock()
            tool_call_delta1.index = 0
            tool_call_delta1.id = "call_weather_123"
            tool_call_delta1.function = MagicMock()
            tool_call_delta1.function.name = "get_weather"
            tool_call_delta1.function.arguments = '{"location": '
            chunk1.choices[0].delta = MagicMock(content=None, tool_calls=[tool_call_delta1])
            chunk1.choices[0].finish_reason = None
            yield chunk1

            # Tool call chunk 2: complete arguments
            chunk2 = MagicMock()
            chunk2.choices = [MagicMock()]
            tool_call_delta2 = MagicMock()
            tool_call_delta2.index = 0
            tool_call_delta2.id = None
            tool_call_delta2.function = MagicMock()
            tool_call_delta2.function.name = None
            tool_call_delta2.function.arguments = '"Paris"}'
            chunk2.choices[0].delta = MagicMock(content=None, tool_calls=[tool_call_delta2])
            chunk2.choices[0].finish_reason = "tool_calls"
            yield chunk2

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(state_weather, config_with_tools)

        # Verify tool call was returned
        assert "messages" in result
        assert len(result["messages"]) == 1
        ai_message = result["messages"][0]
        assert isinstance(ai_message, AIMessage)
        assert hasattr(ai_message, "tool_calls")
        assert len(ai_message.tool_calls) == 1

        # Verify tool call details
        tool_call = ai_message.tool_calls[0]
        assert tool_call["name"] == "get_weather"
        assert tool_call["id"] == "call_weather_123"
        assert tool_call["args"] == {"location": "Paris"}
        assert tool_call["type"] == "tool_call"

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_multi_turn_conversation(self, mock_acompletion, mock_get_writer):
        """Test handling of multi-turn conversation with history"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Create state with conversation history
        state_multi_turn = {
            "messages": [
                HumanMessage(content="What is Python?"),
                AIMessage(content="Python is a programming language."),
                HumanMessage(content="What can I use it for?"),
            ],
            "cleaned_messages": [
                HumanMessage(content="What is Python?"),
                AIMessage(content="Python is a programming language."),
                HumanMessage(content="What can I use it for?"),
            ],
            "context_input": "",
            "documents": "",
            "vs_metadata": {},
        }

        # Simulate streaming response
        async def mock_stream():
            response = "You can use Python for web development, data science, automation, and more."
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content=response, tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(
                return_value={
                    "usage": {
                        "prompt_tokens": 30,  # Higher due to conversation history
                        "completion_tokens": 15,
                        "total_tokens": 45,
                    }
                }
            )
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(state_multi_turn, self.base_config)

        # Verify response
        assert result["messages"][0].content == "You can use Python for web development, data science, automation, and more."

        # Verify conversation history was included
        call_args = mock_acompletion.call_args
        messages = call_args.kwargs["messages"]
        # Should have: system + 3 conversation messages
        assert len(messages) >= 4

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_error_recovery_and_retry(self, mock_acompletion, mock_get_writer):
        """Test that errors are handled gracefully and returned to user"""
        from litellm.exceptions import APIConnectionError

        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # First call fails, but function handles it
        mock_acompletion.side_effect = APIConnectionError(
            "Service temporarily unavailable", llm_provider="openai", model="gpt-4"
        )

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify error was caught and returned as AIMessage
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "problem" in result["messages"][0].content.lower()
        assert "connecting to LLM API" in result["messages"][0].content
        assert "Service temporarily unavailable" in result["messages"][0].content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_long_streaming_response(self, mock_acompletion, mock_get_writer):
        """Test handling of long streaming response with many chunks"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Simulate many chunks (like a long explanation)
        async def mock_stream():
            words = "This is a very long response that contains many words and will be streamed in many chunks to test the streaming capability of the system.".split()
            for i, word in enumerate(words):
                chunk = MagicMock()
                chunk.choices = [MagicMock()]
                content = word if i == 0 else f" {word}"
                chunk.choices[0].delta = MagicMock(content=content, tool_calls=None)
                chunk.choices[0].finish_reason = None if i < len(words) - 1 else "stop"
                if i == len(words) - 1:
                    chunk.model_dump = MagicMock(
                        return_value={"usage": {"total_tokens": 50}}
                    )
                yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify all content was collected
        expected = "This is a very long response that contains many words and will be streamed in many chunks to test the streaming capability of the system."
        assert result["messages"][0].content == expected

        # Verify all chunks were streamed (25 words in the sentence)
        stream_calls = [
            call for call in mock_writer.call_args_list
            if call.args and isinstance(call.args[0], dict) and "stream" in call.args[0]
        ]
        assert len(stream_calls) == 25  # Number of words in sentence

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_model_parameters_passed_correctly(self, mock_acompletion, mock_get_writer):
        """Test that all LLM config parameters are passed to acompletion"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Setup config with specific parameters
        config_with_params = self.base_config.copy()
        config_with_params["configurable"]["ll_config"] = {
            "model": "gpt-4-turbo",
            "temperature": 0.5,
            "max_tokens": 2048,
            "top_p": 0.9,
            "frequency_penalty": 0.2,
            "presence_penalty": 0.1,
        }

        # Simulate response
        async def mock_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content="Response", tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        await stream_completion(self.base_state, config_with_params)

        # Verify all parameters passed
        call_args = mock_acompletion.call_args
        assert call_args.kwargs["model"] == "gpt-4-turbo"
        assert call_args.kwargs["temperature"] == 0.5
        assert call_args.kwargs["max_tokens"] == 2048
        assert call_args.kwargs["top_p"] == 0.9
        assert call_args.kwargs["frequency_penalty"] == 0.2
        assert call_args.kwargs["presence_penalty"] == 0.1
        assert call_args.kwargs["stream"] is True

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_combined_vs_and_tools(self, mock_acompletion, mock_get_writer):
        """Test combination of vector search documents and tool availability"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Create state with both VS results and tools
        state_combined = {
            "messages": [HumanMessage(content="What's the weather like according to our docs?")],
            "cleaned_messages": [HumanMessage(content="What's the weather like according to our docs?")],
            "context_input": "weather information",
            "documents": "Document: Our system monitors weather patterns.",
            "vs_metadata": {
                "searched_tables": ["WEATHER_DOCS"],
                "context_input": "weather information",
                "num_documents": 1,
            },
        }

        config_with_tools = self.base_config.copy()
        config_with_tools["metadata"] = self.base_config["metadata"].copy()
        config_with_tools["metadata"]["tools"] = [
            {"type": "function", "function": {"name": "get_weather"}}
        ]

        # Simulate response
        async def mock_stream():
            response = "According to the documentation, our system monitors weather patterns."
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(content=response, tool_calls=None)
            chunk.choices[0].finish_reason = "stop"
            chunk.model_dump = MagicMock(
                return_value={"usage": {"total_tokens": 40}}
            )
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(state_combined, config_with_tools)

        # Verify both documents and tools were considered
        call_args = mock_acompletion.call_args
        messages = call_args.kwargs["messages"]
        system_message = next((m for m in messages if m.get("role") == "system"), None)
        assert "monitors weather patterns" in system_message["content"]
        assert "tools" in call_args.kwargs
        assert len(call_args.kwargs["tools"]) == 1

        # Verify VS metadata in response
        assert "vs_metadata" in result["messages"][0].response_metadata

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_unreliable_function_calling_detection(self, mock_acompletion, mock_get_writer):
        """Test detection of models that return JSON-like text instead of tool_calls"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Add tools to config
        config_with_tools = self.base_config.copy()
        config_with_tools["metadata"] = self.base_config["metadata"].copy()
        config_with_tools["metadata"]["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                        "required": ["location"],
                    },
                },
            }
        ]

        # Mock LLM returning JSON as text instead of tool_calls (unreliable function calling)
        async def mock_stream():
            # Model returns JSON-like structure as text content, not as tool_calls
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock(
                content='{"name": "get_weather", "arguments": {"location": "NYC"}}', tool_calls=None
            )
            chunk.choices[0].finish_reason = "stop"
            chunk.object = "chat.completion.chunk"
            chunk.model_dump = MagicMock(return_value={"usage": {"total_tokens": 10}})
            yield chunk

        mock_acompletion.return_value = mock_stream()

        # Execute
        result = await stream_completion(self.base_state, config_with_tools)

        # Verify unreliable function calling was detected and error returned
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "Function Calling Not Supported" in result["messages"][0].content
        # Should mention the model name in error
        assert "gpt-4" in result["messages"][0].content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    @patch("server.mcp.graph.acompletion")
    async def test_generic_exception_handling(self, mock_acompletion, mock_get_writer):
        """Test that non-APIConnectionError exceptions are caught gracefully"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Mock raising a generic exception (not APIConnectionError)
        mock_acompletion.side_effect = ValueError("Invalid model configuration parameter")

        # Execute
        result = await stream_completion(self.base_state, self.base_config)

        # Verify error was caught and returned as user-friendly AIMessage
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "problem" in result["messages"][0].content.lower()
        assert "generating completion" in result["messages"][0].content
        assert "Invalid model configuration parameter" in result["messages"][0].content
        # Should include GitHub issues link for bug reports
        assert "github.com/oracle/ai-optimizer/issues" in result["messages"][0].content
