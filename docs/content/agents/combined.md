---
title: "Combined Session"
date: 2026-03-07
draft: false
---

The Combined session is an orchestrator that routes queries to VecSearch, NL2SQL, or both. Unlike the other agents and flows, it does not have an AgentSpec definition — it coordinates existing sub-sessions at runtime.

```mermaid
flowchart TD
    query["User query"] --> classify["LLM classification call"]
    classify --> route{"Route decision"}
    route -->|nl2sql| nl2sql["NL2SQL Agent"]
    route -->|vecsearch| vecsearch["VecSearch Flow"]
    route -->|both| parallel["Run both in parallel"]
    nl2sql --> answer_sql["Return NL2SQL answer"]
    vecsearch --> answer_vs["Return VecSearch answer"]
    parallel --> nl2sql_p["NL2SQL Agent"]
    parallel --> vecsearch_p["VecSearch Flow"]
    nl2sql_p --> synth["LLM synthesizes results"]
    vecsearch_p --> synth
    synth --> answer_both["Return combined answer"]
```

- The classifier prompts the LLM to respond with exactly one word — `nl2sql`, `vecsearch`, or `both` — based on the user's question. Unrecognized responses default to `both`.
- When routed to a single tool, the query is dispatched directly to the corresponding sub-session.
- When routed to `both`, the sub-sessions run in parallel. The results are then fed into a synthesis LLM call to produce a unified response.
- The system prompt is fetched from the MCP server (`optimizer_tools-default`). If unavailable, a default instruction is used.
- Token usage from the classifier, sub-sessions, and synthesis calls is aggregated.
- Requires both a configured [VecSearch](vecsearch/) flow and an [NL2SQL](nl2sql/) agent to be available.
