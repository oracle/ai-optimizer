+++
title = 'IDE Integration'
weight = 15
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore apikey cline jsonl langgraph nl2sql sqlcl streamable windsurf aider
-->

Any IDE or coding agent that supports MCP can connect directly to the {{% short_app_ref %}} and use the same RAG tools, prompts, and resources that the built-in client uses.  For tools that do not support MCP, a limited OpenAI-style compatibility path is available.

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

1. Install and configure the {{% short_app_ref %}}.
2. Configure at least one usable language model.
3. Configure a database if you want Vector Search or NL2SQL features.
4. If you want Vector Search, embed your documents first — see [Split & Embed]({{% relref "client/tools/split_embed" %}}).
5. Install **Oracle SQLcl** if you want NL2SQL tools.
6. Start the API Server — see [API Server]({{% relref "client/api_server" %}}).

If `AIO_API_KEY` was not set before startup, retrieve the generated key from the [API Server]({{% relref "client/api_server" %}}) page or review [Environment Variables]({{% relref "configuration" %}}).

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

Paste the `oracle-ai-optimizer` entry into your IDE's MCP server configuration.  Refer to your tool's MCP documentation for the exact location — most tools expose this under a dedicated MCP or AI server settings panel.

{{% notice style="note" %}}
IDE clients connect as the `server` client by default.  Use **Copy Client Settings** on the [API Server]({{% relref "client/api_server" %}}) page to push your GUI client settings to that client before connecting.
{{% /notice %}}

After adding the server, verify the connection:

```bash
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/tools
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/prompts
```

### Available MCP Tools

| Tool | Purpose |
|------|---------|
| `optimizer_vs_discovery` | List available vector stores |
| `optimizer_vs_retriever` | Retrieve relevant chunks from vector stores |
| `optimizer_vs_grade` | Grade document relevance |
| `optimizer_vs_rephrase` | Rephrase queries using conversation history |

SQLcl tools (`sqlcl_*`) are registered automatically when SQLcl is available and a database is configured.  They provide read-only database access: schema inspection, SQL execution, and session metadata.

## OpenAI-Style Compatibility

Some tools — primarily terminal assistants like aider — do not support MCP and need an OpenAI-style endpoint.

The {{% short_app_ref %}} exposes `/v1/chat/completions` and `/v1/chat/streams`, but these are **Optimizer-specific** endpoints, not drop-in OpenAI wire-compatible routes:

- Authentication uses `X-API-Key`, not `Authorization: Bearer`.
- Model selection comes from the client's saved settings, not the `model` field in the request body.
- Responses return a custom `{role, content, route, vs_metadata, token_usage}` object, not the OpenAI `choices` envelope.
- Streaming uses custom SSE event types, not OpenAI delta events.

For tools that cannot speak MCP or accommodate a custom auth header, the recommended path is the [Spring AI]({{% relref "advanced/source_code/springai" %}}) sample or a thin reverse-proxy adapter.

### aider

aider does not support MCP and sends `Authorization: Bearer`, which the Optimizer does not accept directly.  Use a reverse proxy to rewrite the auth header, or point aider at the [Spring AI]({{% relref "advanced/source_code/springai" %}}) sample endpoint instead.

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

Enabling Vector Search also depends on vector search settings such as which store to query and whether discovery, rephrase, and grade nodes are active.  Models under 7B parameters automatically disable rephrase and grade.  See [VecSearch Flow]({{% relref "agents/vecsearch" %}}) and [Chatbot]({{% relref "client/chatbot" %}}) for details.

Use the `client` header on chat requests to isolate conversation history and settings across IDE sessions:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "X-API-Key: $AIO_API_KEY" \
  -H "client: my-ide-session" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

## Tool Routing

When both tools are enabled the runtime routes automatically based on question semantics.  See [VecSearch Flow]({{% relref "agents/vecsearch" %}}) and [NL2SQL Agent]({{% relref "agents/nl2sql" %}}) for how each path works.

## Troubleshooting

**`403 Forbidden`** — The `X-API-Key` header is missing or incorrect.  Retrieve the key from the [API Server]({{% relref "client/api_server" %}}) page.

**MCP tools not visible** — Check `/mcp/healthz` and confirm tools are registered:

```bash
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/healthz
```

**NL2SQL tools missing** — Verify SQLcl is in `PATH` and a database is configured.  Check server logs for the SQLcl proxy registration message.

**Model not found** — Confirm the model is enabled in **Configuration → Models** and list configured models to verify:

```bash
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/v1/models
```

## Related

- [Custom MCP Tools]({{% relref "advanced/mcp" %}})
- [VecSearch Flow]({{% relref "agents/vecsearch" %}})
- [NL2SQL Agent]({{% relref "agents/nl2sql" %}})
- [Split & Embed]({{% relref "client/tools/split_embed" %}})
- [API Server]({{% relref "client/api_server" %}})
- [API Examples]({{% relref "advanced/api_examples" %}})
- [Spring AI]({{% relref "advanced/source_code/springai" %}})
- [Troubleshooting]({{% relref "help/troubleshooting" %}})
