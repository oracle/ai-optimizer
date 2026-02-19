"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
This file is being used in APIs, and not the backend.py file.
"""

# spell-checker:ignore noauth fastmcp healthz
from fastapi import APIRouter, Request, Depends
from fastmcp import FastMCP, Client

import server.api.utils.mcp as utils_mcp

from common import logging_config

logger = logging_config.logging.getLogger("api.v1.mcp")

auth = APIRouter()


def get_mcp(request: Request) -> FastMCP:
    """Get the MCP engine from the app state"""
    return request.app.state.fastmcp_app


@auth.get(
    "/client",
    description="Get MCP Client Configuration",
    response_model=dict,
)
async def get_client(server: str = None, port: int = None) -> dict:
    "Get MCP Client Configuration"
    return utils_mcp.get_client(server, port)


@auth.get(
    "/tools",
    description="List available MCP tools",
    response_model=list[dict],
)
async def get_tools(mcp_engine: FastMCP = Depends(get_mcp)) -> list[dict]:
    """List MCP tools"""
    tools_info = []
    try:
        client = Client(mcp_engine)
        async with client:
            tools = await client.list_tools()
            logger.debug("MCP Tools: %s", tools)
            for tool_object in tools:
                tools_info.append(tool_object.model_dump())
    finally:
        await client.close()

    return tools_info


@auth.get(
    "/resources",
    description="List MCP resources",
    response_model=list[dict],
)
async def mcp_list_resources(mcp_engine: FastMCP = Depends(get_mcp)) -> list[dict]:
    """List MCP Resources"""
    resources_info = []
    try:
        client = Client(mcp_engine)
        async with client:
            resources = await client.list_resources()
            logger.debug("MCP Resources: %s", resources)
            for resources_object in resources:
                resources_info.append(resources_object.model_dump())
    finally:
        await client.close()

    return resources_info
