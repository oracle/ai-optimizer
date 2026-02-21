"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP prompt endpoints.
"""
# pylint: disable=duplicate-code

from unittest.mock import AsyncMock, patch

import pytest

from server.app.prompts.schemas import PromptConfig
from server.app.core.settings import settings


@pytest.fixture(autouse=True)
def _populate_prompts():
    """Inject test PromptConfig entries into settings."""
    original = settings.prompt_configs
    settings.prompt_configs = [
        PromptConfig(
            name="test_prompt-one",
            title="Test Prompt One",
            description="First test prompt",
            tags=["test"],
            text="Hello, world!",
            default_text="Hello, world!",
            customized=False,
        ),
        PromptConfig(
            name="test_prompt-two",
            title="Test Prompt Two",
            description="Second test prompt (customized)",
            tags=["test", "custom"],
            text="Custom text here",
            default_text="Original default text",
            customized=True,
        ),
    ]
    yield
    settings.prompt_configs = original


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
async def test_list_prompts_excludes_default_text(app_client, auth_headers):
    """Response should not contain default_text field."""
    resp = await app_client.get("/mcp/prompts", headers=auth_headers)
    assert resp.status_code == 200
    for entry in resp.json():
        assert "default_text" not in entry


# --- GET /mcp/prompts/{name} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_prompt(app_client, auth_headers):
    """Fetch a single prompt config by name."""
    resp = await app_client.get("/mcp/prompts/test_prompt-one", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "test_prompt-one"
    assert body["text"] == "Hello, world!"
    assert body["customized"] is False


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_prompt_not_found(app_client, auth_headers):
    """Return 404 for unknown prompt name."""
    resp = await app_client.get("/mcp/prompts/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_prompt_case_insensitive(app_client, auth_headers):
    """Prompt name lookup is case-insensitive."""
    resp = await app_client.get("/mcp/prompts/TEST_PROMPT-ONE", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "test_prompt-one"


# --- PUT /mcp/prompts/{name} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_prompt(app_client, auth_headers):
    """PUT with new text returns 200, sets customized=True."""
    with (
        patch("server.app.api.mcp.endpoints.prompts.persist_settings", new_callable=AsyncMock),
        patch("server.app.api.mcp.endpoints.prompts.register_mcp_prompt"),
    ):
        resp = await app_client.put(
            "/mcp/prompts/test_prompt-one",
            json={"text": "Updated prompt text"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Updated prompt text"
    assert body["customized"] is True


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_prompt_not_found(app_client, auth_headers):
    """PUT unknown prompt returns 404."""
    resp = await app_client.put(
        "/mcp/prompts/nonexistent",
        json={"text": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_prompt_persists(app_client, auth_headers):
    """PUT calls persist_settings and register_mcp_prompt."""
    with (
        patch("server.app.api.mcp.endpoints.prompts.persist_settings", new_callable=AsyncMock) as mock_persist,
        patch("server.app.api.mcp.endpoints.prompts.register_mcp_prompt") as mock_register,
    ):
        resp = await app_client.put(
            "/mcp/prompts/test_prompt-one",
            json={"text": "New text"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    mock_persist.assert_called_once()
    mock_register.assert_called_once()


# --- POST /mcp/prompts/{name}/reset ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_prompt(app_client, auth_headers):
    """Reset copies default_text to text and sets customized=False."""
    with (
        patch("server.app.api.mcp.endpoints.prompts.persist_settings", new_callable=AsyncMock),
        patch("server.app.api.mcp.endpoints.prompts.register_mcp_prompt"),
    ):
        resp = await app_client.post(
            "/mcp/prompts/test_prompt-two/reset",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Original default text"
    assert body["customized"] is False


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_prompt_not_found(app_client, auth_headers):
    """Reset unknown prompt returns 404."""
    resp = await app_client.post(
        "/mcp/prompts/nonexistent/reset",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_prompt_persists(app_client, auth_headers):
    """Reset calls persist_settings and register_mcp_prompt."""
    with (
        patch("server.app.api.mcp.endpoints.prompts.persist_settings", new_callable=AsyncMock) as mock_persist,
        patch("server.app.api.mcp.endpoints.prompts.register_mcp_prompt") as mock_register,
    ):
        await app_client.post(
            "/mcp/prompts/test_prompt-two/reset",
            headers=auth_headers,
        )
    mock_persist.assert_called_once()
    mock_register.assert_called_once()
