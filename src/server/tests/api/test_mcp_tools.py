"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP tools endpoint.
"""
# spell-checker: disable

import pytest

pytestmark = pytest.mark.anyio


@pytest.mark.unit
async def test_list_tools_no_auth(app_client):
    """GET /mcp/tools without auth returns 403."""
    resp = await app_client.get("/mcp/tools")
    assert resp.status_code == 403


@pytest.mark.unit
async def test_list_tools_returns_list(app_client, auth_headers):
    """GET /mcp/tools returns a list."""
    resp = await app_client.get("/mcp/tools", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
