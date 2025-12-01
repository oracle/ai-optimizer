"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/chat.py
Tests for chat completion endpoints.
"""

from unittest.mock import patch, MagicMock
import pytest
from fastapi.responses import StreamingResponse

from server.api.v1 import chat


class TestChatPost:
    """Tests for the chat_post endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chat.completion_generator")
    async def test_chat_post_returns_last_message(self, mock_generator, make_chat_request):
        """chat_post should return the final completion message."""
        request = make_chat_request(content="Hello")
        mock_response = {"choices": [{"message": {"content": "Hi there!"}}]}

        async def mock_gen():
            yield mock_response

        mock_generator.return_value = mock_gen()

        result = await chat.chat_post(request=request, client="test_client")

        assert result == mock_response
        mock_generator.assert_called_once_with("test_client", request, "completions")

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chat.completion_generator")
    async def test_chat_post_iterates_through_all_chunks(self, mock_generator, make_chat_request):
        """chat_post should iterate through all chunks and return last."""
        request = make_chat_request(content="Hello")

        async def mock_gen():
            yield "chunk1"
            yield "chunk2"
            yield {"final": "response"}

        mock_generator.return_value = mock_gen()

        result = await chat.chat_post(request=request, client="test_client")

        assert result == {"final": "response"}

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chat.completion_generator")
    async def test_chat_post_uses_default_client(self, mock_generator, make_chat_request):
        """chat_post should use 'server' as default client."""
        request = make_chat_request()

        async def mock_gen():
            yield {"response": "data"}

        mock_generator.return_value = mock_gen()

        await chat.chat_post(request=request, client="server")

        mock_generator.assert_called_once_with("server", request, "completions")


class TestChatStream:
    """Tests for the chat_stream endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chat.completion_generator")
    async def test_chat_stream_returns_streaming_response(self, mock_generator, make_chat_request):
        """chat_stream should return a StreamingResponse."""
        request = make_chat_request(content="Hello")

        async def mock_gen():
            yield b"chunk1"
            yield b"chunk2"

        mock_generator.return_value = mock_gen()

        result = await chat.chat_stream(request=request, client="test_client")

        assert isinstance(result, StreamingResponse)
        assert result.media_type == "application/octet-stream"

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chat.completion_generator")
    async def test_chat_stream_calls_generator_with_streams_mode(self, mock_generator, make_chat_request):
        """chat_stream should call generator with 'streams' mode."""
        request = make_chat_request()

        async def mock_gen():
            yield b"data"

        mock_generator.return_value = mock_gen()

        await chat.chat_stream(request=request, client="test_client")

        mock_generator.assert_called_once_with("test_client", request, "streams")


class TestChatHistoryClean:
    """Tests for the chat_history_clean endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chatbot.chatbot_graph")
    async def test_chat_history_clean_success(self, mock_graph):
        """chat_history_clean should clear history and return confirmation."""
        mock_graph.update_state = MagicMock(return_value=None)

        result = await chat.chat_history_clean(client="test_client")

        assert len(result) == 1
        assert "forgotten" in result[0].content
        assert result[0].role == "system"

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chatbot.chatbot_graph")
    async def test_chat_history_clean_updates_state_correctly(self, mock_graph):
        """chat_history_clean should update state with correct values."""
        mock_graph.update_state = MagicMock(return_value=None)

        await chat.chat_history_clean(client="test_client")

        call_args = mock_graph.update_state.call_args
        values = call_args[1]["values"]

        assert "messages" in values
        assert values["cleaned_messages"] == []
        assert values["context_input"] == ""
        assert values["documents"] == {}
        assert values["final_response"] == {}

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chatbot.chatbot_graph")
    async def test_chat_history_clean_handles_key_error(self, mock_graph):
        """chat_history_clean should handle KeyError gracefully."""
        mock_graph.update_state = MagicMock(side_effect=KeyError("thread not found"))

        result = await chat.chat_history_clean(client="nonexistent_client")

        assert len(result) == 1
        assert "no history" in result[0].content
        assert result[0].role == "system"

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chatbot.chatbot_graph")
    async def test_chat_history_clean_uses_correct_thread_id(self, mock_graph):
        """chat_history_clean should use client as thread_id."""
        mock_graph.update_state = MagicMock(return_value=None)

        await chat.chat_history_clean(client="my_client_id")

        call_args = mock_graph.update_state.call_args
        # config is passed as keyword argument, RunnableConfig is dict-like
        config = call_args.kwargs["config"]

        assert config["configurable"]["thread_id"] == "my_client_id"


class TestChatHistoryReturn:
    """Tests for the chat_history_return endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chatbot.chatbot_graph")
    @patch("server.api.v1.chat.convert_to_openai_messages")
    async def test_chat_history_return_success(self, mock_convert, mock_graph):
        """chat_history_return should return chat messages."""
        mock_messages = [
            MagicMock(content="Hello", role="user"),
            MagicMock(content="Hi there", role="assistant"),
        ]
        mock_state = MagicMock()
        mock_state.values = {"messages": mock_messages}
        mock_graph.get_state = MagicMock(return_value=mock_state)
        mock_convert.return_value = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        result = await chat.chat_history_return(client="test_client")

        assert len(result) == 2
        mock_convert.assert_called_once_with(mock_messages)

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chatbot.chatbot_graph")
    async def test_chat_history_return_handles_key_error(self, mock_graph):
        """chat_history_return should handle KeyError gracefully."""
        mock_graph.get_state = MagicMock(side_effect=KeyError("thread not found"))

        result = await chat.chat_history_return(client="nonexistent_client")

        assert len(result) == 1
        assert "no history" in result[0].content
        assert result[0].role == "system"

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chatbot.chatbot_graph")
    async def test_chat_history_return_uses_correct_thread_id(self, mock_graph):
        """chat_history_return should use client as thread_id."""
        mock_state = MagicMock()
        mock_state.values = {"messages": []}
        mock_graph.get_state = MagicMock(return_value=mock_state)

        with patch("server.api.v1.chat.convert_to_openai_messages", return_value=[]):
            await chat.chat_history_return(client="my_client_id")

        call_args = mock_graph.get_state.call_args
        # config is passed as keyword argument, RunnableConfig is dict-like
        config = call_args.kwargs["config"]

        assert config["configurable"]["thread_id"] == "my_client_id"

    @pytest.mark.asyncio
    @patch("server.api.v1.chat.chatbot.chatbot_graph")
    @patch("server.api.v1.chat.convert_to_openai_messages")
    async def test_chat_history_return_empty_history(self, mock_convert, mock_graph):
        """chat_history_return should handle empty history."""
        mock_state = MagicMock()
        mock_state.values = {"messages": []}
        mock_graph.get_state = MagicMock(return_value=mock_state)
        mock_convert.return_value = []

        result = await chat.chat_history_return(client="test_client")

        assert result == []
