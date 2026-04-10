"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore noauth healthz

from fastapi import APIRouter

from _version import __version__
from server.app.api.mcp.schemas.probes import MCPHealthResponse
from server.app.core.mcp import mcp

noauth = APIRouter()


@noauth.get("/healthz", response_model=MCPHealthResponse)
async def mcp_healthz():
    """MCP health probe."""
    tools = await mcp.list_tools()
    return {
        "status": "ok",
        "name": mcp.name,
        "version": __version__,
        "available_tools": sorted(t.name for t in tools),
    }
