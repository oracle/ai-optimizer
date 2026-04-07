"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Read-only endpoints for MCP resource data.
"""
# spell-checker: ignore fastmcp

from fastapi import APIRouter
from fastmcp import Client

from server.app.core.mcp import mcp

auth = APIRouter(prefix="/resources")


@auth.get("", response_model=list[dict])
async def list_resources():
    """Return all registered MCP resources."""
    client = Client(mcp)
    async with client:
        resources = await client.list_resources()
        return [r.model_dump() for r in resources]
