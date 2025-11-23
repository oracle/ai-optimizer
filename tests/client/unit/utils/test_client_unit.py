"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from client.utils.client import Client


#############################################################################
# Test Client Initialization
#############################################################################
class TestClientInitialization:
    """Test Client class initialization"""

    def test_client_init_with_defaults(self, app_server, monkeypatch):
        """Test Client initialization with default parameters"""
        assert app_server is not None

        # Mock httpx.Client to avoid actual HTTP calls
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        monkeypatch.setattr(httpx, "Client", lambda: mock_client)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings)

        assert client.server_url == "http://localhost:8000"
        assert client.settings == settings
        assert client.agent == "chatbot"
        assert client.request_defaults["headers"]["Authorization"] == "Bearer test-key"
        assert client.request_defaults["headers"]["Client"] == "test-client"

    def test_client_init_with_custom_agent(self, app_server, monkeypatch):
        """Test Client initialization with custom agent"""
        assert app_server is not None

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        monkeypatch.setattr(httpx, "Client", lambda: mock_client)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings, agent="custom-agent")

        assert client.agent == "custom-agent"

    def test_client_init_with_timeout(self, app_server, monkeypatch):
        """Test Client initialization with custom timeout"""
        assert app_server is not None

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        monkeypatch.setattr(httpx, "Client", lambda: mock_client)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings, timeout=60.0)

        assert client.request_defaults["timeout"] == 60.0

    def test_client_init_patch_success(self, app_server, monkeypatch):
        """Test Client initialization with successful PATCH request"""
        assert app_server is not None

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(return_value=mock_response)

        monkeypatch.setattr(httpx, "Client", lambda: mock_client)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings)

        # Should have called PATCH method
        assert mock_client.request.called
        first_call_method = mock_client.request.call_args_list[0][1]["method"]
        assert first_call_method == "PATCH"

    def test_client_init_patch_fails_post_succeeds(self, app_server, monkeypatch):
        """Test Client initialization when PATCH fails but POST succeeds"""
        assert app_server is not None

        # First call (PATCH) returns 400, second call (POST) returns 200
        mock_responses = [
            MagicMock(status_code=400, text="PATCH failed"),
            MagicMock(status_code=200, text="POST success"),
        ]

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = MagicMock(side_effect=mock_responses)

        monkeypatch.setattr(httpx, "Client", lambda: mock_client)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings)

        # Should have called both PATCH and POST
        assert mock_client.request.call_count == 2
        assert client is not None

    def test_client_init_with_retry_on_http_error(self, app_server, monkeypatch):
        """Test Client initialization with retry on HTTP error"""
        assert app_server is not None

        # First two calls fail, third succeeds
        call_count = 0

        def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.HTTPError("Connection failed")
            response = MagicMock()
            response.status_code = 200
            return response

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = mock_request

        monkeypatch.setattr(httpx, "Client", lambda: mock_client)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings)

        # Should have retried and succeeded
        assert call_count == 3
        assert client is not None

    def test_client_init_max_retries_exceeded(self, app_server, monkeypatch):
        """Test Client initialization when max retries exceeded"""
        assert app_server is not None

        def mock_request(*args, **kwargs):
            raise httpx.HTTPError("Connection failed")

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request = mock_request

        monkeypatch.setattr(httpx, "Client", lambda: mock_client)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        # Should raise HTTPError after max retries
        with pytest.raises(httpx.HTTPError):
            Client(server, settings)


