"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/chat.py
Tests for chat completion utility functions.
"""

from unittest.mock import patch, MagicMock
import pytest

from server.api.utils import chat as utils_chat
from server.api.utils.models import UnknownModelError
from common.schema import ChatRequest


class TestCompletionGenerator:
    """Tests for the completion_generator function."""

    @pytest.mark.asyncio
    @patch("server.api.utils.chat.utils_settings.get_client")
    @patch("server.api.utils.chat.utils_oci.get")
    @patch("server.api.utils.chat.utils_models.get_litellm_config")
    @patch("server.api.utils.chat.chatbot_graph")
    async def test_completion_generator_completions_mode(
        self,
        mock_graph,
        mock_get_config,
        mock_oci_get,
        mock_get_client,
        make_settings,
        make_chat_request,
        make_oci_config,
    ):
        """completion_generator should yield final response in completions mode."""
        mock_get_client.return_value = make_settings()
        mock_oci_get.return_value = make_oci_config()
        mock_get_config.return_value = {"model": "gpt-4o-mini"}

        async def mock_astream(**_kwargs):
            yield {"completion": {"choices": [{"message": {"content": "Hello!"}}]}}

        mock_graph.astream = mock_astream

        request = make_chat_request(content="Hi")
        results = []
        async for output in utils_chat.completion_generator("test_client", request, "completions"):
            results.append(output)

        assert len(results) == 1
        assert results[0]["choices"][0]["message"]["content"] == "Hello!"

    @pytest.mark.asyncio
    @patch("server.api.utils.chat.utils_settings.get_client")
    @patch("server.api.utils.chat.utils_oci.get")
    @patch("server.api.utils.chat.utils_models.get_litellm_config")
    @patch("server.api.utils.chat.chatbot_graph")
    async def test_completion_generator_streams_mode(
        self,
        mock_graph,
        mock_get_config,
        mock_oci_get,
        mock_get_client,
        make_settings,
        make_chat_request,
        make_oci_config,
    ):
        """completion_generator should yield stream chunks in streams mode."""
        mock_get_client.return_value = make_settings()
        mock_oci_get.return_value = make_oci_config()
        mock_get_config.return_value = {"model": "gpt-4o-mini"}

        async def mock_astream(**_kwargs):
            yield {"stream": "Hello"}
            yield {"stream": " World"}
            yield {"completion": {"choices": []}}

        mock_graph.astream = mock_astream

        request = make_chat_request(content="Hi")
        results = []
        async for output in utils_chat.completion_generator("test_client", request, "streams"):
            results.append(output)

        # Should have 3 outputs: 2 stream chunks + stream_finished
        assert len(results) == 3
        assert results[0] == b"Hello"
        assert results[1] == b" World"
        assert results[2] == "[stream_finished]"

    @pytest.mark.asyncio
    @patch("server.api.utils.chat.utils_settings.get_client")
    @patch("server.api.utils.chat.utils_oci.get")
    @patch("server.api.utils.chat.utils_models.get_litellm_config")
    @patch("server.api.utils.chat.completion")
    async def test_completion_generator_unknown_model_error(
        self,
        mock_completion,
        mock_get_config,
        mock_oci_get,
        mock_get_client,
        make_settings,
        make_chat_request,
        make_oci_config,
    ):
        """completion_generator should return error response on UnknownModelError."""
        mock_get_client.return_value = make_settings()
        mock_oci_get.return_value = make_oci_config()
        mock_get_config.side_effect = UnknownModelError("Model not found")

        mock_error_response = MagicMock()
        mock_error_response.choices = [MagicMock()]
        mock_error_response.choices[0].message.content = "I'm unable to initialise the Language Model."
        mock_completion.return_value = mock_error_response

        request = make_chat_request(content="Hi")
        results = []
        async for output in utils_chat.completion_generator("test_client", request, "completions"):
            results.append(output)

        assert len(results) == 1
        mock_completion.assert_called_once()
        # Verify mock_response was used
        call_kwargs = mock_completion.call_args.kwargs
        assert "mock_response" in call_kwargs

    @pytest.mark.asyncio
    @patch("server.api.utils.chat.utils_settings.get_client")
    @patch("server.api.utils.chat.utils_oci.get")
    @patch("server.api.utils.chat.utils_models.get_litellm_config")
    @patch("server.api.utils.chat.chatbot_graph")
    async def test_completion_generator_uses_request_model(
        self, mock_graph, mock_get_config, mock_oci_get, mock_get_client, make_settings, make_oci_config
    ):
        """completion_generator should use model from request if provided."""
        mock_get_client.return_value = make_settings()
        mock_oci_get.return_value = make_oci_config()
        mock_get_config.return_value = {"model": "claude-3"}

        async def mock_astream(**_kwargs):
            yield {"completion": {}}

        mock_graph.astream = mock_astream

        request = ChatRequest(messages=[{"role": "user", "content": "Hi"}], model="claude-3")
        async for _ in utils_chat.completion_generator("test_client", request, "completions"):
            pass

        # get_litellm_config should be called with the request model
        call_args = mock_get_config.call_args[0]
        assert call_args[0]["model"] == "claude-3"

    @pytest.mark.asyncio
    @patch("server.api.utils.chat.utils_settings.get_client")
    @patch("server.api.utils.chat.utils_oci.get")
    @patch("server.api.utils.chat.utils_models.get_litellm_config")
    @patch("server.api.utils.chat.chatbot_graph")
    async def test_completion_generator_uses_settings_model_when_not_in_request(
        self,
        mock_graph,
        mock_get_config,
        mock_oci_get,
        mock_get_client,
        make_settings,
        make_chat_request,
        make_oci_config,
        make_ll_settings,
    ):
        """completion_generator should use model from settings when not in request."""
        settings = make_settings(ll_model=make_ll_settings(model="gpt-4-turbo"))
        mock_get_client.return_value = settings
        mock_oci_get.return_value = make_oci_config()
        mock_get_config.return_value = {"model": "gpt-4-turbo"}

        async def mock_astream(**_kwargs):
            yield {"completion": {}}

        mock_graph.astream = mock_astream

        request = make_chat_request(content="Hi")  # No model specified
        async for _ in utils_chat.completion_generator("test_client", request, "completions"):
            pass

        # get_litellm_config should be called with settings model
        call_args = mock_get_config.call_args[0]
        assert call_args[0]["model"] == "gpt-4-turbo"

    @pytest.mark.asyncio
    @patch("server.api.utils.chat.utils_settings.get_client")
    @patch("server.api.utils.chat.utils_oci.get")
    @patch("server.api.utils.chat.utils_models.get_litellm_config")
    @patch("server.api.utils.chat.utils_databases.get_client_database")
    @patch("server.api.utils.chat.utils_models.get_client_embed")
    @patch("server.api.utils.chat.chatbot_graph")
    async def test_completion_generator_with_vector_search_enabled(
        self,
        mock_graph,
        mock_get_embed,
        mock_get_db,
        mock_get_config,
        mock_oci_get,
        mock_get_client,
        make_settings,
        make_chat_request,
        make_oci_config,
    ):
        """completion_generator should setup db connection when vector search enabled."""
        settings = make_settings()
        settings.tools_enabled = ["Vector Search"]
        mock_get_client.return_value = settings
        mock_oci_get.return_value = make_oci_config()
        mock_get_config.return_value = {"model": "gpt-4o-mini"}

        mock_db = MagicMock()
        mock_db.connection = MagicMock()
        mock_get_db.return_value = mock_db
        mock_get_embed.return_value = MagicMock()

        async def mock_astream(**_kwargs):
            yield {"completion": {}}

        mock_graph.astream = mock_astream

        request = make_chat_request(content="Hi")
        async for _ in utils_chat.completion_generator("test_client", request, "completions"):
            pass

        mock_get_db.assert_called_once_with("test_client", False)
        mock_get_embed.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.utils.chat.utils_settings.get_client")
    @patch("server.api.utils.chat.utils_oci.get")
    @patch("server.api.utils.chat.utils_models.get_litellm_config")
    @patch("server.api.utils.chat.chatbot_graph")
    async def test_completion_generator_passes_correct_config(
        self,
        mock_graph,
        mock_get_config,
        mock_oci_get,
        mock_get_client,
        make_settings,
        make_chat_request,
        make_oci_config,
    ):
        """completion_generator should pass correct config to chatbot_graph."""
        settings = make_settings()
        mock_get_client.return_value = settings
        mock_oci_get.return_value = make_oci_config()
        mock_get_config.return_value = {"model": "gpt-4o-mini"}

        captured_kwargs = {}

        async def mock_astream(**kwargs):
            captured_kwargs.update(kwargs)
            yield {"completion": {}}

        mock_graph.astream = mock_astream

        request = make_chat_request(content="Test message")
        async for _ in utils_chat.completion_generator("test_client", request, "completions"):
            pass

        assert captured_kwargs["stream_mode"] == "custom"
        assert captured_kwargs["config"]["configurable"]["thread_id"] == "test_client"
        assert captured_kwargs["config"]["metadata"]["streaming"] is False

    @pytest.mark.asyncio
    @patch("server.api.utils.chat.utils_settings.get_client")
    @patch("server.api.utils.chat.utils_oci.get")
    @patch("server.api.utils.chat.utils_models.get_litellm_config")
    @patch("server.api.utils.chat.chatbot_graph")
    async def test_completion_generator_streaming_metadata(
        self,
        mock_graph,
        mock_get_config,
        mock_oci_get,
        mock_get_client,
        make_settings,
        make_chat_request,
        make_oci_config,
    ):
        """completion_generator should set streaming=True for streams mode."""
        mock_get_client.return_value = make_settings()
        mock_oci_get.return_value = make_oci_config()
        mock_get_config.return_value = {"model": "gpt-4o-mini"}

        captured_kwargs = {}

        async def mock_astream(**kwargs):
            captured_kwargs.update(kwargs)
            yield {"completion": {}}

        mock_graph.astream = mock_astream

        request = make_chat_request(content="Test")
        async for _ in utils_chat.completion_generator("test_client", request, "streams"):
            pass

        assert captured_kwargs["config"]["metadata"]["streaming"] is True


class TestLoggerConfiguration:
    """Tests for logger configuration."""

    def test_logger_exists(self):
        """Logger should be configured."""
        assert hasattr(utils_chat, "logger")

    def test_logger_name(self):
        """Logger should have correct name."""
        assert utils_chat.logger.name == "api.utils.chat"
