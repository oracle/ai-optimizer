"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

from typing import Any, Dict
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from conftest import TEST_HEADERS, TEST_BAD_HEADERS
from langchain_core.messages import ChatMessage
from common.schema import ChatRequest


#############################################################################
# Test AuthN required and Valid
#############################################################################
class TestNoAuthEndpoints:
    """Test endpoints without AuthN"""

    test_cases = [
        pytest.param(
            {"endpoint": "/v1/chat/completions", "method": "post"},
            id="chat_post",
        ),
        pytest.param(
            {"endpoint": "/v1/chat/streams", "method": "post"},
            id="chat_stream",
        ),
        pytest.param(
            {"endpoint": "/v1/chat/history", "method": "patch"},
            id="chat_history_clean",
        ),
        pytest.param(
            {"endpoint": "/v1/chat/history", "method": "get"},
            id="chat_history_return",
        ),
    ]

    @pytest.mark.parametrize("test_case", test_cases)
    def test_no_auth(self, client: TestClient, test_case: Dict[str, Any]) -> None:
        """Testing for required AuthN"""
        response = getattr(client, test_case["method"])(test_case["endpoint"])
        assert response.status_code == 403
        response = getattr(client, test_case["method"])(test_case["endpoint"], headers=TEST_BAD_HEADERS)
        assert response.status_code == 401


#############################################################################
# Test Chat Completions
#############################################################################
class TestChatCompletions:
    """Test chat completion endpoints"""

    def test_chat_completion_valid(self, client: TestClient):
        """Test valid chat completion request"""
        with (
            patch("server.utils.models.get_client", return_value=MagicMock()),
            patch("server.agents.chatbot.chatbot_graph") as mock_graph,
        ):
            # Create a mock response for the final_response
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
            
            # Set up the mock to return the response
            mock_graph.astream_events.return_value.__aiter__.return_value = [
                {
                    "event": "on_chat_model_stream",
                    "data": {
                        "chunk": MagicMock(content="Test response"),
                        "output": {"final_response": mock_response},
                    },
                    "metadata": {"langgraph_triggers": [], "langgraph_node": ""},
                }
            ]

            request = ChatRequest(
                messages=[ChatMessage(content="Hello", role="user")],
                model="test-model",
                temperature=1.0,
                max_completion_tokens=256,
            )

            response = client.post("/v1/chat/completions", headers=TEST_HEADERS, json=request.model_dump())
            assert response.status_code == 200
            assert "choices" in response.json()
            assert response.json()["choices"][0]["message"]["content"] == "Test response"

    def test_chat_completion_model_error(self, client: TestClient):
        """Test chat completion with model initialization error"""
        with patch("server.utils.models.get_client", return_value=None):
            request = ChatRequest(
                messages=[ChatMessage(content="Hello", role="user")],
                model="invalid-model",
                temperature=1.0,
                max_completion_tokens=256,
            )

            response = client.post("/v1/chat/completions", headers=TEST_HEADERS, json=request.model_dump())
            assert response.status_code == 200
            assert (
                "I'm sorry, I'm unable to initialise the Language Model"
                in response.json()["choices"][0]["message"]["content"]
            )


#############################################################################
# Test Chat Streaming
#############################################################################
class TestChatStreaming:
    """Test chat streaming endpoints"""

    def test_chat_stream_valid(self, client: TestClient):
        """Test valid chat stream request"""
        with (
            patch("server.utils.models.get_client", return_value=MagicMock()),
            patch("server.agents.chatbot.chatbot_graph") as mock_graph,
        ):
            # Set up the mock to return streaming chunks
            mock_graph.astream_events.return_value.__aiter__.return_value = [
                {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": MagicMock(content="Test streaming"), "output": {}},
                    "metadata": {"langgraph_triggers": [], "langgraph_node": ""},
                },
                {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": MagicMock(content=" response"), "output": {}},
                    "metadata": {"langgraph_triggers": [], "langgraph_node": ""},
                }
            ]

            request = ChatRequest(
                messages=[ChatMessage(content="Hello", role="user")],
                model="test-model",
                temperature=1.0,
                max_completion_tokens=256,
                streaming=True,
            )

            response = client.post("/v1/chat/streams", headers=TEST_HEADERS, json=request.model_dump())
            assert response.status_code == 200
            content = b"".join(response.iter_bytes())
            assert b"Test streaming response" in content


#############################################################################
# Test Chat History
#############################################################################
class TestChatHistory:
    """Test chat history endpoints"""

    def test_chat_history_valid(self, client: TestClient):
        """Test valid chat history request"""
        with patch("server.agents.chatbot.chatbot_graph") as mock_graph:
            mock_graph.get_state.return_value.values = {
                "messages": [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there!"}]
            }
            response = client.get("/v1/chat/history", headers=TEST_HEADERS)
            assert response.status_code == 200
            history = response.json()
            assert len(history) == 2
            assert history[0]["role"] == "user"
            assert history[0]["content"] == "Hello"

    def test_chat_history_clean(self, client: TestClient):
        """Test chat history with no history"""
        with patch("server.agents.chatbot.chatbot_graph") as mock_graph:
            mock_graph.get_state.side_effect = KeyError()
            response = client.patch("/v1/chat/history", headers=TEST_HEADERS)
            assert response.status_code == 200
            history = response.json()
            assert len(history) == 1
            assert history[0]["role"] == "system"
            assert "forgotten" in history[0]["content"].lower()

    def test_chat_history_empty(self, client: TestClient):
        """Test chat history with no history"""
        with patch("server.agents.chatbot.chatbot_graph") as mock_graph:
            mock_graph.get_state.side_effect = KeyError()
            response = client.get("/v1/chat/history", headers=TEST_HEADERS)
            assert response.status_code == 200
            history = response.json()
            assert len(history) == 1
            assert history[0]["role"] == "system"
            assert "no history" in history[0]["content"].lower()
