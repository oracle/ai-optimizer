"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP tools endpoint.
"""
# spell-checker: disable

from types import SimpleNamespace
from unittest.mock import patch

import pytest

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
                SimpleNamespace(
                    model_dump=lambda: {
                        "name": "sqlcl_list-connections",
                        "description": "List database connections.",
                    }
                )
            ]

    with patch("server.app.api.mcp.endpoints.tools.Client", FakeClient):
        resp = await app_client.get("/mcp/tools", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == [
        {
            "name": "sqlcl_list-connections",
            "description": "List database connections.",
        }
    ]
