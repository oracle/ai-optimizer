# API Layer — `/mcp` vs `/v1`

## `/mcp` — Read-only MCP data

Read-only REST endpoints that mirror MCP protocol data (prompts, client-config,
probes). MCP clients use the FastMCP protocol layer directly; these REST
endpoints serve non-MCP clients (e.g. Streamlit) that need to *read*
MCP-managed data.

## `/v1` — CRUD endpoints

CRUD endpoints for application configuration: databases, models, OCI, settings,
and prompts. All write operations (create, update, reset) live here.

## Shared

`deps.py` — API key authentication middleware used by both routers.
