"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

from unittest.mock import patch, MagicMock
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
            pytest.param("/v1/chat/history", "get", id="chat_history"),
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
        request = ChatRequest(
            messages=[ChatMessage(content="Hello", role="user")],
            model="test-model",
            temperature=1.0,
            max_completion_tokens=256,
        )

        response = client.post("/v1/chat/completions", headers=auth_headers["valid_auth"], json=request.model_dump())
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
            "model": "test-model",
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
                model="test-model",
                temperature=1.0,
                max_completion_tokens=256,
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
                model="test-model",
                temperature=1.0,
                max_completion_tokens=256,
                streaming=True,
            )

            response = client.post("/v1/chat/streams", headers=auth_headers["valid_auth"], json=request.model_dump())
            assert response.status_code == 200
            content = b"".join(response.iter_bytes())
            assert b"Test streaming response" in content

    def test_chat_history_empty(self, client, auth_headers):
        """Test no model chat completion request"""
        response = client.get("/v1/chat/history", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        history = response.json()
        assert history[0]["role"] == "system"
        assert history[0]["content"] == "I'm sorry, I have no history of this conversation"

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
