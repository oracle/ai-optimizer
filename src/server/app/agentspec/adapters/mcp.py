"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared MCP utilities for transport construction and prompt fetching.
"""
# spell-checker: ignore streamable pyagentspec

import logging
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.types import CallToolResult, TextContent
from pyagentspec.mcp import StreamableHTTPTransport

from net_addressing import verify_for_url
from server.app.mcp.proxies.sqlcl import ensure_sqlcl_saved_connection

LOGGER = logging.getLogger(__name__)
_MCP_PROTOCOL_VERSION = "2026-07-28"


def _normalize_server_url(server_url: str) -> str:
    """Use the canonical trailing-slash MCP endpoint."""
    return server_url.rstrip("/") + "/"


def build_mcp_transport(server_url: str, api_key: str) -> StreamableHTTPTransport:
    """Create a StreamableHTTPTransport for the MCP server."""

    return StreamableHTTPTransport(
        name="mcp-transport",
        url=_normalize_server_url(server_url),
        sensitive_headers={"X-API-Key": api_key},
    )


def _mcp_client(server_url: str, api_key: str) -> Client:
    """Create a client pinned to the application's MCP protocol version."""
    server_url = _normalize_server_url(server_url)
    transport = StreamableHttpTransport(
        server_url,
        headers={"X-API-Key": api_key},
        verify=verify_for_url(server_url),
    )
    return Client(transport, mode=_MCP_PROTOCOL_VERSION)


def _render_text_content(content: Any) -> str:
    """Render MCP text content blocks into plain text."""
    if content is None:
        return ""
    if isinstance(content, TextContent):
        return content.text
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, TextContent):
                text = item.text
            elif isinstance(item, dict):
                text = item.get("text")
            else:
                text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def _render_tool_error(result: CallToolResult) -> str:
    return _render_text_content(result.content) or str(result.structured_content or "")


async def connect_sqlcl_database(
    server_url: str,
    api_key: str,
    connection_name: str,
    model: str,
    thread_id: str | None = None,
) -> None:
    """Connect the SQLcl MCP tools to the configured database."""
    if not connection_name:
        return

    LOGGER.debug("Connecting SQLcl database '%s' via %s", connection_name, server_url)
    async with _mcp_client(server_url, api_key) as client:
        connect_args = {"connection_name": connection_name, "model": model}
        if thread_id:
            connect_args["thread_id"] = thread_id
        result = await client.call_tool_mcp(
            "sqlcl_connect",
            connect_args,
        )
        if result.is_error:
            message = _render_tool_error(result)
            if "Connection not found:" in message and await ensure_sqlcl_saved_connection(connection_name):
                result = await client.call_tool_mcp(
                    "sqlcl_connect",
                    connect_args,
                )
                if not result.is_error:
                    return
                message = _render_tool_error(result)
            raise RuntimeError(message or f"sqlcl_connect failed for {connection_name}")


async def fetch_mcp_prompt(
    server_url: str,
    api_key: str,
    prompt_name: str,
    arguments: dict[str, str] | None = None,
) -> str:
    """Fetch a prompt from the MCP server via prompts/get."""

    LOGGER.debug("Fetching MCP prompt '%s' from %s", prompt_name, server_url)
    async with _mcp_client(server_url, api_key) as client:
        result = await client.get_prompt(prompt_name, arguments)
        return "\n\n".join(msg.content.text for msg in result.messages if isinstance(msg.content, TextContent))
