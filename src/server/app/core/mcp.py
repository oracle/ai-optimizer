"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP server definition and authentication middleware.
"""

import hmac
import json

from fastmcp import FastMCP
from starlette.types import ASGIApp, Receive, Scope, Send

from server.app.core.settings import settings

mcp = FastMCP("Oracle AI Optimizer")


class MCPApiKeyMiddleware:
    """ASGI middleware that enforces X-API-Key authentication on MCP routes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        api_key = headers.get(b"x-api-key", b"").decode("utf-8", errors="ignore")
        configured_key = settings.api_key

        if not configured_key or not api_key or not hmac.compare_digest(api_key, configured_key):
            body = json.dumps({"detail": "Forbidden"}).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)
