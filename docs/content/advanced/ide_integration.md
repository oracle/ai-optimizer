+++
title = '🔌 IDE Integration'
weight = 50
+++
<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

The {{< full_app_ref >}} provides both **OpenAI-compatible REST API** and **Model Context Protocol (MCP)** integrations, enabling seamless integration with modern AI-powered IDEs and development tools.

## Quick Start

### Prerequisites

1. **Start the AI Optimizer API Server:**
   ```bash
   cd src
   python launch_server.py --port 8000
   ```

2. **Retrieve Your API Key:**
   ```bash
   # The API key is auto-generated and displayed in the server logs
   # Or set it explicitly:
   export API_SERVER_KEY="your-secure-api-key"
   ```

3. **Verify the Server:**
   ```bash
   curl http://localhost:8000/v1/liveness
   # Expected: {"status":"alive"}
   ```

---

## OpenAI-Compatible API

The AI Optimizer implements the OpenAI Chat Completions API specification, making it compatible with most AI-powered development tools.

### API Base URL
```
http://localhost:8000/v1
```

### Authentication
All requests require Bearer token authentication:
```http
Authorization: Bearer YOUR_API_SERVER_KEY
```

### Endpoint: Chat Completions

**Endpoint:** `POST /v1/chat/completions`

**Request Body:**
```json
{
  "model": "openai/gpt-4o-mini",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Explain Oracle AI Vector Search"}
  ],
  "temperature": 1.0,
  "max_tokens": 4096,
  "top_p": 1.0,
  "frequency_penalty": 0.0,
  "presence_penalty": 0.0,
  "streaming": false
}
```

**Response:** Standard OpenAI `ModelResponse` format (via LiteLLM)

**Streaming:** Enable streaming by setting `"streaming": true` or use the dedicated streaming endpoint:
```
POST /v1/chat/streams
```

### Available Models

**Endpoint:** `GET /v1/models?model_type=ll`

Returns all configured language models in your AI Optimizer instance. Models are identified by `provider/model_id` format (e.g., `openai/gpt-4o-mini`, `ollama/llama3.1`).

### Chat History

**Get History:** `GET /v1/chat/history`
- Header: `client: your-client-id`

**Clear History:** `PATCH /v1/chat/history`
- Header: `client: your-client-id`

Each client (identified by the `client` header) maintains its own independent conversation history.

---

## Model Context Protocol (MCP)

The AI Optimizer exposes an MCP server at `/mcp`, providing tools, prompts, and resources for enhanced AI interactions.

### MCP Server URL
```
http://localhost:8000/mcp
```

### Authentication
MCP requests use the same Bearer token authentication:
```
Authorization: Bearer YOUR_API_SERVER_KEY
```

### Auto-Discovery

The MCP server automatically discovers and registers:
- **Tools** - Custom functions callable by AI agents
- **Prompts** - Reusable prompt templates
- **Resources** - External data sources
- **Proxies** - Pass-through to other MCP servers

All components in `src/server/mcp/{tools,prompts,resources,proxies}/` are auto-discovered at startup.

### Health Check

**Endpoint:** `GET /v1/mcp/healthz`

Verify MCP server is ready to accept connections.

---

## IDE Integration Guides

### Continue.dev

