"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Read-only endpoints for MCP prompt data.
"""
# spell-checker: ignore fastmcp

from fastapi import APIRouter
from fastmcp import Client

from server.app.core.mcp import mcp

auth = APIRouter(prefix="/prompts")


@auth.get("", response_model=list[dict])
async def list_prompts():
    """Return all registered MCP prompts."""
    client = Client(mcp)
    async with client:
        prompts = await client.list_prompts()
        return [p.model_dump() for p in prompts]
