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

In 2.1, the recommended IDE integration path for the {{< short_app_ref >}} is the built-in **MCP server**. Modern IDE agents that support MCP can connect directly to the Optimizer and use the same server for tool access, prompts, and resources.

Some tools also support an **OpenAI-style** integration path. For the built-in FastAPI server, that path should be treated as a **compatibility-layer pattern**, not as a native OpenAI wire-compatible implementation.

The following IDEs and coding agents are useful targets for this integration segment:

| Tool | Type | Platform | Primary Integration Method in 2.1 |
|------|------|----------|-----------------------------------|
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

### Prerequisites

1. Install the {{< short_app_ref >}} and its dependencies.
2. Configure at least one usable language model.
3. Configure a database if you want Vector Search or NL2SQL features.
4. Install **Oracle SQLcl** if you want NL2SQL tools.

For bare-metal development, the project README uses:

```bash
python3.11 -m venv .venv --copies
source .venv/bin/activate
pip3.11 install --upgrade pip wheel setuptools uv
uv pip install -e ".[all]"
cp src/.env.example src/.env.dev
```

### Start the Server

Use the project entrypoint so environment loading and runtime setup behave the same way as the supported application flow:

```bash
src/entrypoint.py server
```

By default, the server listens on `http://localhost:8000`.

### Set or Retrieve the API Key

The server uses the `AIO_API_KEY` setting and expects clients to send it as the `X-API-Key` header.

To set an explicit key:

```bash
export AIO_API_KEY="your-secure-api-key"
src/entrypoint.py server
```

### Verify the Server

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

There are two useful integration modes in 2.1.

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

In 2.1, the built-in Optimizer FastAPI server exposes useful chat endpoints such as:

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

### Verified on `main`

This page was checked against the current `main` branch:

- `GET /mcp/client-config` returns a valid MCP server entry
- MCP routes enforce `X-API-Key`
- `POST /v1/chat/completions` returns the Optimizer-native response object with fields such as `role`, `content`, `route`, and `token_usage`

That last point is why MCP is the primary recommendation for IDE integration in 2.1.

## Optimizer REST API for IDE Workflows

Even when the IDE uses MCP, it is useful to understand the built-in REST API surface because it controls models, settings, client state, and chat history.

### API Base URL

```text
http://localhost:8000/v1
```

### Authentication

The REST API also uses:

```http
X-API-Key: YOUR_API_KEY
```

### Chat Endpoints

| Method | Endpoint | Notes |
|--------|----------|-------|
| `POST` | `/v1/chat/completions` | Non-streaming Optimizer chat response |
| `POST` | `/v1/chat/streams` | Streaming chat endpoint |
| `GET` | `/v1/chat/history` | Get per-client history |
| `PATCH` | `/v1/chat/history` | Clear per-client history |

The chat endpoints use the `client` **header** to identify the session:

```http
client: my-ide-session
```

### Model Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/v1/models` | List configured models |
| `GET` | `/v1/models/supported` | List supported providers and model families |
| `GET` | `/v1/models/{provider}/{id}` | Get one model config |
| `POST` | `/v1/models` | Add a model |
| `PUT` | `/v1/models/{provider}/{id}` | Update a model |

### Settings Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/v1/settings?client=...` | Read settings for a client |
| `PUT` | `/v1/settings?client=...` | Update client settings |
| `POST` | `/v1/settings?client=...` | Create a client configuration |

Settings endpoints use the `client` **query parameter** rather than the `client` header.

### Database and Embed Endpoints

These endpoints are useful for preparing RAG workflows used by IDE agents:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/v1/databases` | List configured databases |
| `GET` | `/v1/databases/{alias}` | Get one database config |
| `GET` | `/v1/embed/{vs}/files` | Inspect files in a vector store |
| `DELETE` | `/v1/embed/{vs}` | Drop a vector store |

## IDE Integration Guides

### VS Code

VS Code is relevant both directly and as the base platform for several agent extensions. When the extension or agent supports MCP, use the generated MCP client configuration from `/mcp/client-config`.

Recommended path:

1. Start the Optimizer server.
2. Fetch `/mcp/client-config`.
3. Copy the `oracle-ai-optimizer` server definition into the MCP configuration expected by the tool.
4. Reconnect the tool and verify tools are visible.

### JetBrains AI Assistant

JetBrains AI Assistant is a strong fit for the 2.1 story because it supports remote MCP servers. Use the same generated Optimizer MCP configuration and map the values into JetBrains' MCP settings.

Recommended path:

- use MCP
- point to `http://localhost:8000/mcp/`
- send `X-API-Key`

