"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP client-config endpoint.
"""

import pytest

from server.app.core.settings import settings


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_no_auth(app_client):
    """Client-config endpoint rejects requests without API key."""
    resp = await app_client.get("/mcp/client-config")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_default(app_client, auth_headers):
    """Default response returns correct structure with type, transport, url, headers."""
    resp = await app_client.get("/mcp/client-config", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "mcpServers" in body
    server = body["mcpServers"]["oracle-ai-optimizer"]
    expected_url = f"http://test{settings.server_url_prefix}/mcp/"
    assert server["url"] == expected_url
    assert server["type"] == "streamableHttp"
    assert server["transport"] == "streamable-http"
    assert server["headers"]["X-API-Key"] == settings.api_key


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_langgraph(app_client, auth_headers):
    """LangGraph client variant omits the 'type' key."""
    resp = await app_client.get("/mcp/client-config?client=langgraph", headers=auth_headers)
    assert resp.status_code == 200
    server = resp.json()["mcpServers"]["oracle-ai-optimizer"]
    assert "type" not in server
    assert server["transport"] == "streamable-http"
