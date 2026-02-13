"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore streamable fastmcp

import os
from fastmcp import FastMCP, Client
from common import logging_config

logger = logging_config.logging.getLogger("api.utils.mcp")


def get_client(server: str = "http://127.0.0.1", port: int = 8000, client: str = None) -> dict:
    """Get the MCP Client Configuration"""
    mcp_client = {
        "mcpServers": {
            "optimizer": {
                "type": "streamableHttp",
                "transport": "streamable_http",
                "url": f"{server}:{port}/mcp/",
                "headers": {"Authorization": f"Bearer {os.getenv('API_SERVER_KEY')}"},
            }
        }
    }
    if client == "langgraph":
        del mcp_client["mcpServers"]["optimizer"]["type"]

    return mcp_client


async def list_prompts(mcp_engine: FastMCP) -> list:
    """Get list of prompts from MCP engine"""
    try:
        client = Client(mcp_engine)
        async with client:
            prompts = await client.list_prompts()
            return prompts
    finally:
        await client.close()
