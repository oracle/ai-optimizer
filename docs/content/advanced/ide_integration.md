+++
title = 'IDE Integration'
weight = 15
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore apikey cline jsonl langgraph nl2sql sqlcl streamable windsurf
-->

## Supported IDEs

The recommended IDE integration path for the {{< short_app_ref >}} is the built-in **MCP server**. Modern IDE agents that support MCP can connect directly to the Optimizer and use the same server for tool access, prompts, and resources.

Some tools also support an **OpenAI-style** integration path. For the built-in FastAPI server, that path should be treated as a **compatibility-layer pattern**, not as a native OpenAI wire-compatible implementation.

The following IDEs and coding agents are useful targets for this integration segment:

| Tool | Type | Platform | Primary Integration Method |
|------|------|----------|----------------------------|
| **VS Code** | Editor / Agent Host | Desktop | MCP |
| **JetBrains AI Assistant** | IDE Assistant | JetBrains IDEs | MCP |
| **Continue** | Code Assistant | VS Code, JetBrains | MCP |
| **Cursor** | AI-First Editor | Desktop | MCP |
| **Claude Code** | Coding Agent | Terminal / Editor workflows | MCP |
| **Windsurf / Cascade** | IDE Agent | Desktop | MCP |
| **Cline** | Autonomous Agent | VS Code | MCP or OpenAI-style compatibility layer |
| **aider** | Terminal Assistant | Command Line | OpenAI-style compatibility layer |

**Key capabilities available through IDE integration:**

- Chat with **RAG-powered** responses using Oracle AI Vector Search
- Natural-language database access through **NL2SQL** when SQLcl proxy support is available
- Multi-tool workflows that combine documentation retrieval and live database reads
- Shared model catalog across clients
- Separate conversation and settings context per client

## Quick Start

1. Install and configure the {{< short_app_ref >}}.
2. Configure at least one usable language model.
3. Configure a database if you want Vector Search or NL2SQL features.
4. Install **Oracle SQLcl** if you want NL2SQL tools.
5. Start the API Server. See [API Server]({{< ref "client/api_server" >}}).

If `AIO_API_KEY` was not set before startup, the generated API key can be obtained from the [API Server]({{< ref "client/api_server" >}}) page. For environment-based configuration, see [Configuration]({{< ref "env_config" >}}).

Useful verification commands:

```bash
curl http://localhost:8000/v1/liveness
curl http://localhost:8000/v1/healthz
curl http://localhost:8000/mcp/healthz
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/client-config
```

Expected results:

- `/v1/liveness` returns `{"status":"alive"}`
- `/v1/healthz` returns application version and status
- `/mcp/healthz` returns MCP health information and currently available tools
- `/mcp/client-config` returns a ready-to-use MCP client configuration

## Integration Modes

There are two useful integration modes.

### 1. Native MCP Integration

This is the preferred path for IDEs and agents that support MCP directly.

Use:

- MCP endpoint: `http://localhost:8000/mcp/`
- Auth header: `X-API-Key: YOUR_API_KEY`
- Generated client config: `GET /mcp/client-config`

This path gives the IDE direct access to:

- registered MCP tools
- registered prompts
- registered resources
- SQLcl-backed tools when available

### 2. OpenAI-Style Compatibility Integration

This path is for tools that only know how to speak to an OpenAI-like API surface.

The built-in Optimizer FastAPI server exposes useful chat endpoints such as:

- `POST /v1/chat/completions`
- `POST /v1/chat/streams`
- `GET /v1/chat/history`
- `PATCH /v1/chat/history`

However, these routes are **Optimizer-specific**, not drop-in OpenAI wire-compatible routes. In particular:

- requests use the Optimizer chat schema
- responses do not use the OpenAI `choices` envelope
- streaming events use the Optimizer event format

So this mode should be documented as:

- a compatibility-layer pattern
- or a fit for the separate [Spring AI]({{< ref "advanced/source_code/springai" >}}) sample

## Model Context Protocol (MCP)

The {{< short_app_ref >}} exposes an MCP server at `/mcp/`, built on FastMCP. This is the cleanest way to integrate modern coding agents and IDE assistants.

### MCP Server URL

```text
http://localhost:8000/mcp/
```

### Authentication

