+++
title = 'MCP Client Configuration'
weight = 25
url = '/advanced/mcp-client-configuration/'
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore apikey claude cline httpx json langgraph mcpServers npx sqlcl streamable
-->

The {{% full_app_ref %}} exposes a built-in [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server at `/mcp`. External MCP clients can connect to this endpoint and use the tools, prompts, and resources registered by the {{% short_app_ref %}}, including Vector Search tools and SQLcl tools when NL2SQL is configured.

The recommended way to configure a client is to copy the generated JSON from the **MCP Configuration** page or request the client-specific configuration from the API Server.

## Prerequisites

1. Start the {{% short_app_ref %}} API Server.
2. Retrieve or configure the API key. If `AIO_API_KEY` was not set before startup, get the generated key from the [API Server]({{% relref "/client/api_server" %}}) page.
3. Confirm that the MCP server is healthy:

   ```bash
   curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/healthz
   ```

4. If you need Vector Search, split and embed documents first. See [Split & Embed]({{% relref "/client/tools/split_embed" %}}).
5. If you need NL2SQL tools, install SQLcl and configure a database. See [MCP Server]({{% relref "/client/configuration/mcp" %}}).

## Get the Generated Configuration

In the UI, open **Configuration -> MCP Server**, expand **Client Configuration**, and select the target client:

- **Cline for VS Code**
- **LangGraph**
- **Claude Desktop**

You can also request the same JSON from the API Server:

```bash
curl -H "X-API-Key: $AIO_API_KEY" \
  "http://localhost:8000/mcp/client-config?client=cline" | jq .
```

Supported client values include:

| Client | Query value | Notes |
|--------|-------------|-------|
| Cline for VS Code | `cline` | Streamable HTTP configuration with a `type` field |
| LangGraph | `langgraph` | Streamable HTTP configuration without the `type` field |
| Claude Desktop | `claude-desktop` | Local `mcp-remote` bridge configuration |

Use the generated JSON as the source of truth. It includes the correct URL, path prefix, and `X-API-Key` header for the running API Server.

## Cline for VS Code

Cline can connect to hosted MCP servers over Streamable HTTP. Get the Cline configuration:

```bash
curl -H "X-API-Key: $AIO_API_KEY" \
  "http://localhost:8000/mcp/client-config?client=cline" | jq .
```

Example output:

```json
{
  "mcpServers": {
    "oracle-ai-optimizer": {
      "transport": "streamable-http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "X-API-Key": "replace-with-your-api-key"
      },
      "type": "streamableHttp"
    }
  }
}
```

To add it in Cline:

1. Open VS Code.
2. Open the Cline panel.
3. Click the **MCP Servers** icon.
4. Open the **Configure** tab.
5. Click **Configure MCP Servers**.
6. Add the `oracle-ai-optimizer` entry under `mcpServers`.
7. Save the file and confirm that the Optimizer tools appear in Cline.

If you use the Cline remote-server form instead of editing JSON, use:

| Field | Value |
|-------|-------|
| Server Name | `oracle-ai-optimizer` |
| Server URL | `http://localhost:8000/mcp` |
| Transport Type | `Streamable HTTP` |
| Header | `X-API-Key: <your API key>` |

## LangGraph

LangGraph MCP integrations expect the Streamable HTTP endpoint and authentication headers. Get the LangGraph-specific configuration:

```bash
curl -H "X-API-Key: $AIO_API_KEY" \
  "http://localhost:8000/mcp/client-config?client=langgraph" | jq .
```

Example output:

```json
{
  "mcpServers": {
    "oracle-ai-optimizer": {
      "transport": "streamable-http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "X-API-Key": "replace-with-your-api-key"
      }
    }
  }
}
```

The LangGraph variant intentionally omits the `type` key. Use the `url` and `headers` values when creating a Streamable HTTP MCP client or when wiring the Optimizer MCP server into an AgentSpec/LangGraph workflow.

Minimal Python example:

```python
import httpx
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

server_url = "http://localhost:8000/mcp"

async with httpx.AsyncClient(headers={"X-API-Key": "replace-with-your-api-key"}) as http_client:
    async with streamable_http_client(server_url, http_client=http_client) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
```

## Claude Desktop

Claude Desktop typically starts MCP servers as local processes. For the Optimizer's remote HTTP endpoint, the generated configuration uses `mcp-remote` as a local bridge.

Get the Claude Desktop configuration:

```bash
curl -H "X-API-Key: $AIO_API_KEY" \
  "http://localhost:8000/mcp/client-config?client=claude-desktop" | jq .
```

Example output:

```json
{
  "mcpServers": {
    "oracle-ai-optimizer": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://localhost:8000/mcp",
        "--transport",
        "http-only",
        "--header",
        "X-API-Key: replace-with-your-api-key"
      ]
    }
  }
}
```

To add it in Claude Desktop:

1. Install Node.js so that `npx` is available from the shell. Start the bridge between Claude Desktop and an HTTP/SSE/Streamable HTTP MCP endpoint. The default command to create this bridge to the AI Optimizer MCP would be the following:
 ```bash
npx mcp-remote http://localhost:8000/mcp \
  --transport http-only \
  --header "X-API-Key: replace-with-your-api-key" \
  --debug
```
2. Open **Claude Desktop -> Settings -> Developer -> Edit Config**.
3. Add the `oracle-ai-optimizer` entry under `mcpServers` in `claude_desktop_config.json`.
4. Save the file.
5. Restart Claude Desktop.
6. Start a new conversation and allow the Optimizer tools when Claude asks for permission.

## Verify the Connection

From the {{% short_app_ref %}} side, confirm that tools are registered:

```bash
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/tools
```

In the MCP client, ask a question that should require an Optimizer tool. For Vector Search, ask about content that exists in an embedded vector store. For NL2SQL, ask a database question only after SQLcl tools are visible.

## Troubleshooting

**`403 Forbidden`** — The `X-API-Key` header is missing or incorrect. Copy the JSON again from the MCP Configuration page or confirm `AIO_API_KEY`.

**Connection refused** — The API Server is not running, or the client is using the wrong host or port. The default local endpoint is `http://localhost:8000/mcp`.

**Tools are not visible** — Check the MCP health and tools endpoints:

```bash
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/healthz
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/tools
```

**NL2SQL tools are missing** — Confirm that SQLcl is installed, the `sql` binary is on `PATH`, and at least one database is configured.

**Claude Desktop cannot start the server** — Confirm that `npx` is available to Claude Desktop. If needed, use the full path to `npx` in the `command` field.

## Related

- [MCP Server]({{% relref "/client/configuration/mcp" %}})
- [Custom MCP Tools]({{% relref "/advanced/mcp" %}})
- [IDE Integration]({{% relref "/advanced/ide_integration" %}})
- [API Server]({{% relref "/client/api_server" %}})
