"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Read-only endpoints for MCP tool data.
"""
# spell-checker: ignore fastmcp

from fastapi import APIRouter
from fastmcp import Client

from server.app.core.mcp import mcp

auth = APIRouter(prefix="/tools")


@auth.get("", response_model=list[dict])
async def list_tools():
    """Return all registered MCP tools."""
    client = Client(mcp)
    async with client:
        tools = await client.list_tools()
        return [t.model_dump() for t in tools]
