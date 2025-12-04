"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/chat.py

Tests the chat completion endpoints including authentication, completion requests,
streaming, and history management.
"""
# spell-checker: disable
# pylint: disable=protected-access too-few-public-methods

from unittest.mock import patch, MagicMock
import warnings

import pytest
from langchain_core.messages import ChatMessage
from common.schema import ChatRequest


class TestChatAuthenticationRequired:
    """Test that chat endpoints require valid authentication."""

    @pytest.mark.parametrize(
        "auth_type, status_code",
        [
            pytest.param("no_auth", 401, id="no_auth"),
            pytest.param("invalid_auth", 401, id="invalid_auth"),
        ],
    )
    @pytest.mark.parametrize(
        "endpoint, api_method",
        [
            pytest.param("/v1/chat/completions", "post", id="chat_post"),
            pytest.param("/v1/chat/streams", "post", id="chat_stream"),
            pytest.param("/v1/chat/history", "patch", id="chat_history_clean"),
            pytest.param("/v1/chat/history", "get", id="chat_history_return"),
        ],
    )
    def test_invalid_auth_endpoints(
        self, client, test_client_auth_headers, endpoint, api_method, auth_type, status_code
    ):
        """Test endpoints require valid authentication."""
        response = getattr(client, api_method)(endpoint, headers=test_client_auth_headers[auth_type])
        assert response.status_code == status_code


class TestChatCompletions:
    """Integration tests for chat completion endpoints."""

    def test_chat_completion_no_model(self, client, test_client_auth_headers):
        """Test chat completion request when no model is configured."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning)
            request = ChatRequest(
                messages=[ChatMessage(content="Hello", role="user")],
                model="test-provider/test-model",
                temperature=1.0,
                max_tokens=256,
            )
            response = client.post(
                "/v1/chat/completions", headers=test_client_auth_headers["valid_auth"], json=request.model_dump()
            )

        assert response.status_code == 200
        assert "choices" in response.json()
        assert (
            response.json()["choices"][0]["message"]["content"]
            == "I'm unable to initialise the Language Model. Please refresh the application."
        )

    def test_chat_completion_valid_mock(self, client, test_client_auth_headers):
        """Test valid chat completion request with mocked response."""
        mock_response = {
            "id": "test-id",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Test response"},
                    "index": 0,
                    "finish_reason": "stop",
                }
            ],
            "created": 1234567890,
            "model": "test-provider/test-model",
            "object": "chat.completion",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

        with patch.object(client, "post") as mock_post:
            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json.return_value = mock_response
            mock_post.return_value = mock_response_obj

            request = ChatRequest(
                messages=[ChatMessage(content="Hello", role="user")],
                model="test-provider/test-model",
                temperature=1.0,
                max_tokens=256,
            )

            response = client.post(
                "/v1/chat/completions", headers=test_client_auth_headers["valid_auth"], json=request.model_dump()
            )
            assert response.status_code == 200
            assert "choices" in response.json()
            assert response.json()["choices"][0]["message"]["content"] == "Test response"


class TestChatStreaming:
    """Integration tests for chat streaming endpoint."""

    def test_chat_stream_valid_mock(self, client, test_client_auth_headers):
        """Test valid chat stream request with mocked response."""
        mock_streaming_response = MagicMock()
        mock_streaming_response.status_code = 200
        mock_streaming_response.iter_bytes.return_value = [b"Test streaming", b" response"]

        with patch.object(client, "post") as mock_post:
            mock_post.return_value = mock_streaming_response

            request = ChatRequest(
                messages=[ChatMessage(content="Hello", role="user")],
                model="test-provider/test-model",
                temperature=1.0,
                max_tokens=256,
                streaming=True,
            )

            response = client.post(
                "/v1/chat/streams", headers=test_client_auth_headers["valid_auth"], json=request.model_dump()
            )
            assert response.status_code == 200
            content = b"".join(response.iter_bytes())
            assert b"Test streaming response" in content


class TestChatHistory:
    """Integration tests for chat history management endpoints."""

    def test_chat_history_valid_mock(self, client, test_client_auth_headers):
        """Test retrieving chat history with mocked response."""
        mock_history = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there!"}]

        with patch.object(client, "get") as mock_get:
            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json.return_value = mock_history
            mock_get.return_value = mock_response_obj

            response = client.get("/v1/chat/history", headers=test_client_auth_headers["valid_auth"])
            assert response.status_code == 200
            history = response.json()
            assert len(history) == 2
            assert history[0]["role"] == "user"
            assert history[0]["content"] == "Hello"

    def test_chat_history_clean(self, client, test_client_auth_headers):
        """Test clearing chat history when no prior history exists."""
        with patch("server.agents.chatbot.chatbot_graph") as mock_graph:
            mock_graph.get_state.side_effect = KeyError()
            response = client.patch("/v1/chat/history", headers=test_client_auth_headers["valid_auth"])
            assert response.status_code == 200
            history = response.json()
            assert len(history) == 1
            assert history[0]["role"] == "system"
            assert "forgotten" in history[0]["content"].lower()

    def test_chat_history_empty(self, client, test_client_auth_headers):
        """Test retrieving chat history when no history exists."""
        with patch("server.agents.chatbot.chatbot_graph") as mock_graph:
            mock_graph.get_state.side_effect = KeyError()
            response = client.get("/v1/chat/history", headers=test_client_auth_headers["valid_auth"])
            assert response.status_code == 200
            history = response.json()
            assert len(history) == 1
            assert history[0]["role"] == "system"
            assert "no history" in history[0]["content"].lower()

    def test_chat_history_clears_rag_context(self, client, test_client_auth_headers):
        """Test that clearing chat history also clears RAG document context.

        This test ensures that when PATCH /v1/chat/history is called,
        all OptimizerState fields are cleared including:
        - messages (conversation history)
        - cleaned_messages (filtered messages)
        - context_input (contextualized query)
        - documents (RAG document context)
        - final_response (completion response)

        This prevents RAG documents from persisting across conversation resets.
        """
        with patch("server.agents.chatbot.chatbot_graph") as mock_graph:
            mock_state = MagicMock()
            mock_state.values = {
                "messages": [
                    ChatMessage(content="What is RAG?", role="user"),
                    ChatMessage(content="RAG stands for Retrieval-Augmented Generation.", role="assistant"),
                ],
                "cleaned_messages": [
                    ChatMessage(content="What is RAG?", role="user"),
                ],
                "context_input": "What is Retrieval-Augmented Generation?",
                "documents": {
                    "doc1": {"content": "RAG combines retrieval with generation..."},
                    "doc2": {"content": "Vector search enables semantic retrieval..."},
                },
                "final_response": {
                    "id": "test-response",
                    "choices": [{"message": {"content": "RAG stands for..."}}],
                },
            }

            mock_graph.get_state.return_value = mock_state
            mock_graph.update_state.return_value = None

            response = client.patch("/v1/chat/history", headers=test_client_auth_headers["valid_auth"])

            assert response.status_code == 200
            history = response.json()
            assert len(history) == 1
            assert history[0]["role"] == "system"
            assert "forgotten" in history[0]["content"].lower()

            mock_graph.update_state.assert_called_once()
            call_args = mock_graph.update_state.call_args

            values = call_args.kwargs["values"]
            assert "messages" in values
            assert "cleaned_messages" in values
            assert values["cleaned_messages"] == []
            assert "context_input" in values
            assert values["context_input"] == ""
            assert "documents" in values
            assert values["documents"] == {}
            assert "final_response" in values
            assert values["final_response"] == {}
