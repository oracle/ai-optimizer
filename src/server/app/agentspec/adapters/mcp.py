"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared MCP utilities for transport construction and prompt fetching.
"""
# spell-checker: ignore streamable pyagentspec

import logging
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent
from pyagentspec.mcp import StreamableHTTPTransport

from net_addressing import verify_for_url
from server.app.mcp.proxies.sqlcl import ensure_sqlcl_saved_connection

LOGGER = logging.getLogger(__name__)


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

    server_url = _normalize_server_url(server_url)
    LOGGER.debug("Connecting SQLcl database '%s' via %s", connection_name, server_url)
    http_client = httpx.AsyncClient(headers={"X-API-Key": api_key}, verify=verify_for_url(server_url))
    async with http_client:  # noqa: SIM117
        async with streamable_http_client(server_url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                connect_args = {"connection_name": connection_name, "model": model}
                if thread_id:
                    connect_args["thread_id"] = thread_id
                result = await session.call_tool(
                    "sqlcl_connect",
                    connect_args,
                )
                if getattr(result, "isError", False):
                    message = _render_text_content(getattr(result, "content", None))
                    if not message:
                        message = str(getattr(result, "structuredContent", "") or "")
                    if "Connection not found:" in message and await ensure_sqlcl_saved_connection(connection_name):
                        result = await session.call_tool(
                            "sqlcl_connect",
                            connect_args,
                        )
                        if not getattr(result, "isError", False):
                            return
                        message = _render_text_content(getattr(result, "content", None))
                        if not message:
                            message = str(getattr(result, "structuredContent", "") or "")
                    raise RuntimeError(message or f"sqlcl_connect failed for {connection_name}")


async def fetch_mcp_prompt(
    server_url: str,
    api_key: str,
    prompt_name: str,
    arguments: dict[str, str] | None = None,
) -> str:
    """Fetch a prompt from the MCP server via prompts/get."""

    server_url = _normalize_server_url(server_url)
    LOGGER.debug("Fetching MCP prompt '%s' from %s", prompt_name, server_url)
    http_client = httpx.AsyncClient(headers={"X-API-Key": api_key}, verify=verify_for_url(server_url))
    async with http_client:  # noqa: SIM117
        async with streamable_http_client(server_url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.get_prompt(prompt_name, arguments)
                return "\n\n".join(msg.content.text for msg in result.messages if isinstance(msg.content, TextContent))
