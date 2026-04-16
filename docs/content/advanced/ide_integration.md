# IDE Integration

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore apikey cline jsonl langgraph nl2sql sqlcl streamable windsurf aider
-->

Any IDE or coding agent that supports MCP can connect directly to the {{< short_app_ref >}} and use the same RAG tools, prompts, and resources that the built-in client uses.  For tools that do not support MCP, a limited OpenAI-style compatibility path is available.

## Supported IDEs

| Tool | Type | Primary Integration |
|------|------|---------------------|
| **VS Code** | Editor / Agent Host | MCP |
| **JetBrains AI Assistant** | IDE Assistant | MCP |
| **Continue** | Code Assistant | MCP |
| **Cursor** | AI-First Editor | MCP |
| **Claude Code** | Coding Agent | MCP |
| **Windsurf / Cascade** | IDE Agent | MCP |
| **Cline** | Autonomous Agent | MCP |
| **aider** | Terminal Assistant | OpenAI-style compatibility layer |

## Prerequisites

1. Install and configure the {{< short_app_ref >}}.
2. Configure at least one usable language model.
3. Configure a database if you want Vector Search or NL2SQL features.
4. If you want Vector Search, embed your documents first — see [Split & Embed]({{< ref "client/tools" >}}).
5. Install **Oracle SQLcl** if you want NL2SQL tools.
6. Start the API Server — see [API Server]({{< ref "client/api_server" >}}).

If `AIO_API_KEY` was not set before startup, retrieve the generated key from the [API Server]({{< ref "client/api_server" >}}) page or via [Configuration]({{< ref "env_config" >}}).

Verify the server before connecting an IDE:

```bash
curl http://localhost:8000/v1/liveness
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/healthz
```

## MCP Integration

This is the preferred path for any IDE or agent that supports MCP.

### Get the Client Configuration

The server generates a ready-to-use client configuration:

```bash
curl -H "X-API-Key: $AIO_API_KEY" \
  http://localhost:8000/mcp/client-config | jq .
```

Example output:

```json
{
  "mcpServers": {
    "oracle-ai-optimizer": {
      "type": "streamableHttp",
      "transport": "streamable-http",
      "url": "http://localhost:8000/mcp/",
      "headers": {
        "X-API-Key": "..."
      }
    }
  }
}
```

Paste the `oracle-ai-optimizer` entry into your IDE's MCP server configuration.

{{% notice style="note" %}}
IDE clients connect as the `server` client by default.  Use **Copy Client Settings** on the [API Server]({{< ref "client/api_server" >}}) page to push your GUI configuration — models, database, tools — to that client before connecting.
{{% /notice %}}

### Per-IDE Setup

| Tool | Where to add the MCP config | Notes |
|------|-----------------------------|-------|
| **VS Code** | MCP extension settings | Use the generated config directly. |
| **JetBrains AI** | Settings → AI Assistant → MCP Servers | Add as a remote MCP server. |
| **Continue** | `~/.continue/config.json` → `mcpServers` | See Continue's MCP documentation. |
| **Cursor** | Settings → MCP | Paste the generated entry. |
| **Claude Code** | `~/.claude.json` or project MCP config | Verify tool visibility with `/mcp/tools` after adding. |
| **Windsurf / Cascade** | MCP settings | Use the generated config directly. |
| **Cline** | VS Code extension settings → MCP Servers | Add server URL and `X-API-Key` header. |

After adding the server, verify the connection:

```bash
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/tools
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/prompts
```

### Available MCP Tools

| Tool | Purpose |
|------|---------|
| `optimizer_vs-discovery` | List available vector stores |
| `optimizer_vs-retriever` | Retrieve relevant chunks from vector stores |
| `optimizer_vs-grade` | Grade document relevance |
| `optimizer_vs-rephrase` | Rephrase queries using conversation history |

SQLcl tools (`sqlcl_*`) are registered automatically when SQLcl is available and a database is configured.  They provide read-only database access: schema inspection, SQL execution, and session metadata.

## OpenAI-Style Compatibility

Some tools — primarily terminal assistants like aider — do not support MCP and need an OpenAI-style endpoint.

The {{< short_app_ref >}} exposes `/v1/chat/completions` and `/v1/chat/streams`, but these are **Optimizer-specific** endpoints, not drop-in OpenAI wire-compatible routes:

- Authentication uses `X-API-Key`, not `Authorization: Bearer`.
- Responses do not use the OpenAI `choices` envelope.
- Streaming uses the Optimizer event format.

For tools that cannot speak MCP or accommodate a custom auth header, the recommended path is the [Spring AI]({{< ref "advanced/source_code/springai" >}}) sample or a thin reverse-proxy adapter.

### aider

aider does not support MCP and sends `Authorization: Bearer`, which the Optimizer does not accept directly.  Use a reverse proxy to rewrite the auth header, or point aider at the [Spring AI]({{< ref "advanced/source_code/springai" >}}) sample endpoint instead.

## Tool Configuration

Each client maintains independent settings, including which tools are enabled.  Set `tools_enabled` per client:

```bash
curl -X PUT "http://localhost:8000/v1/settings?client=my-ide-session" \
  -H "X-API-Key: $AIO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tools_enabled": ["Vector Search", "NL2SQL"]}'
```

| `tools_enabled` | Behavior |
|-----------------|----------|
| `[]` | LLM only |
| `["Vector Search"]` | RAG, no database access |
| `["NL2SQL"]` | Database queries only |
| `["Vector Search", "NL2SQL"]` | Combined multi-tool workflow |

Use the `client` header on chat requests to isolate conversation history and settings across IDE sessions:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "X-API-Key: $AIO_API_KEY" \
  -H "client: my-ide-session" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

## Tool Routing

When both tools are enabled the runtime routes automatically based on question semantics.  See [VecSearch Flow]({{< ref "agents/vecsearch" >}}) and [NL2SQL Agent]({{< ref "agents/nl2sql" >}}) for how each path works.

## Troubleshooting

**`403 Forbidden`** — The `X-API-Key` header is missing or incorrect.  Retrieve the key from the [API Server]({{< ref "client/api_server" >}}) page.

**MCP tools not visible** — Check `/mcp/healthz` and confirm tools are registered:

```bash
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/healthz
```

**NL2SQL tools missing** — Verify SQLcl is in `PATH` and a database is configured.  Check server logs for the SQLcl proxy registration message.

**Model not found** — Confirm the model is enabled in **Configuration → Models** and list available models to verify:

```bash
curl -H "X-API-Key: $AIO_API_KEY" "http://localhost:8000/v1/models?model_type=ll"
```

## Related

- [Custom MCP Tools]({{< ref "advanced/mcp" >}})
- [VecSearch Flow]({{< ref "agents/vecsearch" >}})
- [NL2SQL Agent]({{< ref "agents/nl2sql" >}})
- [Split & Embed]({{< ref "client/tools" >}})
- [API Server]({{< ref "client/api_server" >}})
- [API Examples]({{< ref "advanced/api_examples" >}})
- [Spring AI]({{< ref "advanced/source_code/springai" >}})
- [Troubleshooting]({{< ref "help/troubleshooting" >}})