MCP requests use the same API key as the REST API:

```http
X-API-Key: YOUR_API_KEY
```

### Built-In MCP Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /mcp/healthz` | MCP health probe and tool list |
| `GET /mcp/client-config` | Generated client configuration |
| `GET /mcp/tools` | Registered MCP tools |
| `GET /mcp/prompts` | Registered MCP prompts |
| `GET /mcp/resources` | Registered MCP resources |
| `/mcp/` | MCP server endpoint using streamable HTTP |

### Generated Client Configuration

The easiest bootstrap path is:

```bash
curl -H "X-API-Key: $AIO_API_KEY" \
  http://localhost:8000/mcp/client-config
```

Example response:

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

For LangGraph-oriented clients that expect a slightly different shape:

```bash
curl -H "X-API-Key: $AIO_API_KEY" \
  "http://localhost:8000/mcp/client-config?client=langgraph"
```

### Auto-Discovery

At startup, the MCP layer auto-registers:

- **Tools** from `src/server/app/mcp/tools/`
- **Prompts** from the prompt registry
- **Resources** from the MCP resource registry
- **SQLcl proxy tools** when the SQLcl transport is available

### Available MCP Tools

The built-in Vector Search tools are:

| Tool | Purpose | Typical Use |
|------|---------|-------------|
| `optimizer_vs-discovery` | Discover relevant vector stores | Narrow retrieval scope |
| `optimizer_vs-retriever` | Retrieve relevant chunks from vector stores | Documentation search, RAG |
| `optimizer_vs-grade` | Grade relevance of retrieved chunks | Internal filtering / routing |
| `optimizer_vs-rephrase` | Rephrase or contextualize retrieval queries | Better retrieval quality |

The SQLcl tool list is dynamic because it comes from the SQLcl MCP proxy. When available, these tools provide read-only database-oriented capabilities such as schema inspection, querying, and operational lookups.

For general API usage, see [API Server]({{< ref "client/api_server" >}}) and [API Examples]({{< ref "advanced/api_examples" >}}).

## IDE Integration Notes

The IDEs and coding agents listed above do not need separate Optimizer-side configuration. In most cases, the only Optimizer-specific setup is:

1. start the API Server
2. retrieve the generated MCP configuration from `/mcp/client-config`
3. paste the `oracle-ai-optimizer` server entry into the tool-specific MCP settings
4. verify the connection using `/mcp/tools` or `/mcp/prompts`

The client-specific guidance is mostly about which transport to prefer:

| Tool | Best Fit | Notes |
|------|----------|-------|
| **VS Code** | MCP | Use the generated MCP configuration with the tool or extension you install in VS Code. |
| **JetBrains AI Assistant** | MCP | Use the Optimizer MCP endpoint as a remote MCP server. |
| **Continue** | MCP | Prefer an `mcpServers` entry based on `/mcp/client-config`. |
| **Cursor** | MCP | Treat the Optimizer as an external MCP tool-and-context server. |
| **Claude Code** | MCP | Use MCP and verify tool visibility with `/mcp/tools`. |
| **Windsurf / Cascade** | MCP | Use the same generated MCP configuration approach. |
| **Cline** | MCP, then compatibility layer if needed | Prefer MCP when available; otherwise use an OpenAI-style adapter in front of the Optimizer APIs. |
| **aider** | OpenAI-style compatibility layer | Aider is useful in terminal workflows, but it is not a native fit for the built-in Optimizer chat wire format. |

## Advanced Features

### RAG-Powered Development

Once a vector store is configured, IDE agents can use the Optimizer for documentation-grounded answers.

Typical workflow:

1. Embed documentation into a vector store.
2. Enable **Vector Search** in client settings.
3. Connect an IDE agent through MCP.
4. Ask questions that benefit from documentation retrieval.

This is especially useful for:

- Oracle documentation
- internal runbooks
- product manuals
- architecture notes
- project-specific technical references

### NL2SQL Integration

When SQLcl proxy support is available, IDE agents can use NL2SQL-oriented tools for read-only database workflows.

Typical use cases:

- inspect schema structure
- list objects or tables
- retrieve current state from the database
- compare live state with recommendations found through RAG

### Multi-Tool Workflows

With both **Vector Search** and **NL2SQL** enabled, the Optimizer can support combined workflows such as:

