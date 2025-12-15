# AGENTS.md

This file provides guidance to AI coding agents working on this repository. It complements README.md with agent-specific context and pointers to detailed documentation.

## Project Overview

**Oracle AI Optimizer and Toolkit** is a GenAI application combining RAG (Retrieval-Augmented Generation) with Oracle AI Database VectorSearch:

- **Streamlit Client** (`src/client/`) - GUI for chatbot, configuration, testing
- **FastAPI Server** (`src/server/`) - REST API with MCP integration
- **LangGraph Orchestration** (`src/server/mcp/graph.py`) - Dual-path routing for chat workflows

**Key architectural concept**: Vector Search uses an internal pipeline (token-efficient), external tools (SQLcl) use standard MCP patterns. See `src/server/mcp/README.md` for details.

## Quick Reference

| Task | Location |
|------|----------|
| Setup & Installation | [README.md](README.md) |
| MCP/LangGraph Details | [src/server/mcp/README.md](src/server/mcp/README.md) |
| Git Workflow & PRs | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Security Reporting | [SECURITY.md](SECURITY.md) |
| Kubernetes Deploy | [helm/README.md](helm/README.md) |
| IaC (OpenTofu) | [opentofu/README.md](opentofu/README.md) |
| Full Documentation | [oracle.github.io/ai-optimizer](https://oracle.github.io/ai-optimizer) |

## Build & Test Commands

```bash
# Setup
python3.11 -m venv .venv --copies && source .venv/bin/activate
pip install --upgrade pip wheel setuptools uv
uv pip install -e ".[all-test]"

# Run application
cd src/ && streamlit run launch_client.py --server.port 8501  # Client (must be in src/)
python src/launch_server.py --port 8000                        # Server

# Test & Lint
pytest tests -v
pytest tests -v --cov=src --cov-report=term
pylint src && pylint tests
```

## Directory Structure

```
src/
├── launch_client.py         # Streamlit entry
├── launch_server.py         # FastAPI/FastMCP entry
├── client/                  # GUI components
│   ├── content/             # Pages (chatbot, testbed, config)
│   └── utils/               # API helpers
├── server/
│   ├── api/v1/              # REST endpoints (routers)
│   ├── api/utils/           # Business logic (routers delegate here)
│   ├── bootstrap/           # Config loading (ConfigStore singleton)
│   └── mcp/                 # MCP implementation → SEE mcp/README.md
│       ├── tools/           # Auto-discovered MCP tools
│       ├── prompts/         # Auto-discovered MCP prompts
│       ├── proxies/         # External MCP servers (SQLcl)
│       └── graph.py         # LangGraph state machine
└── common/schema.py         # All Pydantic models
```

## Core Patterns (Agent-Critical)

### Configuration
- `ConfigStore` singleton loads JSON config at startup
- Client settings are per-session via `thread_id` (UUID)
- Access via `utils_settings.get_client(thread_id)`

### MCP Auto-Registration
Components auto-register via `register()` functions:
```python
# server/mcp/tools/my_tool.py
async def register(mcp, auth):
    @mcp.tool(name='optimizer_my-tool')
    def my_tool(...): ...
```
Tools prefixed `optimizer_` receive `thread_id` automatically.

### API Pattern
Routers (`api/v1/`) are thin - delegate to `api/utils/`:
```python
# api/v1/settings.py
@auth.get("/settings")
async def get_settings(thread_id: str):
    return utils_settings.get_client(thread_id)  # Logic in utils
```

### Dual-Path Routing (graph.py)
- **VS tools** → `vs_orchestrate` node → documents in state (ephemeral)
- **External tools** → `tools` node → standard ToolMessages
- `clean_messages()` filters VS ToolMessages before LLM calls

## Testing Patterns

Tests mirror source: `tests/unit/server/api/v1/test_v1_settings.py`

```python
# Use factory fixtures from tests/shared_fixtures.py
def test_something(make_database, make_model):
    db = make_database(name='test_db')

# Mock bootstrap for unit tests
@patch('server.api.utils.settings.get_client')
def test_endpoint(mock_get_client): ...

# Test MCP tools via _impl functions directly
from server.mcp.tools.vs_retriever import _vs_retrieve_impl
```

## Code Style

- Python 3.11, PEP 8
- Pydantic for all data structures (`common/schema.py`)
- Single quotes, functional patterns preferred
- Routers delegate to utils (separation of concerns)
- `pylint` target: 10.00/10

## Security Considerations

- All `/v1/` endpoints require Bearer token (`API_SERVER_KEY`)
- SQLcl proxy enforces read-only (DML/DDL blocked)
- Never commit: `.env`, credentials, wallet files
- Input validation via Pydantic models

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `API_SERVER_KEY` | Auth token (auto-generated if unset) |
| `API_SERVER_PORT` | Server port (default: 8000) |
| `CONFIG_FILE` | Path to config JSON |
| `TNS_ADMIN` | Oracle wallet directory |
| `DISABLE_*` | Feature toggles (TESTBED, API, TOOLS, DB_CFG, MODEL_CFG) |

## Common Agent Tasks

| Task | Steps |
|------|-------|
| Add MCP Tool | Create `server/mcp/tools/foo.py` with `register()` → auto-discovered |
| Add API Endpoint | Router in `api/v1/`, logic in `api/utils/`, register in `__init__.py` |
| Modify Chat Graph | Edit `graph.py`, update `should_continue()` routing |
| Update Schema | Modify `common/schema.py`, update affected endpoints |

**Always**: `pytest tests -v && pylint src` before committing.

## Troubleshooting

| Issue | Check |
|-------|-------|
| Oracle connection | `TNS_ADMIN` points to wallet with `tnsnames.ora` |
| MCP registration fails | `register()` is async, file in correct directory |
| Context bloat | `clean_messages()` filtering, `internal_vs=True` metadata |
| Graph recursion | ToolMessages exist for ALL tool_calls |
| Decimal serialization | Use `DecimalEncoder` in `graph.py` |

## External References

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [LangGraph](https://python.langchain.com/docs/langgraph)
- [Oracle AI Vector Search](https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/)
