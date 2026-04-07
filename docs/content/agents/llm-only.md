---
title: "LLM-Only Agent"
date: 2026-03-07
draft: false
---

The LLM-Only agent provides a pure conversational experience with no tools or external data sources. It is the simplest agent in the {{< short_app_ref >}}.

```mermaid
flowchart TD
    prompt["Fetch system prompt (optimizer_basic-default)"] --> build["Build AgentSpec (no tools)"]
    build --> load["Load into runtime"]
    load --> session["Create chat session"]
    session --> input["User message"]
    input --> history{"Chat history enabled?"}
    history -->|Yes| stateful["Append to persistent conversation"]
    history -->|No| stateless["Stateless turn (no history impact)"]
    stateful --> execute["Execute LLM call"]
    stateless --> execute
    execute --> reply["Return response"]
```

- The system prompt is fetched from the MCP server (`optimizer_basic-default`). If unavailable, a default instruction is used.
- `build_llm_only_agentspec` creates a portable AgentSpec Agent with no tools — pure LLM conversation.
- The session manages conversation state. When `chat_history` is enabled, turns are appended to persistent history. When disabled, turns are stateless and do not affect history.
- Failed turns are fully rolled back — the user message and any partial response are removed so subsequent turns are not corrupted.
