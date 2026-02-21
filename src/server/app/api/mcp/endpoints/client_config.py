"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoint returning MCP client configuration.
"""
# spell-checker:ignore streamable

from fastapi import APIRouter, Request

from server.app.api.mcp.schemas.client_config import MCPClientConfigResponse
from server.app.core.settings import settings

auth = APIRouter()


@auth.get("/client-config", response_model=MCPClientConfigResponse)
async def get_client_config(request: Request, client: str | None = None):
    """Return a ready-to-use MCP client configuration object."""
    base = str(request.base_url).rstrip("/")
    url = f"{base}{settings.server_url_prefix}/mcp/"

    server_entry: dict = {
        "type": "streamableHttp",
        "transport": "streamable-http",
        "url": url,
        "headers": {"X-API-Key": settings.api_key},
    }

    if client == "langgraph":
        server_entry.pop("type")

    return {"mcpServers": {"oracle-ai-optimizer": server_entry}}
