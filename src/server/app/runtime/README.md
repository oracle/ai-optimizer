# Runtime Directory

This directory contains two independent runtime implementations: **LangGraph** and **WayFlow**. The active runtime is selected at startup via the `AIO_RUNTIME` environment variable (`langgraph` or `wayflow`).  When `AIO_RUNTIME` is not specified, the default is: `langgraph`.

## Isolation Rules

1. **Each runtime must be fully self-contained.** If either the `langgraph/` or `wayflow/` directory is deleted, the other must continue to work without any errors or missing imports. No runtime directory may import from the other.

2. **Shared code lives in `common.py` only.** Base classes (`BaseChatOrchestrator`, `BaseCombinedSession`), utilities (`HistoryStore`, `resolve_route`), and shared constants are defined in `common.py`. Both runtimes inherit from and extend these — they never depend on each other directly.

3. **Mirror structure is intentional.** Both runtimes expose the same session types (`chat`, `llm_only`, `nl2sql`, `vecsearch`, `multi_tool`) and adapters (`litellm`, `streaming`). This parallel structure exists to keep each runtime independently deletable.

## Agentspec Dependency

Both runtimes depend on the `agentspec/` package (`src/server/app/agentspec/`), but the dependency is strictly one-way: runtimes import from `agentspec/`, and `agentspec/` never imports from `runtime/`. This separation keeps agent and flow specifications portable across engines.

### What agentspec provides

| Component | Module | Purpose |
|-----------|--------|---------|
| Agent builders | `agent_llm_only.py`, `agent_nl2sql.py` | `build_llm_only_agentspec`, `build_nl2sql_agentspec` — construct pyagentspec agent objects from client settings |
| Flow builders | `flow_vecsearch.py` | `build_vecsearch_flow` — constructs a pyagentspec flow for vector-search RAG |
| Adapters | `adapters/litellm.py`, `adapters/mcp.py` | `LiteLlmConfig`, `get_litellm_deserialization_plugin`, `fetch_mcp_prompt`, MCP transport utilities |

### Data flow

```
client_settings → agentspec builder → pyagentspec object → runtime loader → engine-specific instance
```

Each runtime has its own loader (`langgraph/loader.py`, `wayflow/loader.py`) that bridges pyagentspec objects into the target engine's native representation.

### Implications for changes

Modifications to agentspec builders or adapters affect **both** runtimes. Any change in `agentspec/` must be tested against LangGraph and WayFlow to ensure neither breaks.

## Keeping Runtimes in Sync

Behavior fixes and feature changes implemented in one runtime **must be carried over to the other**. For example, if streaming behavior is changed in `langgraph/chat.py`, the equivalent change should be applied to `wayflow/chat.py`. The implementations will differ (LangGraph uses graph compilation and `ToolNode`; WayFlow uses `wayflowcore` flow loading), but the user-facing behavior must stay consistent.

When making changes:
- Fix or implement in one runtime first
- Identify the corresponding file in the other runtime (the directory structures mirror each other)
- Apply the equivalent change, adapting to that runtime's APIs
- Verify both runtimes handle the same edge cases
