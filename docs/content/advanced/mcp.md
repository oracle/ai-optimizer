+++
title = 'Custom MCP Tools'
weight = 20
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore pydantic fastmcp agentspec pyagentspec
-->

The {{< short_app_ref >}} exposes an [MCP](https://modelcontextprotocol.io/) server built on [FastMCP](https://gofastmcp.com/).  All registered tools are available over the MCP protocol at the `/mcp` endpoint and through the REST API at `/mcp/tools`.

Developers can add custom tools by dropping a Python file into the tools package — no other files need to be edited.

## Quick Example

Create a new file in `src/server/app/mcp/tools/`:

```python
# src/server/app/mcp/tools/add.py

from server.app.core.mcp import mcp


def register_add_tool():
    """Register the add tool with FastMCP."""

    @mcp.tool(
        name="optimizer_add",
        title="Add Two Numbers",
        tags={"math", "optimizer"},
    )
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b
```

Restart the server and the tool is immediately available to any MCP client.  The registry automatically discovers every `register_*` function in the `src/server/app/mcp/tools/` package at startup.

## How Auto-Discovery Works

During startup, `register_mcp_tools()` in `src/server/app/mcp/tools/registry.py` scans the package for Python modules, imports each one, and calls every function whose name starts with `register_`.  Utility modules (`schemas.py`, `registry.py`, `__init__.py`) are skipped automatically.

This means adding a tool is a single-file operation:

1. Create a new `.py` file in `src/server/app/mcp/tools/`.
2. Define a function named `register_<something>`.
3. Inside that function, decorate your tool with `@mcp.tool()`.
4. Restart the server.

## Step-by-Step Guide

### 1. Create the Tool File

Add a new Python file under `src/server/app/mcp/tools/`.  Each file should contain:

- A **registration function** (named `register_*`) that decorates the tool with `@mcp.tool()`.
- An optional **private implementation function** (`_impl`) to keep business logic separate from the registration boilerplate.

Import the shared `mcp` instance from `server.app.core.mcp`:

```python
from server.app.core.mcp import mcp
```

### 2. Decorate with `@mcp.tool()`

The `@mcp.tool()` decorator accepts the following parameters:

| Parameter | Description |
|-----------|-------------|
| `name` | Unique tool identifier.  Prefix with `optimizer_` by convention. |
| `title` | Human-readable display name. |
| `tags` | Set of strings for categorization (e.g. `{"math", "optimizer"}`). |
| `annotations` | Optional hints: `readOnlyHint`, `idempotentHint`, `openWorldHint`. |
| `timeout` | Execution timeout in seconds (default varies by FastMCP). |

The decorated function's **docstring** is sent to the LLM as the tool description, so make it clear and concise.  Function **parameters** with type hints become the tool's input schema automatically.

### 3. Define a Response Model (Optional)

For tools that return structured data, define a [Pydantic](https://docs.pydantic.dev/) `BaseModel` in `src/server/app/mcp/tools/schemas.py`:

```python
from pydantic import BaseModel


class AddResponse(BaseModel):
    """Response from the optimizer_add tool."""
    result: int
```

Then use it as the return type:

```python
@mcp.tool(name="optimizer_add", title="Add Two Numbers", tags={"math", "optimizer"})
def add(a: int, b: int) -> AddResponse:
    """Add two numbers."""
    return AddResponse(result=a + b)
```

### 4. Verify

After restarting the server, confirm the tool is registered:

```bash
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/tools
```

The response will include your new tool alongside the built-in tools.

## Using Custom Tools

Registering a tool makes it available on the MCP server, but something still needs to *call* it.  There are two ways a custom tool can be used:

### External MCP Clients

Any MCP-compatible client can connect to the {{< short_app_ref >}} server and use registered tools directly.  Configure the client to connect to the `/mcp` endpoint with an `X-API-Key` header.

Examples of MCP clients that can consume tools this way:

- [Claude Desktop](https://modelcontextprotocol.io/quickstart/user)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)
- [VS Code Copilot](https://code.visualstudio.com/docs/copilot/chat/mcp-servers)
- [Cursor](https://docs.cursor.com/context/model-context-protocol)
- Any client that supports the [MCP specification](https://modelcontextprotocol.io/)

With this approach the tool is available immediately after registration — no additional server-side code is needed.

### Internal Agent Use (AgentSpec)

The {{< short_app_ref >}} uses [AgentSpec]({{< ref "agents" >}}) to define agents and flows as portable configurations.  There are two ways to bind MCP tools to an agent:

**MCPToolBox** — Connects to the MCP server and discovers *all* available tools at runtime.  The built-in NL2SQL Agent uses this pattern.  Any custom tool registered on the server is automatically available without code changes.

**MCPTool** — References a single tool by name with explicit inputs and outputs, wired into a flow graph.  The built-in VecSearch Flow uses this pattern.  Adding a tool requires modifying the flow definition.

#### Example: Agent with MCPToolBox

The simplest way to use the `optimizer_add` tool in a custom agent is with an `MCPToolBox`, which auto-discovers all registered tools:

```python
from pyagentspec.agent import Agent as AgentSpecAgent
from pyagentspec.mcp import MCPToolBox

from server.app.agentspec.adapters.mcp import build_mcp_transport
from server.app.agentspec.agent_llm_only import build_llm_config
from server.app.core.schemas import ClientSettings


def build_math_agentspec(
    client_settings: ClientSettings,
    server_url: str,
    api_key: str,
) -> AgentSpecAgent:
    """Build an agent that can use all registered MCP tools."""
    return AgentSpecAgent(
        id="math-agent",
        name="Math Agent",
        llm_config=build_llm_config(client_settings),
        system_prompt="You are a math assistant. Use available tools to perform calculations.",
        tools=[],
        toolboxes=[MCPToolBox(name="optimizer-tools", client_transport=build_mcp_transport(server_url, api_key))],
        human_in_the_loop=True,
    )
```

When a user asks "What is 3 + 4?", the LLM sees `optimizer_add` in its available tools, calls it with `a=3, b=4`, and returns the result.

See the [Agents and Flows]({{< ref "agents" >}}) documentation for the full define → load → execute pattern, including how to wire an agent into the chat endpoint.

## Tips

- **Async tools**: Use `async def` when your tool performs I/O (database queries, HTTP calls, etc.).
- **Context**: Add an optional `ctx: Context` parameter (from `fastmcp`) to emit progress messages back to the MCP client via `await ctx.info(...)`.
- **Naming**: Prefix tool names with `optimizer_` to avoid collisions with tools from other MCP servers.
- **Testing**: See `src/server/tests/mcp/tools/` for examples of how the built-in tools are tested.
