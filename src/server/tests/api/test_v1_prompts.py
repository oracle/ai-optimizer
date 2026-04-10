"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for v1 prompt CRUD endpoints.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, patch

import pytest

# Factory text lookup used by endpoints to reset prompts.
_FACTORY_TEXT = {
    "test_prompt-one": "Hello, world!",
    "test_prompt-two": "Original default text",
}

pytestmark = [pytest.mark.usefixtures("populate_prompts")]


@pytest.fixture(autouse=True)
def _mock_factory_text():
    """Patch get_factory_text so endpoints can reset prompts."""
    with patch(
        "server.app.api.v1.endpoints.prompts.get_factory_text",
        side_effect=_FACTORY_TEXT.get,
    ):
        yield


# --- PUT /v1/prompts/{name} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_prompt(app_client, auth_headers):
    """PUT with new text returns 200 and updated text."""
    with (
        patch("server.app.api.v1.endpoints.prompts.persist_settings", new_callable=AsyncMock),
        patch("server.app.api.v1.endpoints.prompts.register_mcp_prompt"),
    ):
        resp = await app_client.put(
            "/v1/prompts/test_prompt-one",
            json={"text": "Updated prompt text"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Updated prompt text"
    assert set(body.keys()) == {"name", "description", "text"}


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_prompt_not_found(app_client, auth_headers):
    """PUT unknown prompt returns 404."""
    resp = await app_client.put(
        "/v1/prompts/nonexistent",
        json={"text": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_prompt_persists(app_client, auth_headers):
    """PUT calls persist_settings and register_mcp_prompt."""
    with (
        patch("server.app.api.v1.endpoints.prompts.persist_settings", new_callable=AsyncMock) as mock_persist,
        patch("server.app.api.v1.endpoints.prompts.register_mcp_prompt") as mock_register,
    ):
        resp = await app_client.put(
            "/v1/prompts/test_prompt-one",
            json={"text": "New text"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    mock_persist.assert_called_once()
    mock_register.assert_called_once()


# --- POST /v1/prompts/{name}/reset ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_prompt(app_client, auth_headers):
    """Reset restores factory text."""
    with (
        patch("server.app.api.v1.endpoints.prompts.persist_settings", new_callable=AsyncMock),
        patch("server.app.api.v1.endpoints.prompts.register_mcp_prompt"),
    ):
        resp = await app_client.post(
            "/v1/prompts/test_prompt-two/reset",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Original default text"
    assert set(body.keys()) == {"name", "description", "text"}


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_prompt_not_found(app_client, auth_headers):
    """Reset unknown prompt returns 404."""
    resp = await app_client.post(
        "/v1/prompts/nonexistent/reset",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_prompt_persists(app_client, auth_headers):
    """Reset calls persist_settings and register_mcp_prompt."""
    with (
        patch("server.app.api.v1.endpoints.prompts.persist_settings", new_callable=AsyncMock) as mock_persist,
        patch("server.app.api.v1.endpoints.prompts.register_mcp_prompt") as mock_register,
    ):
        await app_client.post(
            "/v1/prompts/test_prompt-two/reset",
            headers=auth_headers,
        )
    mock_persist.assert_called_once()
    mock_register.assert_called_once()


# --- POST /v1/prompts/reset ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_reset_all_prompts(app_client, auth_headers):
    """Bulk reset restores all prompts to factory text."""
    with (
        patch("server.app.api.v1.endpoints.prompts.persist_settings", new_callable=AsyncMock),
        patch("server.app.api.v1.endpoints.prompts.register_mcp_prompts"),
    ):
        resp = await app_client.post(
            "/v1/prompts/reset",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    for entry in body:
        assert set(entry.keys()) == {"name", "description", "text"}
