"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/mcp.py
Tests for MCP (Model Context Protocol) endpoints.
"""

# pylint: disable=too-few-public-methods

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from shared_fixtures import TEST_API_KEY

from server.api.v1 import mcp


class TestGetMcp:
    """Tests for the get_mcp dependency function."""

    def test_get_mcp_returns_fastmcp_app(self):
        """get_mcp should return the FastMCP app from request state."""
        mock_request = MagicMock()
        mock_fastmcp = MagicMock()
        mock_request.app.state.fastmcp_app = mock_fastmcp

        result = mcp.get_mcp(mock_request)

        assert result == mock_fastmcp


class TestGetClient:
    """Tests for the get_client endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp.utils_mcp.get_client")
    async def test_get_client_returns_config(self, mock_get_client):
        """get_client should return MCP client configuration."""
        expected_config = {
            "mcpServers": {
                "optimizer": {
                    "type": "streamableHttp",
                    "transport": "streamable_http",
                    "url": "http://127.0.0.1:8000/mcp/",
                    "headers": {"Authorization": f"Bearer {TEST_API_KEY}"},
                }
            }
        }
        mock_get_client.return_value = expected_config

        result = await mcp.get_client(server="http://127.0.0.1", port=8000)

        assert result == expected_config
        mock_get_client.assert_called_once_with("http://127.0.0.1", 8000)

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp.utils_mcp.get_client")
    async def test_get_client_with_default_params(self, mock_get_client):
        """get_client should use default parameters."""
        mock_get_client.return_value = {}

        await mcp.get_client()

        mock_get_client.assert_called_once_with(None, None)


class TestGetTools:
    """Tests for the get_tools endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp.Client")
    async def test_get_tools_returns_tool_list(self, mock_client_class, mock_fastmcp):
        """get_tools should return list of MCP tools."""
        mock_tool1 = MagicMock()
        mock_tool1.model_dump.return_value = {"name": "optimizer_tool1"}
        mock_tool2 = MagicMock()
        mock_tool2.model_dump.return_value = {"name": "optimizer_tool2"}

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_tools = AsyncMock(return_value=[mock_tool1, mock_tool2])
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await mcp.get_tools(mcp_engine=mock_fastmcp)

        assert len(result) == 2
        mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp.Client")
    async def test_get_tools_returns_empty_list(self, mock_client_class, mock_fastmcp):
        """get_tools should return empty list when no tools."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await mcp.get_tools(mcp_engine=mock_fastmcp)

        assert result == []


class TestMcpListResources:
    """Tests for the mcp_list_resources endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp.Client")
    async def test_mcp_list_resources_returns_resource_list(self, mock_client_class, mock_fastmcp):
        """mcp_list_resources should return list of resources."""
        mock_resource = MagicMock()
        mock_resource.model_dump.return_value = {"name": "test_resource", "uri": "resource://test"}

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_resources = AsyncMock(return_value=[mock_resource])
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await mcp.mcp_list_resources(mcp_engine=mock_fastmcp)

        assert len(result) == 1
        mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp.Client")
    async def test_mcp_list_resources_returns_empty_list(self, mock_client_class, mock_fastmcp):
        """mcp_list_resources should return empty list when no resources."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_resources = AsyncMock(return_value=[])
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await mcp.mcp_list_resources(mcp_engine=mock_fastmcp)

        assert result == []
