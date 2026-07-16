---
title: "VecSearch Flow"
date: 2026-03-07
draft: false
---

The VecSearch flow implements a Retrieval-Augmented Generation (RAG) pipeline with conditional nodes for query rephrasing, store discovery, retrieval, and document grading. It is exposed through the AgentSpec REST API under the name `vecsearch_flow`.

```mermaid
flowchart TD
    prompt["Fetch system prompt (optimizer_vs-tools-default)"] --> build["Build AgentSpec Flow"]
    build --> load["Load into runtime"]
    load --> session["Create flow session"]
    session --> input["User query"]
    input --> rephrase{"Rephrase enabled?"}
    rephrase -->|Yes| rephrase_node["Rephrase query (optimizer_vs_rephrase)"]
    rephrase -->|No| discovery
    rephrase_node --> discovery{"Discovery enabled?"}
    discovery -->|Yes| discovery_node["Discover vector stores (optimizer_vs_discovery)"]
    discovery -->|No| retriever
    discovery_node --> retriever["Retrieve documents (optimizer_vs_retriever)"]
    retriever --> grade{"Grading enabled?"}
    grade -->|Yes| grade_node["Grade relevance (optimizer_vs_grade)"]
    grade -->|No| format
    grade_node --> format["LLM generates answer from retrieved documents"]
    format --> finish["Return answer"]
```

- The system prompt is fetched from the MCP server (`optimizer_vs-tools-default`). If unavailable, a default instruction is used.
- `build_vecsearch_flow` creates a portable AgentSpec Flow with conditional nodes based on the user's vector search settings (rephrase, discovery, grade).
- **Rephrase** (`optimizer_vs_rephrase`) rewrites the user question using conversation history to improve retrieval quality.
- **Discovery** (`optimizer_vs_discovery`) lists available vector stores when Store Discovery is enabled, allowing the LLM to select the most relevant store.
- **Retriever** (`optimizer_vs_retriever`) performs the core vector similarity search and always runs.
- **Grade** (`optimizer_vs_grade`) filters retrieved documents for relevance before answer generation.
- The final LLM node generates the answer using the system prompt and the retrieved (or graded) documents.
- Unlike NL2SQL, VecSearch does not require a database connection name — it operates entirely through vector search MCP tools.
- When the selected chat model has fewer than 7 billion parameters, the rephrase and grade nodes are automatically disabled to optimize performance. See [Model Configuration]({{% relref "/client/configuration/models#automatic-optimization" %}}) for details.