1. retrieve best-practice guidance from documentation
2. inspect the live database state
3. synthesize both into one answer

This is one of the strongest reasons to position MCP as the primary integration path.

### Multi-Model Support

Configured models are shared across clients. IDE workflows can point at the same Optimizer instance while selecting different enabled models through client settings.

Examples:

- cloud-hosted OpenAI-compatible models
- local Ollama models
- OCI-backed models
- other LiteLLM-backed providers configured in the Optimizer

### Separate Client Contexts

Each IDE session can maintain an independent client identity.

For chat routes, set the `client` header:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "X-API-Key: $AIO_API_KEY" \
  -H "client: my-ide-session" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Hello"}
    ]
  }'
```

This keeps conversation history separate across editor sessions, assistants, or users.

### Configuring Tools Per Client

The main tool flags are:

- `Vector Search`
- `NL2SQL`

Update them through the settings endpoint:

```bash
curl -X PUT "http://localhost:8000/v1/settings?client=my-ide-session" \
  -H "X-API-Key: $AIO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tools_enabled": ["Vector Search", "NL2SQL"]
  }'
```

Useful combinations:

- `[]` - LLM-only behavior
- `["Vector Search"]` - RAG only
- `["NL2SQL"]` - database access only
- `["Vector Search", "NL2SQL"]` - combined multi-tool workflow

## Intelligent Tool Routing

The Optimizer runtime uses `tools_enabled` to determine whether the session behaves as:

- `llm_only`
- `vecsearch`
- `nl2sql`
- `combined`

When both tools are enabled, the system can support combined workflows that use documentation retrieval and database querying together.

Typical routing patterns:

| User Question | Likely Route |
|---------------|--------------|
| "How do I configure Oracle RAC?" | `vecsearch` |
| "List the current application users." | `nl2sql` |
| "What should PGA be set to, and what is it set to now?" | `combined` |

## Configuration Best Practices

### 1. Prefer MCP When Available

If the IDE or coding agent supports MCP, use MCP first. It matches the native Optimizer feature set better than an OpenAI-style shim.

### 2. Use Explicit Client IDs

Give each IDE session or automation workflow its own client identity so history and settings do not bleed together.

### 3. Separate RAG and Database Readiness Checks

For reliable demos and IDE workflows, verify:

- a usable LLM is enabled
- a database is configured
- vector stores exist if Vector Search is enabled
- SQLcl tooling is available if NL2SQL is expected

### 4. Use Compatibility Layers Only Where Needed

For OpenAI-style clients that cannot speak MCP, put a thin adapter or proxy in front of the Optimizer APIs rather than pretending the built-in server is OpenAI wire-compatible.

## Examples

### Example: Read MCP Client Config

```bash
curl -H "X-API-Key: $AIO_API_KEY" \
  http://localhost:8000/mcp/client-config | jq .
```

### Example: Verify MCP Tools

```bash
curl -H "X-API-Key: $AIO_API_KEY" \
  http://localhost:8000/mcp/tools | jq .
```

### Example: Optimizer Chat Request

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "X-API-Key: $AIO_API_KEY" \
  -H "client: my-session" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "What is Oracle AI Vector Search?"
      }
    ]
  }' | jq .
```

### Example: Enable Both Tools for a Client

```bash
curl -X PUT "http://localhost:8000/v1/settings?client=my-session" \
  -H "X-API-Key: $AIO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tools_enabled": ["Vector Search", "NL2SQL"]
  }' | jq .
```

## Next Steps

1. Start the server and verify `/mcp/healthz`.
2. Fetch `/mcp/client-config`.
3. Configure one MCP-capable IDE client.
4. Verify `/mcp/tools` and `/mcp/prompts`.
5. Enable Vector Search and, if applicable, NL2SQL for a test client.
6. Add a compatibility layer only for tools that cannot use MCP.

For related material, see:

- [Custom MCP Tools]({{< ref "advanced/mcp" >}})
- [Spring AI]({{< ref "advanced/source_code/springai" >}})
- [API Server]({{< ref "client/api_server" >}})
- [API Examples]({{< ref "advanced/api_examples" >}})
- [Troubleshooting]({{< ref "help/troubleshooting" >}})
