"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared MCP utilities for transport construction and prompt fetching.
"""
# spell-checker: ignore streamable pyagentspec

import logging

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent
from pyagentspec.mcp import StreamableHTTPTransport

from net_addressing import verify_for_url

LOGGER = logging.getLogger(__name__)


def build_mcp_transport(server_url: str, api_key: str) -> StreamableHTTPTransport:
    """Create a StreamableHTTPTransport for the MCP server."""

    return StreamableHTTPTransport(
        name="mcp-transport",
        url=server_url,
        sensitive_headers={"X-API-Key": api_key},
    )


async def fetch_mcp_prompt(
    server_url: str,
    api_key: str,
    prompt_name: str,
    arguments: dict[str, str] | None = None,
) -> str:
    """Fetch a prompt from the MCP server via prompts/get."""

    LOGGER.debug("Fetching MCP prompt '%s' from %s", prompt_name, server_url)
    http_client = httpx.AsyncClient(headers={"X-API-Key": api_key}, verify=verify_for_url(server_url))
    async with http_client:  # noqa: SIM117
        async with streamable_http_client(server_url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.get_prompt(prompt_name, arguments)
                return "\n\n".join(msg.content.text for msg in result.messages if isinstance(msg.content, TextContent))
