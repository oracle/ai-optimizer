"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP probe endpoints.
"""
# spell-checker:ignore healthz

import pytest


@pytest.mark.unit
@pytest.mark.anyio
async def test_mcp_healthz(app_client):
    """MCP healthz probe returns 200 with name, version, and tools, no auth required."""
    resp = await app_client.get("/mcp/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["name"] == "Oracle AI Optimizer"
    assert "version" in body
    assert isinstance(body["available_tools"], list)
