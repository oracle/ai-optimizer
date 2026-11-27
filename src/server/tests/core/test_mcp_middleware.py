"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP transport middleware.
"""
# spell-checker: disable

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from server.app.core.mcp import MCPOriginMiddleware

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
