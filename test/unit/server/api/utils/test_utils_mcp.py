"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/mcp.py
Tests for MCP utility functions.
"""

import os
from test.shared_fixtures import TEST_API_KEY, TEST_API_KEY_ALT
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.api.utils import mcp


class TestGetClient:
    """Tests for the get_client function."""

    @patch.dict(os.environ, {"API_SERVER_KEY": TEST_API_KEY_ALT})
    def test_get_client_default_values(self):
        """get_client should return default configuration."""
        result = mcp.get_client()

        assert "mcpServers" in result
        assert "optimizer" in result["mcpServers"]
        assert result["mcpServers"]["optimizer"]["type"] == "streamableHttp"
        assert result["mcpServers"]["optimizer"]["transport"] == "streamable_http"
        assert "http://127.0.0.1:8000/mcp/" in result["mcpServers"]["optimizer"]["url"]

    @patch.dict(os.environ, {"API_SERVER_KEY": TEST_API_KEY_ALT})
    def test_get_client_custom_server_port(self):
        """get_client should use custom server and port."""
        result = mcp.get_client(server="http://custom.server", port=9000)

        assert "http://custom.server:9000/mcp/" in result["mcpServers"]["optimizer"]["url"]

    @patch.dict(os.environ, {"API_SERVER_KEY": TEST_API_KEY_ALT})
    def test_get_client_includes_auth_header(self):
        """get_client should include authorization header."""
        result = mcp.get_client()

        headers = result["mcpServers"]["optimizer"]["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"] == f"Bearer {TEST_API_KEY_ALT}"

    @patch.dict(os.environ, {"API_SERVER_KEY": TEST_API_KEY})
    def test_get_client_langgraph_removes_type(self):
        """get_client should remove type field for langgraph client."""
        result = mcp.get_client(client="langgraph")

        assert "type" not in result["mcpServers"]["optimizer"]
        assert "transport" in result["mcpServers"]["optimizer"]

    @patch.dict(os.environ, {"API_SERVER_KEY": TEST_API_KEY})
    def test_get_client_non_langgraph_keeps_type(self):
        """get_client should keep type field for non-langgraph clients."""
        result = mcp.get_client(client="other")

        assert "type" in result["mcpServers"]["optimizer"]

    @patch.dict(os.environ, {"API_SERVER_KEY": TEST_API_KEY})
    def test_get_client_none_client_keeps_type(self):
        """get_client should keep type field when client is None."""
        result = mcp.get_client(client=None)

        assert "type" in result["mcpServers"]["optimizer"]

    @patch.dict(os.environ, {"API_SERVER_KEY": ""})
    def test_get_client_empty_api_key(self):
        """get_client should handle empty API key."""
        result = mcp.get_client()

        headers = result["mcpServers"]["optimizer"]["headers"]
        assert headers["Authorization"] == "Bearer "

    @patch.dict(os.environ, {"API_SERVER_KEY": TEST_API_KEY})
    def test_get_client_structure(self):
        """get_client should return expected structure."""
        result = mcp.get_client()

        assert isinstance(result, dict)
        assert isinstance(result["mcpServers"], dict)
        assert isinstance(result["mcpServers"]["optimizer"], dict)

        optimizer = result["mcpServers"]["optimizer"]
        expected_keys = {"type", "transport", "url", "headers"}
        assert set(optimizer.keys()) == expected_keys


class TestListPrompts:
    """Tests for the list_prompts function."""

    @pytest.mark.asyncio
    @patch("server.api.utils.mcp.Client")
    async def test_list_prompts_success(self, mock_client_class):
        """list_prompts should return list of prompts."""
        mock_prompts = [MagicMock(name="prompt1"), MagicMock(name="prompt2")]

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_prompts = AsyncMock(return_value=mock_prompts)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_mcp_engine = MagicMock()

        result = await mcp.list_prompts(mock_mcp_engine)

        assert result == mock_prompts
        mock_client.list_prompts.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.utils.mcp.Client")
    async def test_list_prompts_empty_list(self, mock_client_class):
        """list_prompts should return empty list when no prompts."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_prompts = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_mcp_engine = MagicMock()

        result = await mcp.list_prompts(mock_mcp_engine)

        assert result == []

    @pytest.mark.asyncio
    @patch("server.api.utils.mcp.Client")
    async def test_list_prompts_closes_client(self, mock_client_class):
        """list_prompts should close client after use."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_prompts = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_mcp_engine = MagicMock()

        await mcp.list_prompts(mock_mcp_engine)

        mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.utils.mcp.Client")
    async def test_list_prompts_creates_client_with_engine(self, mock_client_class):
        """list_prompts should create client with MCP engine."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_prompts = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_mcp_engine = MagicMock()

        await mcp.list_prompts(mock_mcp_engine)

        mock_client_class.assert_called_once_with(mock_mcp_engine)

    @pytest.mark.asyncio
    @patch("server.api.utils.mcp.Client")
    async def test_list_prompts_closes_client_on_exception(self, mock_client_class):
        """list_prompts should close client even if exception occurs."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_prompts = AsyncMock(side_effect=RuntimeError("Test error"))
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_mcp_engine = MagicMock()

        with pytest.raises(RuntimeError):
            await mcp.list_prompts(mock_mcp_engine)

        mock_client.close.assert_called_once()


class TestLoggerConfiguration:
    """Tests for logger configuration."""

    def test_logger_exists(self):
        """Logger should be configured."""
        assert hasattr(mcp, "logger")

    def test_logger_name(self):
        """Logger should have correct name."""
        assert mcp.logger.name == "api.utils.mcp"