[Continue](https://continue.dev) is an open-source AI code assistant for VS Code and JetBrains.

**Configuration:** Add to `~/.continue/config.json`:

```json
{
  "models": [
    {
      "title": "Oracle AI Optimizer",
      "provider": "openai",
      "model": "openai/gpt-4o-mini",
      "apiBase": "http://localhost:8000/v1",
      "apiKey": "YOUR_API_SERVER_KEY"
    }
  ],
  "tabAutocompleteModel": {
    "title": "Oracle AI Optimizer",
    "provider": "openai",
    "model": "openai/gpt-4o-mini",
    "apiBase": "http://localhost:8000/v1",
    "apiKey": "YOUR_API_SERVER_KEY"
  }
}
```

**Features:**
- Chat with your code using RAG-powered responses
- Tab autocomplete with local LLMs
- Access Oracle Database documentation via vector search
- Use SelectAI for natural language to SQL

### Cline

[Cline](https://github.com/clinebot/cline) is an autonomous AI coding agent for VS Code.

**Configuration:**

1. Install Cline extension in VS Code
2. Open Cline settings
3. Configure Custom API:
   - **API Provider:** OpenAI-compatible
   - **Base URL:** `http://localhost:8000/v1`
   - **API Key:** `YOUR_API_SERVER_KEY`
   - **Model:** `openai/gpt-4o-mini` (or any enabled model)

**Features:**
- Autonomous coding with access to Oracle Database
- RAG-powered code generation using your embedded documentation
- Multi-step workflows with SelectAI integration

### Cursor

[Cursor](https://cursor.com) is an AI-first code editor based on VS Code.

**Configuration:** Settings → Models → Add Model

```
Provider: OpenAI-compatible
API Base URL: http://localhost:8000/v1
API Key: YOUR_API_SERVER_KEY
Model: openai/gpt-4o-mini
```

**Features:**
- AI-powered code completion
- Chat with your codebase enhanced with Oracle AI Vector Search
- Inline code generation with RAG context

### Aider

[Aider](https://aider.chat) is an AI pair programming tool for the terminal.

**Configuration:**

```bash
export OPENAI_API_KEY="YOUR_API_SERVER_KEY"
export OPENAI_API_BASE="http://localhost:8000/v1"

aider --model openai/gpt-4o-mini
```

**Features:**
- Terminal-based pair programming
- Git integration with AI-powered commits
- Access to Oracle Database via SelectAI

### Copilot Alternative (Custom)

**Using Any OpenAI-compatible Client:**

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="YOUR_API_SERVER_KEY"
)

response = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[
        {"role": "user", "content": "Explain Oracle AI Vector Search"}
    ]
)

print(response.choices[0].message.content)
```

---

## Advanced Features

### RAG-Powered Development

When you configure a vector store in the AI Optimizer, IDE interactions automatically benefit from Retrieval-Augmented Generation:

1. **Embed Documentation:**
   - Use the GUI to embed Oracle docs, your codebase, or technical references
   - Configure in **Tools → Vector Search**

2. **Enable Vector Search:**
   - Set a default vector store in **Configuration → Settings**
   - Enable "Vector Search" toggle

3. **Use in IDE:**
   - All chat interactions now have access to your embedded knowledge
   - Responses cite sources from your vector store

### SelectAI Integration

Natural language to SQL queries in your IDE:

1. **Configure SelectAI:**
   - Set up Oracle Database with SelectAI in **Configuration → Databases**
   - Enable SelectAI profile

2. **Use in IDE:**
   ```
   User: "Show me the top 10 customers by revenue this quarter"

   AI Optimizer: [Generates and executes SQL query via SelectAI]
   ```

### Multi-Model Support

Switch between models dynamically:

```json
{
  "models": [
    {
      "title": "GPT-4o (Cloud)",
      "model": "openai/gpt-4o-mini",
      "apiBase": "http://localhost:8000/v1"
    },
    {
      "title": "Llama 3.1 (Local)",
      "model": "ollama/llama3.1",
      "apiBase": "http://localhost:8000/v1"
    },
    {
      "title": "Cohere Command-R",
      "model": "cohere/command-r",
      "apiBase": "http://localhost:8000/v1"
    }
  ]
}
```

All models are configured once in AI Optimizer and available to all IDE clients.

### Custom Client Identifiers

Use the `client` header to maintain separate conversation contexts:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_SERVER_KEY" \
  -H "client: my-ide-session" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4o-mini",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

Each `client` value maintains independent:
- Chat history
- Settings preferences
- Vector search state

---

## Configuration Best Practices

### 1. Security

**API Key Management:**
```bash
# Generate a strong API key
export API_SERVER_KEY=$(openssl rand -base64 32)

# Store securely
echo $API_SERVER_KEY > ~/.config/ai-optimizer/api_key.txt
chmod 600 ~/.config/ai-optimizer/api_key.txt
```

**Network Security:**
- For production, use HTTPS with a reverse proxy (nginx, Caddy)
- Restrict access to `localhost` for development
- Use firewall rules to control access

### 2. Performance

**Connection Pooling:**
- Configure IDE tools to reuse connections
- Set appropriate timeouts for long-running operations

**Model Selection:**
- Use smaller models for autocomplete (e.g., `phi-4`, `qwen2.5-coder`)
- Use larger models for complex reasoning (e.g., `gpt-4o`, `command-r-plus`)

**Streaming:**
- Enable streaming for better responsiveness in IDE chat
- Disable streaming for programmatic access

### 3. Multi-User Setup

**Separate API Server:**
```bash
# Start API server independently
python src/launch_server.py --port 8000

# Connect multiple IDE clients
# Each uses client header for isolation
```

**Shared Configuration:**
- Database configs are shared across all clients
- Model configs are shared across all clients
- Settings are per-client

---

## Troubleshooting

### Connection Refused

**Problem:** IDE cannot connect to `http://localhost:8000`

**Solution:**
```bash
# Check if server is running
curl http://localhost:8000/v1/liveness

# Check port
lsof -i :8000

# Restart server
python src/launch_server.py --port 8000
```

### Authentication Failed

**Problem:** `401 Unauthorized`

**Solution:**
```bash
# Check API key in server logs
grep "API_SERVER_KEY" apiserver_8000.log

# Set API key explicitly
export API_SERVER_KEY="your-key"
python src/launch_server.py --port 8000
```

### Model Not Found

**Problem:** `Model 'xyz' not found`

**Solution:**
1. Check enabled models:
   ```bash
   curl -H "Authorization: Bearer YOUR_KEY" \
     http://localhost:8000/v1/models?model_type=ll
   ```

2. Enable model in AI Optimizer GUI:
   - **Configuration → Models**
   - Find your model and toggle "Enabled"

3. Configure API key (if using cloud provider):
   - Set `OPENAI_API_KEY`, `COHERE_API_KEY`, etc.

### Slow Responses

**Problem:** Responses take too long

**Solution:**
1. **Use Local Models:** Configure Ollama for faster responses
2. **Reduce Context:** Lower `max_tokens` parameter
3. **Disable RAG:** Turn off vector search for faster responses
4. **Optimize Vector Store:** Use smaller embeddings or reduce `top_k`

### MCP Connection Issues

**Problem:** MCP tools not available

**Solution:**
```bash
# Check MCP health
curl http://localhost:8000/v1/mcp/healthz

# Check server logs
tail -f apiserver_8000.log | grep MCP

# Verify auto-discovery
# Look for "Registering via server.mcp.tools.X"
```

---

## API Reference

### Complete Endpoint List

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/chat/completions` | Chat completions (OpenAI-compatible) |
| `POST` | `/v1/chat/streams` | Streaming completions |
| `GET` | `/v1/chat/history` | Get chat history |
| `PATCH` | `/v1/chat/history` | Clear chat history |
| `GET` | `/v1/models` | List all models |
| `GET` | `/v1/models/{provider}/{id}` | Get model details |
| `PATCH` | `/v1/models/{provider}/{id}` | Update model config |
| `GET` | `/v1/databases` | List databases |
| `GET` | `/v1/databases/{name}/vector_stores` | List vector stores |
| `POST` | `/v1/embed/local/store` | Upload files for embedding |
| `POST` | `/v1/embed/{vs}/embed` | Embed documents |
| `POST` | `/v1/embed/refresh` | Refresh vector store from OCI |
| `GET` | `/v1/prompts` | List prompts |
| `PATCH` | `/v1/prompts/{category}/{name}` | Update prompt |
| `GET` | `/v1/settings` | Get client settings |
| `PATCH` | `/v1/settings` | Update client settings |
| `GET` | `/v1/oci/buckets` | List OCI buckets |
| `GET` | `/v1/selectai/objects` | Get SelectAI profiles |
| `GET` | `/v1/liveness` | Liveness probe (no auth) |
| `GET` | `/v1/readiness` | Readiness probe (no auth) |
| `GET` | `/v1/mcp/healthz` | MCP health check |

### Full OpenAPI Documentation

Interactive API documentation is available at:
```
http://localhost:8000/v1/docs
```

OpenAPI schema:
```
http://localhost:8000/v1/openapi.json
```

---

## Examples

### Python Example: Streaming Chat

```python
import httpx
import os

API_KEY = os.getenv("API_SERVER_KEY")
BASE_URL = "http://localhost:8000/v1"

async def chat_stream():
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/chat/streams",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "Explain vector search"}
                ],
                "streaming": True
            }
        ) as response:
            async for chunk in response.aiter_bytes():
                if chunk:
                    print(chunk.decode("utf-8"), end="", flush=True)

