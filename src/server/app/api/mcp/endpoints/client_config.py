"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoint returning MCP client configuration.
"""
# spell-checker:ignore streamable langgraph claude cline vscode npx

from fastapi import APIRouter, HTTPException, Request

from server.app.api.mcp.schemas.client_config import MCPClientConfigResponse
from server.app.core.secrets import reveal
from server.app.core.settings import settings

auth = APIRouter()


def _mcp_url(request: Request) -> str:
    """Build MCP URL from the incoming request."""
    base = str(request.base_url).rstrip("/")
    prefix = settings.server_url_prefix or ""

    if prefix and not prefix.startswith("/"):
        prefix = f"/{prefix}"

    prefix = prefix.rstrip("/")

    return f"{base}{prefix}/mcp"


def _api_key() -> str:
    """Reveal API key for client configuration."""
    api_key = reveal(settings.api_key)

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="MCP API key is not configured.",
        )

    return api_key


def _streamable_http_entry(url: str, headers: dict[str, str], include_type: bool = True) -> dict:
    """Return a Streamable HTTP MCP server entry."""
    entry = {
        "transport": "streamable-http",
        "url": url,
        "headers": headers,
    }

    if include_type:
        entry["type"] = "streamableHttp"

    return entry


def _client_config(client: str, url: str, headers: dict[str, str]) -> dict:
    """Return client-specific MCP configuration."""
    client = client.lower().strip()
    header_name, header_value = next(iter(headers.items()))

    if client in {"cline", "vscode"}:
        return {
            "mcpServers": {
                "oracle-ai-optimizer": _streamable_http_entry(
                    url=url,
                    headers=headers,
                    include_type=True,
                )
            }
        }

    if client == "langgraph":
        return {
            "mcpServers": {
                "oracle-ai-optimizer": _streamable_http_entry(
                    url=url,
                    headers=headers,
                    include_type=False,
                )
            }
        }

    if client in {"inspector", "mcp-inspector", "npx-inspector"}:
        return {
            "mcpServers": {
                "oracle-ai-optimizer": {
                    "type": "http",
                    "url": url,
                    "headers": headers,
                }
            }
        }

    if client in {"claude", "claude-desktop"}:
        return {
            "mcpServers": {
                "oracle-ai-optimizer": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "mcp-remote",
                        url,
                        "--transport",
                        "http-only",
                        "--header",
                        f"{header_name}: {header_value}",
                    ],
                }
            }
        }

    if client in {"generic", "default"}:
        return {
            "mcpServers": {
                "oracle-ai-optimizer": _streamable_http_entry(
                    url=url,
                    headers=headers,
                    include_type=True,
                )
            }
        }

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported MCP client: {client}",
    )


@auth.get("/client-config", response_model=MCPClientConfigResponse)
async def get_client_config(request: Request, client: str = "generic"):
    """Return a ready-to-use MCP client configuration object."""
    url = _mcp_url(request)
    authorization = request.headers.get("authorization")
    if authorization:
        headers = {"Authorization": authorization}
    elif settings.auth_mode is None:
        headers = {"X-API-Key": _api_key()}
    else:
        raise HTTPException(
            status_code=400,
            detail="MCP client configuration requires a replayable bearer credential.",
        )

    return _client_config(client=client, url=url, headers=headers)
