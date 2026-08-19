# Oracle Agent Memory Integration Plan

This is a phased implementation plan for integrating Oracle AI Agent Memory into the Oracle AI Optimizer and Toolkit. The work is ordered as follows:

1. Backend API, MCP server, and chat runtime
2. OpenTelemetry and SigNoz observability
3. Streamlit client integration

## Recommended Architecture

Introduce a single `AgentMemoryService` boundary in the server:

```text
REST API ------\
MCP tools ------+-- AgentMemoryService -- Oracle Agent Memory SDK -- Oracle AI Database
Chat runtime ---/            |
                             +-- OTEL spans/log correlation -- SigNoz
```

This service should own SDK configuration, lifecycle, model adapters, database selection, identity scoping, and stable response DTOs. REST, MCP, and LangGraph should not call `OracleAgentMemory` directly.

Oracle Agent Memory provides persistent thread context and durable memory. It can automatically extract memories from messages, perform scoped search, generate summaries and context cards, and enforce retention policies.

References:

- [Oracle Agent Memory getting-started guide](https://docs.oracle.com/en/database/oracle/agent-memory/26.6/guide/get-started.html)
- [Oracle Agent Memory overview](https://docs.oracle.com/en/database/oracle/agent-memory/26.6/guide/about.html)

## Critical Decision Gate: Identity

Do not equate the existing `client` header with a durable user identity without explicitly limiting the feature to trusted deployments.

The repository documents that client IDs do not authenticate users or isolate access, and Streamlit generates a new UUID for each browser session:

- `docs/content/server/multi-user-sessions.mdx`
- `src/client/app/main.py`

Oracle Agent Memory requires exact user scoping and assigns authorization responsibility to the integrating application. See the [Oracle Agent Memory security considerations](https://docs.oracle.com/en/database/oracle/agent-memory/26.6/guide/security.html).

Define this contract first:

- `user_id`: authenticated principal or deployment-scoped pseudonym.
- `agent_id`: stable AI Optimizer agent or application identity.
- `thread_id`: individual conversation identity.
- `client`: remains an ephemeral settings and session selector.

For the initial trusted-demo mode, `client` could be mapped to `user_id`, but memory must be disabled by default and the limitation documented. A later authenticated mode should derive `user_id` from a verified gateway or identity claim, never a caller-controlled header.

# Plan 1: Backend API, MCP, and Chat Integration

## B0. Compatibility and Configuration Spike

Before building endpoints:

- Pin `oracleagentmemory` to the exact initially validated release rather than the current open-ended `>=26.6.0` dependency in `pyproject.toml`. The repository generally pins server integrations, and the SDK already documents upcoming API removals.
- Prove against the real Oracle database that:
  - The existing async `oracledb` pool works with the SDK's async APIs.
  - The configured database meets the SDK's required database capabilities.
  - Schema creation and upgrades work under the intended schema owner.
  - Existing LiteLLM model and OCI authentication settings can initialize the SDK LLM and embedder.
- Prefer `MemoryExtractionConfig`; do not use the SDK's deprecated top-level extraction arguments.
- Verify shutdown behavior for background extraction through `close_async()`.

Add a server-level `AgentMemoryConfig`, defaulting to disabled, containing:

- Enabled flag.
- Database alias.
- Memory LLM identity.
- Embedding model identity.
- OCI profile where applicable.
- Schema policy and table prefix or store ID.
- Semantic versus hybrid search strategy.
- Inline, background, or disabled extraction.
- Default and maximum TTL.
- Context-card and retrieval limits.

The database, embedding model, schema policy, and retention rules should remain operator-owned because changing them per browser session can create schema or index incompatibilities. Per-client settings may contain only consumption controls such as "use memory" and "automatically extract memories."

Use separate least-privilege identities:

- Migration or schema owner: permitted to create or upgrade the managed schema.
- Runtime user: only the DML and query privileges required for memory operations.
- Do not let every application startup perform opportunistic DDL. The SDK warns that schema upgrades can be long-running and that expiry cleanup may require scheduler privileges.

References:

- [Stores and schema](https://docs.oracle.com/en/database/oracle/agent-memory/26.6/guide/api/stores.html)
- [Time-to-live guide](https://docs.oracle.com/en/database/oracle/agent-memory/26.6/guide/int-time-to-live.html)

## B1. Memory Service Layer

Create a package resembling:

```text
src/server/app/memory/
|-- adapters.py
|-- config.py
|-- registry.py
|-- schemas.py
+-- service.py
```

Responsibilities:

- Resolve the configured database pool and model credentials.
- Translate the repository's `LiteLlmModelSpec` and embedding configuration into SDK `Llm` and `Embedder` instances.
- Cache components by database, model, and configuration identity, not by user.
- Invalidate the cache after relevant configuration or credential changes.
- Close SDK components during application shutdown.
- Require a `MemoryPrincipal` on every scoped call.
- Always search with exact `user_id` matching.
- Return project-owned Pydantic DTOs rather than exposing SDK objects directly.
- Map SDK exceptions into stable API error categories.
- Never log prompts, stored content, search queries, metadata, user IDs, or thread IDs.

Recommended service methods:

- `create_thread`
- `get_thread`
- `append_turn`
- `get_messages`
- `add_memory`
- `search_memories`
- `update_memory`
- `delete_memory`
- `delete_thread`
- `get_summary`
- `get_context_card`

Include request or turn IDs and deterministic message IDs for retry safety. This matters for streaming reconnects and multi-replica deployments.

## B2. REST API

Add an authenticated `/v1/memory` router using the existing `src/server/app/api/v1/router.py` pattern.

Proposed surface:

- `POST /v1/memory/threads`
- `GET /v1/memory/threads/{thread_id}/messages`
- `POST /v1/memory/threads/{thread_id}/messages`
- `DELETE /v1/memory/threads/{thread_id}`
- `POST /v1/memory/search`
- `POST /v1/memory/memories`
- `PATCH /v1/memory/memories/{memory_id}`
- `DELETE /v1/memory/memories/{memory_id}`
- `GET /v1/memory/threads/{thread_id}/context-card`

Use `POST` for search because metadata filters can be structured and should not be placed in query strings or access logs.

Important deletion semantics:

- "New conversation" should rotate to a new thread.
- `delete_thread` is a separate destructive operation because the SDK cascades through messages, derived memories, and retrieval data.
- Deleting an individual message does not necessarily remove memories previously derived from it.

Reference: [Oracle Agent Memory thread API](https://docs.oracle.com/en/database/oracle/agent-memory/26.6/guide/api/thread.html).

## B3. MCP Tools

Add `src/server/app/mcp/tools/memory.py`. It will be discovered automatically by the existing registry in `src/server/app/mcp/tools/registry.py`.

Start with the same intentionally small capability set recommended by Oracle:

- `optimizer_memory_get_or_create_thread`
- `optimizer_memory_add_messages`
- `optimizer_memory_get_messages`
- `optimizer_memory_add`
- `optimizer_memory_search`

Oracle's MCP example recommends this limited thread, message, add, and search surface. See the [Agent Memory MCP guide](https://docs.oracle.com/en/database/oracle/agent-memory/26.6/guide/int-mcp-server.html).

Repository-specific choices:

- Return typed Pydantic responses, following the existing MCP tools, rather than raw SDK records.
- Resolve scope through `MemoryPrincipal`; do not give the model unrestricted cross-user `user_id` arguments.
- Keep update and deletion tools out of the first MCP release. Add them only after authorization and confirmation semantics are settled.
- Cap result counts and content sizes.
- Validate metadata-filter depth, size, and supported operators.
- Keep memory tools available to external MCP consumers even when automatic chat integration is disabled.

## B4. Integrate Built-in Chat Deterministically

The current orchestrator owns an in-memory `HistoryStore` in `src/server/app/runtime/common.py`. It loads that history before execution and appends a successful user and assistant pair afterward in `src/server/app/runtime/langgraph/chat.py`.

Implement this integration in three increments.

### B4.1 Persistent Transcript

- Introduce a conversation-store protocol.
- Keep the current in-memory implementation as the disabled or fallback mode.
- Add an Agent Memory implementation using `get_messages_async()` and `add_messages_async()`.
- Persist only after a completed response, preserving current failed-turn behavior.
- Ensure the streaming path writes exactly once after the final completion event.

### B4.2 Long-Term Retrieval

- Before each turn, search durable memory using exact user scope.
- Inject returned content in a clearly delimited, untrusted context block.
- Do not allow memory-derived text to authorize database writes, privilege changes, or other sensitive actions.
- Return non-content metadata such as result count and record types in `ChatResponse` and the SSE completion event.

### B4.3 Context Compaction

- Continue using raw messages for short conversations.
- At a configured token threshold, replace the older prefix with `get_context_card_async().content` plus a small recent-message tail.
- Do not pass both the complete transcript and a context card containing the same transcript.
- Oracle specifically recommends context cards when compaction should retain summary, topics, relevant durable records, and recent turns.

Reference: [Use Agent Memory short-term APIs with LangGraph](https://docs.oracle.com/en/database/oracle/agent-memory/26.6/guide/use-api-langgraph.html).

Recommended failure behavior:

- Explicit memory REST or MCP calls fail closed with a clear error.
- Chat retrieval may fail open and continue without memory, while reporting `memory_status="unavailable"`.
- A failed post-response persistence call must not retract an answer already streamed to the client.
- Background extraction should initially be opt-in. Explicit "remember this" writes offer more predictable behavior for the first release.

## B5. Backend Verification

Follow TDD for each slice:

- Unit tests for identity derivation and exact scope enforcement.
- Unit tests for model and OCI adapter translation.
- Service tests for result serialization and exception mapping.
- API tests for authentication, validation, and destructive operations.
- MCP registration and tool-contract tests.
- Chat tests proving:
  - Successful turns persist once.
  - Failed turns do not persist.
  - Streaming reconnects and retries do not duplicate messages.
  - Disabled memory retains existing behavior.
  - "History off" does not silently become "automatic durable memory on."
- Real Oracle integration tests for schema initialization, thread and message storage, search, TTL, update, deletion, extraction, and context cards.
- A multi-instance test or simulation showing that two server processes can load the same thread without relying on local `HistoryStore` state.

Run only the relevant test modules, then Ruff on touched files and `pyright .`, consistent with repository rules.

Backend exit gate: REST, MCP, and built-in chat can use the same service; restart persistence works; exact-user tests pass; the feature remains off by default.

# Plan 2: OpenTelemetry and SigNoz

The SDK emits standard Python logs under `oracleagentmemory` but does not configure handlers or tracing. Those logs can already flow through the repository's opt-in OTEL log pipeline in `src/server/app/otel/setup.py`. Oracle recommends INFO in production and DEBUG only in controlled troubleshooting.

Reference: [Oracle Agent Memory logging guidance](https://docs.oracle.com/en/database/oracle/agent-memory/26.6/guide/get-started.html).

## O1. Manual Memory Spans

Add spans around the service boundary rather than modifying or monkey-patching the SDK:

- `agent_memory.initialize`
- `agent_memory.thread.create`
- `agent_memory.messages.append`
- `agent_memory.messages.get`
- `agent_memory.search`
- `agent_memory.context_card`
- `agent_memory.memory.add`
- `agent_memory.memory.update`
- `agent_memory.memory.delete`
- `agent_memory.thread.delete`
- `agent_memory.extraction.wait`

Low-cardinality attributes:

- `aio.memory.operation`
- `aio.memory.outcome`
- `aio.memory.record_type`
- `aio.memory.search_strategy`
- `aio.memory.result_count`
- `aio.memory.max_results`
- `aio.memory.extraction_mode`
- `aio.memory.context_compacted`
- `db.system=oracle`

Do not attach content, queries, metadata, user or thread identifiers, credentials, or hashes of those identifiers. Hashes would still introduce high cardinality and can enable correlation.

Add span events for queue-full, timeout, fail-open, retry, and schema-policy outcomes.

## O2. Logs and Correlation

- Set `oracleagentmemory` to inherit the application's configured log level.
- Keep production at INFO.
- Confirm SDK structured `extra` fields survive OTEL export.
- Extend redaction tests around SDK exception and diagnostic records.
- Ensure logs correlate with the active memory span.
- Keep log export opt-in, as it is today.

## O3. SigNoz Assets

Extend the existing source-of-truth dashboard JSON under `helm/observability/signoz/` with:

- Memory operations per second by operation.
- p50 and p95 memory latency.
- Memory error and timeout rate.
- Search result count and zero-result rate.
- Context-card generation latency.
- Append and extraction latency.
- Fail-open chat count.
- Schema initialization or upgrade failures.

Add alerts for:

- Sustained memory error percentage.
- Search or append p95 breach.
- Background extraction queue-full events.
- Memory traffic silence when the feature is enabled.
- Repeated schema initialization failures.

Prefer span-derived charts first. The current implementation configures traces and logs but not a dedicated metrics pipeline, so adding an OTEL metrics provider is unnecessary for the first release. The Helm OTEL controls already provide endpoint, protocol, sampling, resource, and log-export settings in `helm/values.yaml`.

Observability exit gate: one chat trace shows retrieval, LLM activity, persistence, and extraction as correlated spans; dashboards import through the existing bootstrap script; no memory content appears in exported telemetry.

# Plan 3: Streamlit Integration

## S1. Minimal Recommended UI

Replace the ambiguous "History and Context" control in `src/client/app/core/sidebar.py` with separate concepts:

- **Use conversation context**
- **Use durable memory**
- **Automatically learn memories** - opt-in
- **New conversation**

"New conversation" should rotate `thread_id`; it must not call cascading `delete_thread`.

Show a small completion annotation:

- Memory used: yes or no.
- Number and types of memories retrieved.
- Memory persistence status.
- Context compacted: yes or no.

Add an expander displaying the non-sensitive memory records used for the answer, similar to the existing Vector Search and SQL detail expanders.

## S2. User-Controlled Memory Actions

Add message-level actions:

- **Remember this**
- **Review before remembering**
- **Forget this memory**

This provides an explicit-memory workflow before automatic extraction becomes the default. It also helps users understand the distinction between conversation history and durable memory.

## S3. Memory Manager in the Toolkit

Add an "Agent Memory" tab under Tools:

- Search current-user memory.
- Filter by record type and metadata.
- View source thread and expiry where permitted.
- Add or edit an explicit fact, preference, or guideline.
- Delete one memory with confirmation.
- Forget an entire conversation with stronger confirmation.
- Show retention and auto-extraction policy as read-only operator settings.

Do not offer "all users" browsing unless the application gains a real administrator authorization boundary.

## S4. Conversation Management

Once stable identity exists:

- Provide a conversation list with titles, updated time, and current thread.
- Start, resume, rename, and forget conversations.
- Persist the active conversation ID independently of Streamlit's random `optimizer_client`.
- Keep short-term history toggles independent from long-term memory consent.

Streamlit exit gate: users can see when memory influenced an answer, explicitly remember or forget information, start a new conversation without deleting durable memories, and never gain access to another scope by changing client-side state.

# Suggested Delivery Order

1. Identity and SDK/database compatibility spike.
2. Service layer plus REST API.
3. Read, add, and search MCP tools.
4. Persistent chat transcript behind a disabled-by-default feature flag.
5. Long-term retrieval and context-card compaction.
6. OTEL spans and log correlation.
7. SigNoz dashboards and alerts.
8. Minimal Streamlit controls and transparency.
9. Toolkit memory manager and automatic extraction opt-in.
10. Documentation, Helm configuration, rollout, and upgrade guidance.

The built-in chatbot should use memory deterministically while memory is also exposed through MCP. Letting the model decide whether to call memory is appropriate for external agents; it is not reliable enough to be the sole persistence and retrieval mechanism for AI Optimizer's own chat runtime.
