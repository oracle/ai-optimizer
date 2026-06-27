# Runtime Directory

This directory contains the **LangGraph** runtime implementation. The runtime loads pyagentspec definitions (built in `agentspec/`) into LangGraph's native graph representation and drives chat orchestration, streaming, and session management.

## Layout

- `langgraph/` — runtime implementation (chat orchestrator, sessions, loaders, adapters).
- `common.py` — shared runtime utilities (`HistoryStore`, `resolve_route`, history/prompt/token helpers) used by the LangGraph chat orchestrator and combined session.
- `ollama_tools.py` — Ollama tool-calling helpers used by the LangGraph adapter.

## Agentspec Dependency

The runtime depends on the `agentspec/` package (`src/server/app/agentspec/`), but the dependency is strictly one-way: the runtime imports from `agentspec/`, and `agentspec/` never imports from `runtime/`. This separation keeps agent and flow specifications portable across engines.

### What agentspec provides

| Component | Module | Purpose |
|-----------|--------|---------|
| Agent builders | `agent_llm_only.py`, `agent_nl2sql.py` | `build_llm_only_agentspec`, `build_nl2sql_agentspec` — construct pyagentspec agent objects from client settings |
| Flow builders | `flow_vecsearch.py` | `build_vecsearch_flow` — constructs a pyagentspec flow for vector-search RAG |
| Adapters | `adapters/litellm.py`, `adapters/mcp.py` | `LiteLlmConfig`, `get_litellm_deserialization_plugin`, `fetch_mcp_prompt`, MCP transport utilities |

### Data flow

```
client_settings → agentspec builder → pyagentspec object → langgraph loader → LangGraph instance
```

`langgraph/loader.py` bridges pyagentspec objects into LangGraph's native representation (graph compilation, `ToolNode`, etc.).