#############################################################################
# Test Client Streaming
#############################################################################
class TestClientStreaming:
    """Test Client streaming functionality"""

    @pytest.mark.asyncio
    async def test_stream_text_message(self, app_server, monkeypatch):
        """Test streaming with text message"""
        assert app_server is not None

        # Mock successful initialization
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_sync_client = MagicMock()
        mock_sync_client.__enter__ = MagicMock(return_value=mock_sync_client)
        mock_sync_client.__exit__ = MagicMock(return_value=False)
        mock_sync_client.request = MagicMock(return_value=mock_response)

        monkeypatch.setattr(httpx, "Client", lambda: mock_sync_client)

        # Mock async streaming
        async def mock_aiter_bytes():
            yield b"Hello"
            yield b" "
            yield b"World"
            yield b"[stream_finished]"

        mock_stream_response = AsyncMock()
        mock_stream_response.aiter_bytes = mock_aiter_bytes
        mock_stream_response.__aenter__ = AsyncMock(return_value=mock_stream_response)
        mock_stream_response.__aexit__ = AsyncMock(return_value=False)

        mock_async_client = AsyncMock()
        mock_async_client.stream = MagicMock(return_value=mock_stream_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(httpx, "AsyncClient", lambda: mock_async_client)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings)

        # Stream a message
        chunks = []
        async for chunk in client.stream("Hello"):
            chunks.append(chunk)

        assert chunks == ["Hello", " ", "World"]

    @pytest.mark.asyncio
    async def test_stream_with_image(self, app_server, monkeypatch):
        """Test streaming with image (base64)"""
        assert app_server is not None

        # Mock successful initialization
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_sync_client = MagicMock()
        mock_sync_client.__enter__ = MagicMock(return_value=mock_sync_client)
        mock_sync_client.__exit__ = MagicMock(return_value=False)
        mock_sync_client.request = MagicMock(return_value=mock_response)

        monkeypatch.setattr(httpx, "Client", lambda: mock_sync_client)

        # Mock async streaming
        async def mock_aiter_bytes():
            yield b"Response"
            yield b"[stream_finished]"

        mock_stream_response = AsyncMock()
        mock_stream_response.aiter_bytes = mock_aiter_bytes
        mock_stream_response.__aenter__ = AsyncMock(return_value=mock_stream_response)
        mock_stream_response.__aexit__ = AsyncMock(return_value=False)

        mock_async_client = AsyncMock()
        mock_async_client.stream = MagicMock(return_value=mock_stream_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(httpx, "AsyncClient", lambda: mock_async_client)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings)

        # Stream a message with image
        image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        chunks = []
        async for chunk in client.stream("Describe this image", image_b64=image_b64):
            chunks.append(chunk)

        assert chunks == ["Response"]

    @pytest.mark.asyncio
    async def test_stream_enables_streaming_flag(self, app_server, monkeypatch):
        """Test that stream() enables streaming flag in settings"""
        assert app_server is not None

        # Mock successful initialization
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_sync_client = MagicMock()
        mock_sync_client.__enter__ = MagicMock(return_value=mock_sync_client)
        mock_sync_client.__exit__ = MagicMock(return_value=False)
        mock_sync_client.request = MagicMock(return_value=mock_response)

        monkeypatch.setattr(httpx, "Client", lambda: mock_sync_client)

        # Mock async streaming
        async def mock_aiter_bytes():
            yield b"test"
            yield b"[stream_finished]"

        mock_stream_response = AsyncMock()
        mock_stream_response.aiter_bytes = mock_aiter_bytes
        mock_stream_response.__aenter__ = AsyncMock(return_value=mock_stream_response)
        mock_stream_response.__aexit__ = AsyncMock(return_value=False)

        mock_async_client = AsyncMock()
        mock_async_client.stream = MagicMock(return_value=mock_stream_response)
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(httpx, "AsyncClient", lambda: mock_async_client)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings)

        # Verify streaming is not set initially
        assert "streaming" not in client.settings["ll_model"]

        # Stream a message
        async for _ in client.stream("test"):
            pass

        # Verify streaming was enabled
        assert client.settings["ll_model"]["streaming"] is True


#############################################################################
# Test Client History
#############################################################################
class TestClientHistory:
    """Test Client history retrieval"""

    @pytest.mark.asyncio
    async def test_get_history_success(self, app_server, monkeypatch):
        """Test get_history with successful response"""
        assert app_server is not None

        # Mock successful initialization
        mock_init_response = MagicMock()
        mock_init_response.status_code = 200

        mock_sync_client = MagicMock()
        mock_sync_client.__enter__ = MagicMock(return_value=mock_sync_client)
        mock_sync_client.__exit__ = MagicMock(return_value=False)
        mock_sync_client.request = MagicMock(return_value=mock_init_response)

        monkeypatch.setattr(httpx, "Client", lambda: mock_sync_client)

        # Mock get request for history
        mock_history_response = MagicMock()
        mock_history_response.status_code = 200
        mock_history_response.json.return_value = [
            {"role": "human", "content": "Hello"},
            {"role": "ai", "content": "Hi there!"},
        ]

        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_history_response))

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings)

        history = await client.get_history()

        assert len(history) == 2
        assert history[0]["role"] == "human"
        assert history[1]["role"] == "ai"

    @pytest.mark.asyncio
    async def test_get_history_error_response(self, app_server, monkeypatch):
        """Test get_history with error response"""
        assert app_server is not None

        # Mock successful initialization
        mock_init_response = MagicMock()
        mock_init_response.status_code = 200

        mock_sync_client = MagicMock()
        mock_sync_client.__enter__ = MagicMock(return_value=mock_sync_client)
        mock_sync_client.__exit__ = MagicMock(return_value=False)
        mock_sync_client.request = MagicMock(return_value=mock_init_response)

        monkeypatch.setattr(httpx, "Client", lambda: mock_sync_client)

        # Mock get request with error
        mock_history_response = MagicMock()
        mock_history_response.status_code = 404
        mock_history_response.text = "Not found"
        mock_history_response.json.return_value = {"detail": [{"msg": "History not found"}]}

        monkeypatch.setattr(httpx, "get", MagicMock(return_value=mock_history_response))

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings)

        result = await client.get_history()

        assert "Error: 404" in result
        assert "History not found" in result

    @pytest.mark.asyncio
    async def test_get_history_connection_error(self, app_server, monkeypatch):
        """Test get_history with connection error"""
        assert app_server is not None

        # Mock successful initialization
        mock_init_response = MagicMock()
        mock_init_response.status_code = 200

        mock_sync_client = MagicMock()
        mock_sync_client.__enter__ = MagicMock(return_value=mock_sync_client)
        mock_sync_client.__exit__ = MagicMock(return_value=False)
        mock_sync_client.request = MagicMock(return_value=mock_init_response)

        monkeypatch.setattr(httpx, "Client", lambda: mock_sync_client)

        # Mock connection error
        def mock_get(*args, **kwargs):
            raise httpx.ConnectError("Cannot connect")

        monkeypatch.setattr(httpx, "get", mock_get)

        server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        settings = {"client": "test-client", "ll_model": {}}

        client = Client(server, settings)

        result = await client.get_history()

        # Should return None on connection error
        assert result is None
