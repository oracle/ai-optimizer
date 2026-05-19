"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP client-config endpoint.
"""
# spell-checker:disable

from unittest.mock import patch

import pytest

from server.app.core.secrets import reveal
from server.app.core.settings import SettingsBase, settings


@pytest.mark.unit
def test_url_prefix_normalized_when_missing_leading_slash():
    """Validator prepends '/' when server_url_prefix lacks one."""
    s = SettingsBase(server_url_prefix="api")
    assert s.server_url_prefix == "/api"


@pytest.mark.unit
def test_url_prefix_unchanged_when_already_correct():
    """Validator leaves a well-formed prefix as-is."""
    s = SettingsBase(server_url_prefix="/api")
    assert s.server_url_prefix == "/api"


@pytest.mark.unit
def test_url_prefix_strips_trailing_slash():
    """Validator strips trailing slashes."""
    s = SettingsBase(server_url_prefix="/api/")
    assert s.server_url_prefix == "/api"


@pytest.mark.unit
def test_url_prefix_empty_stays_empty():
    """Empty prefix remains empty."""
    s = SettingsBase(server_url_prefix="")
    assert s.server_url_prefix == ""


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_with_prefix(app_client, auth_headers):
    """URL is well-formed when server_url_prefix is set."""
    with patch.object(settings, "server_url_prefix", "/api"):
        resp = await app_client.get("/mcp/client-config", headers=auth_headers)

    assert resp.status_code == 200

    server_cfg = resp.json()["mcpServers"]["oracle-ai-optimizer"]
    assert server_cfg["url"] == "http://test/api/mcp"


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_no_auth(app_client):
    """Client-config endpoint rejects requests without API key."""
    resp = await app_client.get("/mcp/client-config")

    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_default(app_client, auth_headers):
    """Default response returns generic Streamable HTTP MCP config."""
    resp = await app_client.get("/mcp/client-config", headers=auth_headers)

    assert resp.status_code == 200

    body = resp.json()
    assert "mcpServers" in body

    server = body["mcpServers"]["oracle-ai-optimizer"]
    expected_url = f"http://test{settings.server_url_prefix}/mcp"

    assert server["url"] == expected_url
    assert server["type"] == "streamableHttp"
    assert server["transport"] == "streamable-http"
    assert server["headers"]["X-API-Key"] == reveal(settings.api_key)


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_generic(app_client, auth_headers):
    """Generic client variant returns Streamable HTTP config with type."""
    resp = await app_client.get("/mcp/client-config?client=generic", headers=auth_headers)

    assert resp.status_code == 200

    server = resp.json()["mcpServers"]["oracle-ai-optimizer"]

    assert server["type"] == "streamableHttp"
    assert server["transport"] == "streamable-http"
    assert server["url"] == f"http://test{settings.server_url_prefix}/mcp"
    assert server["headers"]["X-API-Key"] == reveal(settings.api_key)


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_cline(app_client, auth_headers):
    """Cline client variant returns Streamable HTTP config with type."""
    resp = await app_client.get("/mcp/client-config?client=cline", headers=auth_headers)

    assert resp.status_code == 200

    server = resp.json()["mcpServers"]["oracle-ai-optimizer"]

    assert server["type"] == "streamableHttp"
    assert server["transport"] == "streamable-http"
    assert server["url"] == f"http://test{settings.server_url_prefix}/mcp"
    assert server["headers"]["X-API-Key"] == reveal(settings.api_key)


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_vscode_alias(app_client, auth_headers):
    """VS Code alias returns the same structure as Cline."""
    resp = await app_client.get("/mcp/client-config?client=vscode", headers=auth_headers)

    assert resp.status_code == 200

    server = resp.json()["mcpServers"]["oracle-ai-optimizer"]

    assert server["type"] == "streamableHttp"
    assert server["transport"] == "streamable-http"
    assert server["url"] == f"http://test{settings.server_url_prefix}/mcp"
    assert server["headers"]["X-API-Key"] == reveal(settings.api_key)


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_langgraph(app_client, auth_headers):
    """LangGraph client variant omits the 'type' key."""
    resp = await app_client.get("/mcp/client-config?client=langgraph", headers=auth_headers)

    assert resp.status_code == 200

    server = resp.json()["mcpServers"]["oracle-ai-optimizer"]

    assert "type" not in server
    assert server["transport"] == "streamable-http"
    assert server["url"] == f"http://test{settings.server_url_prefix}/mcp"
    assert server["headers"]["X-API-Key"] == reveal(settings.api_key)


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("client", ["inspector", "mcp-inspector", "npx-inspector"])
async def test_client_config_inspector_aliases(app_client, auth_headers, client):
    """Inspector client variants return the inspector command configuration."""
    resp = await app_client.get(f"/mcp/client-config?client={client}", headers=auth_headers)

    assert resp.status_code == 200

    body = resp.json()

    assert body["command"] == "npx -y @modelcontextprotocol/inspector"
    assert body["transport"] == "Streamable HTTP"
    assert body["url"] == f"http://test{settings.server_url_prefix}/mcp"
    assert body["headers"]["X-API-Key"] == reveal(settings.api_key)


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_claude_desktop(app_client, auth_headers):
    """Claude Desktop client variant returns mcp-remote bridge configuration."""
    resp = await app_client.get("/mcp/client-config?client=claude-desktop", headers=auth_headers)

    assert resp.status_code == 200

    server = resp.json()["mcpServers"]["oracle-ai-optimizer"]
    expected_url = f"http://test{settings.server_url_prefix}/mcp"
    expected_header = f"X-API-Key: {reveal(settings.api_key)}"

    assert server["command"] == "npx"
    assert server["args"] == [
        "-y",
        "mcp-remote",
        expected_url,
        "--transport",
        "http-only",
        "--header",
        expected_header,
    ]


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_claude_alias(app_client, auth_headers):
    """Claude alias returns the Claude Desktop config."""
    resp = await app_client.get("/mcp/client-config?client=claude", headers=auth_headers)

    assert resp.status_code == 200

    server = resp.json()["mcpServers"]["oracle-ai-optimizer"]

    assert server["command"] == "npx"
    assert server["args"][0:2] == ["-y", "mcp-remote"]
    assert server["args"][2] == f"http://test{settings.server_url_prefix}/mcp"
    assert server["args"][-2:] == [
        "--header",
        f"X-API-Key: {reveal(settings.api_key)}",
    ]


@pytest.mark.unit
@pytest.mark.anyio
async def test_client_config_unsupported_client(app_client, auth_headers):
    """Unsupported client returns a 400 response."""
    resp = await app_client.get("/mcp/client-config?client=unsupported", headers=auth_headers)

    assert resp.status_code == 400
    assert "Unsupported MCP client" in resp.json()["detail"]
