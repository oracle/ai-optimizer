"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP tools endpoint.
"""
# spell-checker: disable

from unittest.mock import patch

import pytest
from mcp.types import Tool, ToolAnnotations

pytestmark = pytest.mark.anyio


@pytest.mark.unit
async def test_list_tools_no_auth(app_client):
    """GET /mcp/tools without auth returns 403."""
    resp = await app_client.get("/mcp/tools")
    assert resp.status_code == 403


@pytest.mark.unit
async def test_list_tools_returns_registered_tool_payload(app_client, auth_headers):
    """GET /mcp/tools returns serialized registered tool metadata."""

    class FakeClient:
        def __init__(self, mcp):
            self.mcp = mcp

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def list_tools(self):
            return [
                Tool(
                    name="sqlcl_list-connections",
                    description="List database connections.",
                    input_schema={"type": "object", "properties": {}},
                    output_schema={"type": "object", "properties": {"connections": {"type": "array"}}},
                    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
                    _meta={"owner": "sqlcl"},
                )
            ]

    with patch("server.app.api.mcp.endpoints.tools.Client", FakeClient):
        resp = await app_client.get("/mcp/tools", headers=auth_headers)

    assert resp.status_code == 200
    tool = resp.json()[0]
    assert tool["name"] == "sqlcl_list-connections"
    assert tool["inputSchema"] == {"type": "object", "properties": {}}
    assert tool["outputSchema"]["properties"]["connections"] == {"type": "array"}
    assert tool["annotations"]["readOnlyHint"] is True
    assert tool["annotations"]["openWorldHint"] is False
    assert tool["_meta"] == {"owner": "sqlcl"}
    assert "input_schema" not in tool
    assert "output_schema" not in tool
    assert "read_only_hint" not in tool["annotations"]
    assert "open_world_hint" not in tool["annotations"]
    assert "meta" not in tool