### Continue

Continue supports MCP-based workflows and is a good candidate for an IDE integration guide.

Recommended path:

- use MCP rather than the OpenAI-style route
- add an `mcpServers` entry based on `/mcp/client-config`
- use Continue's agent-oriented workflow when tools are required

### Cursor

Cursor is best documented in 2.1 as an MCP-capable client.

Recommended path:

- use the generated MCP configuration
- treat the Optimizer as an external tool-and-context server
- keep OpenAI-style base-URL configuration as a fallback pattern only when a compatibility layer is in front of the Optimizer APIs

### Claude Code

Claude Code is a natural fit for the native MCP story. It can use the Optimizer MCP server as an external tool source for documentation retrieval and database-aware workflows.

Recommended path:

- use MCP
- verify tools via `/mcp/tools`
- verify prompts via `/mcp/prompts`

### Windsurf / Cascade

Windsurf belongs in this segment because MCP support makes it compatible with the same generated configuration approach.

Recommended path:

- use the Optimizer MCP config
- keep the integration focused on tool access, retrieval, and multi-step workflows

### Cline

Cline belongs in two categories:

- **preferred:** MCP integration
- **fallback:** OpenAI-style compatibility integration

For 2.1 documentation, prefer the MCP route when possible because it matches the built-in server capabilities directly.

### Aider

Aider is not an IDE plugin, but it is worth mentioning because many development workflows mix terminal agents and IDE agents.

Aider fits the **OpenAI-style compatibility** bucket, so it should be documented as:

- suitable when a compatibility layer or proxy is present
- not a native fit for the built-in Optimizer chat wire format

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

## Troubleshooting

### Connection Refused

```bash
curl http://localhost:8000/v1/liveness
lsof -i :8000
src/entrypoint.py server
```

### Authentication Failed

The server returns **403 Forbidden** when `X-API-Key` is missing or incorrect.

Check:

- the client sends `X-API-Key`
- the value matches `AIO_API_KEY`
- the IDE MCP config includes the header exactly

### Model Not Found

Check configured models:

```bash
curl -H "X-API-Key: $AIO_API_KEY" \
  http://localhost:8000/v1/models
```

Then enable or fix the model in the Optimizer configuration UI or API.

### MCP Tools Not Visible

Check:

```bash
curl http://localhost:8000/mcp/healthz
curl -H "X-API-Key: $AIO_API_KEY" http://localhost:8000/mcp/tools
```

If SQLcl tools are missing, the SQLcl proxy may not be available in the current environment.

### Vector Search Not Working

Check:

- an embedding model is configured and usable
- a database is configured
- at least one vector store exists
- `Vector Search` is enabled in `tools_enabled`

### NL2SQL Not Working

Check:

- SQLcl is installed and reachable
- a database is configured
- `NL2SQL` is enabled in `tools_enabled`
- the SQLcl proxy initialized successfully

## API Reference

### Core Probes

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/liveness` | Liveness probe |
| `GET` | `/v1/readiness` | Readiness probe |
| `GET` | `/v1/healthz` | Application health and version |
| `GET` | `/mcp/healthz` | MCP health and available tools |

### MCP Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/mcp/client-config` | Generated MCP config |
| `GET` | `/mcp/tools` | List tools |
| `GET` | `/mcp/prompts` | List prompts |
| `GET` | `/mcp/resources` | List resources |

### Chat and Settings Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/chat/completions` | Non-streaming chat |
| `POST` | `/v1/chat/streams` | Streaming chat |
| `GET` | `/v1/chat/history` | Chat history |
| `PATCH` | `/v1/chat/history` | Clear chat history |
| `GET` | `/v1/settings` | Read client settings |
| `PUT` | `/v1/settings` | Update client settings |

### OpenAPI Documentation

Interactive API docs:

```text
http://localhost:8000/v1/docs
```

OpenAPI schema:

```text
http://localhost:8000/v1/openapi.json
```

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
