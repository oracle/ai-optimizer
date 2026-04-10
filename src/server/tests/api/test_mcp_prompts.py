"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP prompt read-only endpoints.
"""
# spell-checker: disable

import pytest

pytestmark = [pytest.mark.usefixtures("populate_prompts")]


# --- GET /mcp/prompts ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_prompts_no_auth(app_client):
    """Prompts endpoint rejects requests without API key."""
    resp = await app_client.get("/mcp/prompts")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_prompts(app_client, auth_headers):
    """Default response returns all prompt configs."""
    resp = await app_client.get("/mcp/prompts", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    names = [p["name"] for p in body]
    assert "test_prompt-one" in names
    assert "test_prompt-two" in names


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_prompts_contains_expected_fields(app_client, auth_headers):
    """Response entries contain standard MCP prompt fields."""
    resp = await app_client.get("/mcp/prompts", headers=auth_headers)
    assert resp.status_code == 200
    for entry in resp.json():
        assert "name" in entry
        assert "description" in entry
