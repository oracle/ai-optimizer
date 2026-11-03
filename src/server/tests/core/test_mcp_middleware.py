"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP transport middleware.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from server.app.core.mcp import MCPApiKeyMiddleware, MCPOriginMiddleware

pytestmark = pytest.mark.anyio


async def _inner_app(scope: Scope, receive: Receive, send: Send) -> None:
    """Minimal ASGI app that returns 200 OK."""
    response = PlainTextResponse("OK")
    await response(scope, receive, send)


@pytest.mark.unit
async def test_origin_middleware_allows_request_without_origin():
    """Origin-less requests reach the MCP application."""
    wrapped = MCPOriginMiddleware(_inner_app, path="/")
    async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.text == "OK"


@pytest.mark.unit
@pytest.mark.parametrize("origin", ["http://test", "https://example.com", ""])
async def test_origin_middleware_rejects_every_origin(origin: str):
    """Every supplied Origin is invalid for the MCP transport."""
    inner = AsyncMock()
    wrapped = MCPOriginMiddleware(inner, path="/")
    async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.get("/", headers={"Origin": origin})

    assert response.status_code == 403
    assert response.text == "Forbidden Origin"
    inner.assert_not_awaited()


@pytest.mark.unit
async def test_origin_middleware_only_checks_configured_path():
    """Origin validation leaves adjacent REST routes unchanged."""
    wrapped = MCPOriginMiddleware(_inner_app, path="/mcp")
    async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.get("/mcp/tools", headers={"Origin": "https://example.com"})

    assert response.status_code == 200
    assert response.text == "OK"


@pytest.mark.unit
async def test_origin_middleware_handles_root_path():
    """Origin validation recognizes the MCP path behind a URL prefix."""
    inner = AsyncMock()
    wrapped = MCPOriginMiddleware(inner, path="/mcp")
    transport = ASGITransport(app=wrapped, root_path="/optimizer")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/optimizer/mcp",
            headers={"Origin": "https://example.com"},
        )

    assert response.status_code == 403
    inner.assert_not_awaited()


def _make_client(configured_key: str | None):
    """Build an httpx AsyncClient with the middleware wrapping _inner_app."""
    with patch("server.app.core.mcp.settings") as mock_settings:
        mock_settings.api_key = configured_key
        wrapped = MCPApiKeyMiddleware(_inner_app)
    # The middleware reads settings at call-time, so we need the patch active during requests too.
    # Return the wrapped app and the key for the caller to patch during requests.
    return wrapped


@pytest.mark.unit
async def test_valid_key_passes_through():
    """Valid API key allows the request through to the inner app."""
    wrapped = MCPApiKeyMiddleware(_inner_app)
    with patch("server.app.core.mcp.settings") as mock_settings:
        mock_settings.api_key = "valid-key"
        async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
            resp = await client.get("/", headers={"X-API-Key": "valid-key"})
    assert resp.status_code == 200
    assert resp.text == "OK"


@pytest.mark.unit
async def test_missing_key_returns_403():
    """Missing API key header returns 403 with JSON detail."""
    wrapped = MCPApiKeyMiddleware(_inner_app)
    with patch("server.app.core.mcp.settings") as mock_settings:
        mock_settings.api_key = "valid-key"
        async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
            resp = await client.get("/")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Forbidden"}


@pytest.mark.unit
async def test_wrong_key_returns_403():
    """Incorrect API key returns 403."""
    wrapped = MCPApiKeyMiddleware(_inner_app)
    with patch("server.app.core.mcp.settings") as mock_settings:
        mock_settings.api_key = "valid-key"
        async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
            resp = await client.get("/", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 403


@pytest.mark.unit
async def test_no_configured_key_returns_403():
    """Returns 403 when no key is configured on the server."""
    wrapped = MCPApiKeyMiddleware(_inner_app)
    with patch("server.app.core.mcp.settings") as mock_settings:
        mock_settings.api_key = None
        async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
            resp = await client.get("/", headers={"X-API-Key": "any-key"})
    assert resp.status_code == 403


@pytest.mark.unit
async def test_non_http_passthrough():
    """Non-HTTP scopes (e.g. websocket) are passed through to the inner app."""
    inner = AsyncMock()
    middleware = MCPApiKeyMiddleware(inner)
    scope = {"type": "websocket", "headers": []}
    receive = AsyncMock()
    send = AsyncMock()

    await middleware(scope, receive, send)
    inner.assert_awaited_once_with(scope, receive, send)
