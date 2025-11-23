"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error import-outside-toplevel

from unittest.mock import patch, MagicMock
import warnings

import pytest
from langchain_core.messages import ChatMessage
from common.schema import ChatRequest


#############################################################################
# Test AuthN required and Valid
#############################################################################
class TestInvalidAuthEndpoints:
    """Test endpoints without Headers and Invalid AuthN"""

    @pytest.mark.parametrize(
        "auth_type, status_code",
        [
            pytest.param("no_auth", 403, id="no_auth"),
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
    def test_endpoints(self, client, auth_headers, endpoint, api_method, auth_type, status_code):
        """Test endpoints require valide authentication."""
        response = getattr(client, api_method)(endpoint, headers=auth_headers[auth_type])
        assert response.status_code == status_code


#############################################################################
# Endpoints Test
#############################################################################
class TestEndpoints:
    """Test Endpoints"""

    def test_chat_completion_no_model(self, client, auth_headers):
        """Test no model chat completion request"""
        with warnings.catch_warnings():
            # Enable the catch_warnings context
            warnings.simplefilter("ignore", category=UserWarning)
            request = ChatRequest(
                messages=[ChatMessage(content="Hello", role="user")],
                model="test-provider/test-model",
                temperature=1.0,
                max_tokens=256,
            )
            response = client.post(
                "/v1/chat/completions", headers=auth_headers["valid_auth"], json=request.model_dump()
            )

        assert response.status_code == 200
        assert "choices" in response.json()
        assert (
            response.json()["choices"][0]["message"]["content"]
            == "I'm unable to initialise the Language Model. Please refresh the application."
        )

    def test_chat_completion_valid_mock(self, client, auth_headers):
        """Test valid chat completion request"""
        # Create the mock response
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

        # Mock the requests.post call
        with patch.object(client, "post") as mock_post:
            # Configure the mock response
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
                "/v1/chat/completions", headers=auth_headers["valid_auth"], json=request.model_dump()
            )
            assert response.status_code == 200
            assert "choices" in response.json()
            assert response.json()["choices"][0]["message"]["content"] == "Test response"

    def test_chat_stream_valid_mock(self, client, auth_headers):
        """Test valid chat stream request"""
        # Create the mock streaming response
        mock_streaming_response = MagicMock()
        mock_streaming_response.status_code = 200
        mock_streaming_response.iter_bytes.return_value = [b"Test streaming", b" response"]

        # Mock the requests.post call
        with patch.object(client, "post") as mock_post:
            mock_post.return_value = mock_streaming_response

            request = ChatRequest(
                messages=[ChatMessage(content="Hello", role="user")],
                model="test-provider/test-model",
                temperature=1.0,
                max_tokens=256,
                streaming=True,
            )

            response = client.post("/v1/chat/streams", headers=auth_headers["valid_auth"], json=request.model_dump())
            assert response.status_code == 200
            content = b"".join(response.iter_bytes())
            assert b"Test streaming response" in content

    def test_chat_history_valid_mock(self, client, auth_headers):
        """Test valid chat history request"""
        # Create the mock history response
        mock_history = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there!"}]

        # Mock the requests.get call
        with patch.object(client, "get") as mock_get:
            # Configure the mock response
            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json.return_value = mock_history
            mock_get.return_value = mock_response_obj

            response = client.get("/v1/chat/history", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            history = response.json()
            assert len(history) == 2
            assert history[0]["role"] == "user"
            assert history[0]["content"] == "Hello"

    def test_chat_history_clean(self, client, auth_headers):
        """Test chat history with no history"""
        with patch("server.agents.chatbot.chatbot_graph") as mock_graph:
            mock_graph.get_state.side_effect = KeyError()
            response = client.patch("/v1/chat/history", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            history = response.json()
            assert len(history) == 1
            assert history[0]["role"] == "system"
            assert "forgotten" in history[0]["content"].lower()

    def test_chat_history_empty(self, client, auth_headers):
        """Test chat history with no history"""
        with patch("server.agents.chatbot.chatbot_graph") as mock_graph:
            mock_graph.get_state.side_effect = KeyError()
            response = client.get("/v1/chat/history", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            history = response.json()
            assert len(history) == 1
            assert history[0]["role"] == "system"
            assert "no history" in history[0]["content"].lower()

    def test_chat_history_clears_rag_context(self, client, auth_headers):
        """Test that clearing chat history also clears RAG document context

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
            # Create a mock state snapshot that simulates a conversation with RAG documents
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

            # Setup the mock to return our state
            mock_graph.get_state.return_value = mock_state
            mock_graph.update_state.return_value = None

            # Call the endpoint to clear history
            response = client.patch("/v1/chat/history", headers=auth_headers["valid_auth"])

            # Verify the response
            assert response.status_code == 200
            history = response.json()
            assert len(history) == 1
            assert history[0]["role"] == "system"
            assert "forgotten" in history[0]["content"].lower()

            # Verify update_state was called with ALL state fields cleared
            mock_graph.update_state.assert_called_once()
            call_args = mock_graph.update_state.call_args

            # Check that values dict includes all OptimizerState fields
            values = call_args.kwargs["values"]
            assert "messages" in values  # Should have RemoveMessage
            assert "cleaned_messages" in values
            assert values["cleaned_messages"] == []
            assert "context_input" in values
            assert values["context_input"] == ""
            assert "documents" in values
            assert values["documents"] == {}
            assert "final_response" in values
            assert values["final_response"] == {}
