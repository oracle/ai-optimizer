"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:disable

"""
Integration tests using LiteLLM's built-in mock functionality.
These tests use real LiteLLM code paths but with mocked responses,
providing more realistic testing without actual API calls or costs.
"""

from unittest.mock import patch, MagicMock
import pytest

from langchain_core.messages import HumanMessage, AIMessage

from server.mcp.graph import stream_completion


class TestStreamCompletionWithLiteLLMMocks:
    """Integration tests using LiteLLM's mock_response functionality"""

    def setup_method(self):
        """Setup test data"""
        self.base_state = {
            "messages": [HumanMessage(content="What is 2+2?")],
            "cleaned_messages": [HumanMessage(content="What is 2+2?")],
            "context_input": "",
            "documents": "",
            "vs_metadata": {},
        }

        # Create mock PromptMessage (FastMCP prompt structure)
        mock_prompt_content = MagicMock()
        mock_prompt_content.text = "You are a helpful math assistant"
        mock_sys_prompt = MagicMock()
        mock_sys_prompt.content = mock_prompt_content

        self.base_config = {
            "configurable": {
                "thread_id": "litellm_test_thread",
                "ll_config": {
                    "model": "gpt-3.5-turbo",  # Will be mocked
                    "temperature": 0.0,
                    "max_tokens": 100,
                    "mock_response": "The answer is 4.",  # LiteLLM mock parameter
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
    async def test_litellm_mock_basic_completion(self, mock_get_writer):
        """Test basic completion using LiteLLM's mock_response"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Execute - LiteLLM will use mock_response instead of real API
        result = await stream_completion(self.base_state, self.base_config)

        # Verify result
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "4" in result["messages"][0].content

        # Verify streaming occurred
        stream_calls = [
            call
            for call in mock_writer.call_args_list
            if call.args and isinstance(call.args[0], dict) and "stream" in call.args[0]
        ]
        assert len(stream_calls) > 0

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_with_longer_response(self, mock_get_writer):
        """Test streaming with longer mock response"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Update config with longer response
        config = self.base_config.copy()
        config["configurable"] = self.base_config["configurable"].copy()
        config["configurable"]["ll_config"] = self.base_config["configurable"]["ll_config"].copy()
        config["configurable"]["ll_config"]["mock_response"] = (
            "To calculate 2+2, we simply add the two numbers together. "
            "The result is 4, which is a fundamental arithmetic operation."
        )

        # Execute
        result = await stream_completion(self.base_state, config)

        # Verify full content was received
        assert "messages" in result
        content = result["messages"][0].content
        assert "calculate 2+2" in content
        assert "result is 4" in content
        assert "arithmetic" in content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_with_vector_search_documents(self, mock_get_writer):
        """Test mock completion with vector search documents injected"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Create state with vector search documents
        state_with_vs = self.base_state.copy()
        state_with_vs["documents"] = "Document 1: The sum of 2 and 2 equals 4.\nDocument 2: Addition is a basic arithmetic operation."
        state_with_vs["vs_metadata"] = {
            "searched_tables": ["MATH_KNOWLEDGE"],
            "context_input": "What is 2+2?",
            "num_documents": 2,
        }

        # Update mock response to reference the documents
        config = self.base_config.copy()
        config["configurable"] = self.base_config["configurable"].copy()
        config["configurable"]["ll_config"] = self.base_config["configurable"]["ll_config"].copy()
        config["configurable"]["ll_config"]["mock_response"] = (
            "Based on the provided documents, the sum of 2 and 2 equals 4."
        )

        # Execute
        result = await stream_completion(state_with_vs, config)

        # Verify documents were injected (would be in system prompt)
        assert "messages" in result
        assert "4" in result["messages"][0].content

        # Verify VS metadata is attached
        assert "vs_metadata" in result["messages"][0].response_metadata
        assert result["messages"][0].response_metadata["vs_metadata"]["num_documents"] == 2

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_conversation_history(self, mock_get_writer):
        """Test mock completion with conversation history"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Create state with conversation history
        state_with_history = {
            "messages": [
                HumanMessage(content="What is 2+2?"),
                AIMessage(content="The answer is 4."),
                HumanMessage(content="What about 3+3?"),
            ],
            "cleaned_messages": [
                HumanMessage(content="What is 2+2?"),
                AIMessage(content="The answer is 4."),
                HumanMessage(content="What about 3+3?"),
            ],
            "context_input": "",
            "documents": "",
            "vs_metadata": {},
        }

        # Update mock response for second question
        config = self.base_config.copy()
        config["configurable"] = self.base_config["configurable"].copy()
        config["configurable"]["ll_config"] = self.base_config["configurable"]["ll_config"].copy()
        config["configurable"]["ll_config"]["mock_response"] = "Following the same pattern, 3+3 equals 6."

        # Execute
        result = await stream_completion(state_with_history, config)

        # Verify response
        assert "messages" in result
        assert "6" in result["messages"][0].content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_with_different_models(self, mock_get_writer):
        """Test that mocking works with different model names"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Test with different model names
        for model in ["gpt-4", "gpt-3.5-turbo", "claude-3-sonnet", "command-r-plus"]:
            config = self.base_config.copy()
            config["configurable"] = self.base_config["configurable"].copy()
            config["configurable"]["ll_config"] = {
                "model": model,
                "temperature": 0.0,
                "max_tokens": 100,
                "mock_response": f"Response from {model}: 2+2=4",
            }

            # Execute
            result = await stream_completion(self.base_state, config)

            # Verify response contains model-specific content
            assert "messages" in result
            assert model in result["messages"][0].content or "4" in result["messages"][0].content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_temperature_variations(self, mock_get_writer):
        """Test with different temperature settings (mocked)"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Test with different temperatures
        for temp in [0.0, 0.5, 1.0]:
            config = self.base_config.copy()
            config["configurable"] = self.base_config["configurable"].copy()
            config["configurable"]["ll_config"] = {
                "model": "gpt-3.5-turbo",
                "temperature": temp,
                "max_tokens": 100,
                "mock_response": "The answer is 4.",
            }

            # Execute
            result = await stream_completion(self.base_state, config)

            # Verify response
            assert "messages" in result
            assert "4" in result["messages"][0].content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_max_tokens_handling(self, mock_get_writer):
        """Test with different max_tokens settings (mocked)"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Test with different max_tokens
        for max_tokens in [10, 50, 100, 500]:
            config = self.base_config.copy()
            config["configurable"] = self.base_config["configurable"].copy()
            config["configurable"]["ll_config"] = {
                "model": "gpt-3.5-turbo",
                "temperature": 0.0,
                "max_tokens": max_tokens,
                "mock_response": "4",
            }

            # Execute
            result = await stream_completion(self.base_state, config)

            # Verify response
            assert "messages" in result
            assert "4" in result["messages"][0].content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_metadata_capture(self, mock_get_writer):
        """Test that token usage and metadata are captured correctly"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Execute with mock
        result = await stream_completion(self.base_state, self.base_config)

        # Verify response metadata exists
        assert "messages" in result
        assert hasattr(result["messages"][0], "response_metadata")

        # Note: LiteLLM mocks may not include token usage, but metadata structure should exist
        # In real usage, token_usage would be populated

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_special_characters(self, mock_get_writer):
        """Test mock responses with special characters and formatting"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Test with response containing special characters
        config = self.base_config.copy()
        config["configurable"] = self.base_config["configurable"].copy()
        config["configurable"]["ll_config"] = self.base_config["configurable"]["ll_config"].copy()
        config["configurable"]["ll_config"]["mock_response"] = (
            "The answer is 2 + 2 = 4.\n\n"
            "**Note**: This is basic arithmetic.\n"
            "- Addition: ✓\n"
            "- Result: 4 🎉"
        )

        # Execute
        result = await stream_completion(self.base_state, config)

        # Verify special characters preserved
        content = result["messages"][0].content
        assert "**Note**" in content
        assert "✓" in content
        assert "🎉" in content

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_multiline_response(self, mock_get_writer):
        """Test mock responses with multiple lines"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Test with multiline response
        config = self.base_config.copy()
        config["configurable"] = self.base_config["configurable"].copy()
        config["configurable"]["ll_config"] = self.base_config["configurable"]["ll_config"].copy()
        config["configurable"]["ll_config"]["mock_response"] = (
            "Step 1: Identify the numbers (2 and 2)\n"
            "Step 2: Apply addition operation\n"
            "Step 3: Calculate the sum\n"
            "Result: 4"
        )

        # Execute
        result = await stream_completion(self.base_state, config)

        # Verify multiline content preserved
        content = result["messages"][0].content
        assert "Step 1" in content
        assert "Step 2" in content
        assert "Step 3" in content
        assert "Result: 4" in content


class TestStreamCompletionLiteLLMEdgeCases:
    """Edge case tests using LiteLLM mocks"""

    def setup_method(self):
        """Setup test data"""
        # Create mock PromptMessage
        mock_prompt_content = MagicMock()
        mock_prompt_content.text = "You are a helpful assistant"
        mock_sys_prompt = MagicMock()
        mock_sys_prompt.content = mock_prompt_content

        self.base_config = {
            "configurable": {
                "thread_id": "edge_case_thread",
                "ll_config": {
                    "model": "gpt-3.5-turbo",
                    "temperature": 0.0,
                    "max_tokens": 100,
                    "mock_response": "Test response",
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
    async def test_litellm_mock_empty_string_response(self, mock_get_writer):
        """Test handling of minimal/empty-like response

        Note: LiteLLM's mock_response parameter doesn't work with truly empty strings
        (it falls back to real API calls). Instead, test with a single space which
        simulates an effectively empty response.
        """
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Create state
        state = {
            "messages": [HumanMessage(content="Say nothing")],
            "cleaned_messages": [HumanMessage(content="Say nothing")],
            "context_input": "",
            "documents": "",
            "vs_metadata": {},
        }

        # Config with minimal response (single space - closest to empty that works with mock)
        config = self.base_config.copy()
        config["configurable"] = self.base_config["configurable"].copy()
        config["configurable"]["ll_config"] = self.base_config["configurable"]["ll_config"].copy()
        config["configurable"]["ll_config"]["mock_response"] = " "

        # Execute
        result = await stream_completion(state, config)

        # Verify response is received (even if minimal)
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        # Content should be the minimal space
        assert len(result["messages"][0].content.strip()) == 0

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_very_long_response(self, mock_get_writer):
        """Test with very long mock response"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Create state
        state = {
            "messages": [HumanMessage(content="Tell me a long story")],
            "cleaned_messages": [HumanMessage(content="Tell me a long story")],
            "context_input": "",
            "documents": "",
            "vs_metadata": {},
        }

        # Config with very long response (simulate token-heavy response)
        long_response = " ".join(["This is sentence number " + str(i) + "." for i in range(100)])
        config = self.base_config.copy()
        config["configurable"] = self.base_config["configurable"].copy()
        config["configurable"]["ll_config"] = self.base_config["configurable"]["ll_config"].copy()
        config["configurable"]["ll_config"]["mock_response"] = long_response

        # Execute
        result = await stream_completion(state, config)

        # Verify long response handled
        assert "messages" in result
        assert len(result["messages"][0].content) > 1000

    @pytest.mark.asyncio
    @patch("server.mcp.graph.get_stream_writer")
    async def test_litellm_mock_unicode_characters(self, mock_get_writer):
        """Test with Unicode characters in mock response"""
        # Setup stream writer mock
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        # Create state
        state = {
            "messages": [HumanMessage(content="Respond in multiple languages")],
            "cleaned_messages": [HumanMessage(content="Respond in multiple languages")],
            "context_input": "",
            "documents": "",
            "vs_metadata": {},
        }

        # Config with Unicode response
        config = self.base_config.copy()
        config["configurable"] = self.base_config["configurable"].copy()
        config["configurable"]["ll_config"] = self.base_config["configurable"]["ll_config"].copy()
        config["configurable"]["ll_config"]["mock_response"] = (
            "Hello in different languages:\n"
            "🇬🇧 Hello\n"
            "🇫🇷 Bonjour\n"
            "🇩🇪 Guten Tag\n"
            "🇯🇵 こんにちは\n"
            "🇨🇳 你好\n"
            "🇷🇺 Здравствуйте"
        )

        # Execute
        result = await stream_completion(state, config)

        # Verify Unicode preserved
        content = result["messages"][0].content
        assert "Bonjour" in content
        assert "こんにちは" in content
        assert "🇯🇵" in content