# Run
import asyncio
asyncio.run(chat_stream())
```

### cURL Example: Chat with RAG

```bash
API_KEY="your-api-key"

curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "client: my-session" \
  -d '{
    "model": "openai/gpt-4o-mini",
    "messages": [
      {
        "role": "user",
        "content": "What is Oracle AI Vector Search?"
      }
    ],
    "temperature": 0.7,
    "max_tokens": 2000
  }' | jq .
```

### Node.js Example: List Models

```javascript
const fetch = require('node-fetch');

const API_KEY = process.env.API_SERVER_KEY;
const BASE_URL = 'http://localhost:8000/v1';

async function listModels() {
  const response = await fetch(`${BASE_URL}/models?model_type=ll`, {
    headers: {
      'Authorization': `Bearer ${API_KEY}`
    }
  });

  const models = await response.json();
  console.log('Available models:', models.map(m => m.id));
}

listModels();
```

---

## Next Steps

1. **Start the Server:** Follow the Quick Start guide above
2. **Configure Your IDE:** Choose your preferred IDE from the integration guides
3. **Test the Connection:** Use the examples to verify everything works
4. **Enable RAG:** Set up vector stores for enhanced responses
5. **Explore MCP:** Discover custom tools and prompts

For more information:
- [API Server Documentation](../client/api_server/)
- [MCP Integration Guide](../advanced/langchain_mcp/)
- [Troubleshooting](../help/troubleshooting/)

---

## Contributing

Found an integration that works well? [Contribute to the docs](https://github.com/oracle/ai-optimizer) and help others!

**Tested Integrations:**
- Continue.dev ✅
- Cline ✅
- Cursor ✅
- Aider ✅

**Requested Integrations:**
- GitHub Copilot (via OpenAI proxy)
- Tabnine
- Cody (Sourcegraph)
- Amazon CodeWhisperer

Open an issue or PR to add your integration guide!
