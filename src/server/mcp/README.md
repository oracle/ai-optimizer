# Model Context Protocol (MCP) Implementation

This directory contains the Oracle AI Optimizer and Toolkit's implementation of the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) using [FastMCP](https://github.com/jlowin/fastmcp).

## Overview

The MCP implementation provides:

- **Auto-Discovery System**: Automatically registers tools, prompts, resources, and proxies
- **LangGraph Orchestration**: State machine for intelligent agent workflows
- **Dual-Path Routing**: Optimized handling for internal vector search vs. external tools
- **Token Efficiency**: Prevents context bloat through smart message filtering
- **Extensibility**: Drop-in architecture for adding new MCP components

## Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────┐
│                   MCP SERVER                        │
│  (FastMCP mounted at /mcp)                          │
│  ├─ Tools (auto-discovered)                         │
│  ├─ Prompts (auto-discovered)                       │
│  ├─ Resources (auto-discovered)                     │
│  └─ Proxies (auto-discovered)                       │
└─────────────────┬───────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────┐
│            LANGGRAPH ORCHESTRATION                  │
│  (graph.py - OptimizerState machine)                │
│                                                     │
│  START → initialise → stream_completion             │
│                            ↓                        │
│                    should_continue?                 │
│                            ↓                        │
│                ┌───────────┴──────────┐             │
│                ↓                      ↓             │
│        "vs_orchestrate"           "tools"           │
│         (internal)              (external)          │
│                ↓                      ↓             │
│        Vector Search Pipeline  Standard Execution   │
│        - Rephrase (optional)   - Tool calls         │
│        - Retrieve docs         - ToolMessages       │
│        - Grade relevance                            │
│        - State storage                              │
│                ↓                      ↓             │
│         stream_completion      stream_completion    │
│                ↓                      ↓             │
│               END                    END            │
└─────────────────────────────────────────────────────┘
```

### Directory Structure

```
mcp/
├── __init__.py              # Auto-discovery registration system
├── graph.py                 # LangGraph state machine & orchestration
├── tools/                   # MCP tools (auto-discovered)
│   ├── __init__.py
│   ├── vs_retriever.py      # Vector search retrieval
│   ├── vs_grade.py          # Document relevance grading
│   ├── vs_rephrase.py       # Query rephrasing with context
│   └── vs_tables.py         # Vector store discovery
├── prompts/                 # MCP prompts (auto-discovered)
│   ├── __init__.py
│   ├── defaults.py          # Default system prompts
│   └── cache.py             # Prompt override cache
├── resources/               # MCP resources (auto-discovered)
│   └── __init__.py
└── proxies/                 # MCP proxy servers (auto-discovered)
    ├── __init__.py
    └── sqlcl.py             # Oracle SQLcl MCP proxy
```

## Core Components

### 1. Auto-Discovery System (`__init__.py`)

**Purpose**: Automatically discovers and registers MCP components without manual registration.

**How It Works**: Create a module in the appropriate directory and define a `register()` async function. The system automatically imports all modules and calls their `register()` functions.

**Registration Flow**:
1. `register_all_mcp(mcp, auth)` walks through packages
2. Imports all modules in `tools/`, `prompts/`, `resources/`, `proxies/`
3. Calls each module's `register()` function
4. Components are automatically available via FastMCP

**Benefits**:
- ✅ Zero-boilerplate: Just create a file with `register()` function
- ✅ Plugin architecture: Drop in new components without modifying core code
- ✅ Type safety: FastMCP validates tool schemas automatically

### 2. LangGraph Orchestration (`graph.py`)

**Purpose**: Manages conversational state and orchestrates tool execution through a state machine.

#### State Schema

**`OptimizerState` fields** (`graph.py`):
- `cleaned_messages`: Messages without VS ToolMessages (for LLM)
- `context_input`: Rephrased query used for retrieval
- `documents`: Retrieved documents (formatted string)
- `vs_metadata`: VS metadata (tables searched, etc.)
- `final_response`: OpenAI-format completion response

#### Graph Flow

The graph implements a **dual-path routing architecture** for optimal token efficiency:

**Path 1: Internal VS Orchestration** (Token-Efficient)
```
User asks question
    ↓
LLM calls optimizer_vs-retriever
    ↓
should_continue() → "vs_orchestrate"
    ↓
vs_orchestrate node:
    1. Rephrase query (if chat history exists)
    2. Retrieve documents from vector stores (using rephrased query)
    3. Grade documents for relevance
    4. Store in state["documents"] (NOT in messages)
    ↓
stream_completion:
    - If relevant: Inject documents into system prompt
    - If not relevant: Normal completion (completely transparent)
    ↓
END
```

**Path 2: External Tools** (Standard MCP Pattern)
```
User asks question
    ↓
LLM calls external tool (e.g., sqlcl_query)
    ↓
should_continue() → "tools"
    ↓
tools node (standard LangGraph tool execution):
    - Execute tool
    - Create ToolMessage with results
    - Add to message history
    ↓
stream_completion (LLM sees ToolMessage for context)
    ↓
END
```

#### Why Dual-Path Routing?

**Problem**: Standard MCP tool pattern stores results in ToolMessages that persist in message history.
- Vector search can return 5000+ tokens of documents
- Documents persist across turns: Turn 1 docs + Turn 2 docs + Turn 3 docs = exponential context bloat
- User pays for same documents on every subsequent turn
- **Critical requirement**: When documents not relevant, must be completely transparent (as if VS wasn't called)
- LLM sees all tool responses in standard pattern, can't hide irrelevant results

**Solution**: Internal orchestration for vector search
- ✅ Documents stored in `state["documents"]` (ephemeral)
- ✅ Injected into system prompt only when relevant
- ✅ Filtered out before next turn (no context bloat)
- ✅ Completely transparent when documents aren't relevant
- ✅ External tools (SQLcl, etc.) still work with standard pattern
- ✅ Fast: Single LLM call for final answer (vs multiple round trips in standard pattern)

**Multi-Turn Behavior**:
```
Turn 1: "Hello my name is Mike"
  → VS called → no relevance → normal completion (transparent)

Turn 2: "How do I determine vector index accuracy?"
  → VS (table1) → relevant → completion with documents

Turn 3: "How do I patch Oracle database?"
  → VS (table2) → relevant → completion with NEW documents
  → Documents from Turn 2 NOT in context (topic changed)
```

**Important**: Documents are never persisted across turns. Each turn gets fresh retrieval to avoid context pollution when topics change.

### 3. Vector Search Tools

#### Tool Architecture Pattern

All vector search tools follow this pattern to support both external MCP access and internal graph orchestration:

```python
# Tool wrapper (thin) - for external MCP clients
@mcp.tool(name="optimizer_vs-retriever")
def optimizer_vs_retriever(thread_id: str, question: str, ...) -> VectorSearchResponse:
    """Public MCP tool interface"""
    return _vs_retrieve_impl(thread_id, question, ...)

# Implementation function - shared logic
def _vs_retrieve_impl(thread_id: str, question: str, ...) -> VectorSearchResponse:
    """Actual implementation, called by both wrapper and graph"""
    # ... implementation logic ...
    return VectorSearchResponse(...)
```

**Why This Pattern?**
- External MCP clients call the tool wrapper → works normally
- Internal graph calls `_impl()` directly → bypasses ToolMessage creation
- Zero breaking changes to MCP API
- Single source of truth for logic

#### Available Vector Search Tools

See [Complete Tool Reference](#9-complete-tool-reference) for detailed tool listing.

### 4. Message Filtering (Token Efficiency)

**Problem**: ToolMessages from vector search must be preserved for GUI display but filtered from LLM context.

**Solution**: Metadata-based filtering in `clean_messages()` function (`graph.py`):
- VS ToolMessages marked with `additional_kwargs={"internal_vs": True}`
- `clean_messages()` filters messages based on this metadata marker (not hardcoded tool names)
- External tool ToolMessages preserved (no marker)

**Benefits**:
- ✅ GUI sees documents in `/chat/history` endpoint (full ToolMessages)
- ✅ LLM never sees documents on subsequent turns (filtered out)
- ✅ External tool ToolMessages preserved (needed for context)
- ✅ No hardcoded tool names (extensible)

### 5. Prompts (`prompts/`)

**Default Prompts** (`defaults.py`):

| Prompt Name | Purpose | Used When |
|-------------|---------|-----------|
| `optimizer_basic-default` | Basic chatbot | No tools enabled |
| `optimizer_tools-default` | Tool-aware system prompt | Any tools enabled (VS, SQLcl, etc.) |
| `optimizer_context-default` | Query rephrasing | VS rephrase tool needs context |
| `optimizer_vs-table-selection` | Table selection | Smart retriever selecting vector stores |
| `optimizer_vs-grade` | Document grading | Grading retrieved documents |
| `optimizer_vs-rephrase` | Query rephrasing | Rephrasing with chat history |

**Prompt Override System** (`cache.py`):
- Prompts can be overridden at runtime without restarting server
- Uses `get_prompt_with_override(name)` helper
- Enables prompt engineering experimentation

### 6. Proxies (`proxies/`)

**Oracle SQLcl Proxy** (`sqlcl.py`):
- Registers external `sql -mcp` MCP server as a proxy
- Provides NL2SQL capabilities via SQLcl subprocess
- Creates connection stores: `OPTIMIZER_<DB_NAME>`
- All `sqlcl_*` tools automatically available to LangGraph
- Follows standard MCP tool pattern (ToolMessages in history)

**Security Features**:
- ✅ Read-only mode enforced (DML/DDL blocked)
- ✅ Automatic logging to `DBTOOLS$MCP_LOG` table
- ✅ Session tracking via `V$SESSION.MODULE` and `V$SESSION.ACTION`
- ✅ Principle of least privilege (grant only necessary SELECT privileges)

**Note**: SQLcl results may cause context bloat with large result sets (similar concern to vector search). Architecture supports adding SQLcl tools to filtered set if needed.

### 7. Tool Filtering & Enablement

**Location**: `src/server/api/v1/chat.py`

Tools are filtered based on client settings before being presented to the LLM:
- **Vector Search disabled**: All `optimizer_vs-*` tools removed
- **Vector Search enabled**: Internal-only tools (`optimizer_vs-grade`, `optimizer_vs-rephrase`) hidden from LLM
- **NL2SQL disabled**: All `sqlcl_*` tools removed

**Configuration**: `Settings.tools_enabled` list (default: `["Vector Search", "NL2SQL"]`)

**Effect on Tool Availability**:
- **Both enabled**: LLM sees `optimizer_vs-retriever`, `optimizer_vs-storage`, `sqlcl_*` tools
- **Only Vector Search**: LLM sees `optimizer_vs-retriever`, `optimizer_vs-storage`
- **Only NL2SQL**: LLM sees `sqlcl_*` tools only
- **Neither enabled**: Basic chatbot (no tools)

**Internal-Only Tools**: `optimizer_vs-grade` and `optimizer_vs-rephrase` are never exposed to the LLM - they're only used by the `vs_orchestrate` internal pipeline.

### 8. LLM-Driven Tool Selection

The LLM (e.g., GPT-4o-mini, Claude) decides which tool to invoke based on question semantics and tool descriptions.

**System Prompt Configuration** (`chat.py`):
- Tools enabled → `optimizer_tools-default` prompt
- No tools → `optimizer_basic-default` prompt

**Tool Selection Factors**:

1. **Question Semantics**:
   - Keywords: "documentation", "guide", "how to" → Vector Search
   - Keywords: "count", "list all", "show records", "latest" → NL2SQL
   - Explicit: "based on our docs" → Vector Search
   - Explicit: "from the database" → NL2SQL

2. **Question Structure**:
   - Conceptual/broad questions → Vector Search (semantic understanding)
   - Specific data queries with filters → NL2SQL (structured data access)
   - Aggregations (count, sum, avg) → NL2SQL (computational)

3. **Context Awareness**:
   - Prior tool usage in conversation influences subsequent choices
   - ToolMessages from SQLcl remain in history, providing context for follow-ups

**Example Tool Descriptions**:
- **Vector Search** (`optimizer_vs-retriever`): "Retrieve relevant documents from Oracle Vector Search. Automatically selects the most relevant vector stores based on your question and searches them for semantically similar content."
- **NL2SQL** (`sqlcl_query`): "Execute a SQL query against the Oracle Database and return results. Read-only access for querying tables, views, and system metadata."

**Multi-Tool Scenarios**:

The LLM can chain tools sequentially:
1. **Documentation first, then database**: "Based on our docs, what's the recommended SHMMAX? Then show me the current value."
2. **Database first, then analysis**: "List all DBA users, then check if this matches security guidelines."

### 9. Complete Tool Reference

**Vector Search Tools** (Internal Path):

| Tool | Exposed to LLM | Location | Purpose | Returns |
|------|---------------|----------|---------|---------|
| `optimizer_vs-retriever` | ✅ Yes | `tools/vs_retriever.py` | Semantic search across vector stores (smart table selection, multi-table aggregation) | `VectorSearchResponse` with documents + metadata |
| `optimizer_vs-storage` | ✅ Yes | `tools/vs_tables.py` | List available vector stores (filtered by enabled embedding models) | List of tables with alias, description, model |
| `optimizer_vs-grade` | ❌ No (internal) | `tools/vs_grade.py` | Grade document relevance (binary scoring: yes/no) | `VectorGradeResponse` with relevance + formatted docs |
| `optimizer_vs-rephrase` | ❌ No (internal) | `tools/vs_rephrase.py` | Contextualize query with conversation history (only runs if >2 messages) | `VectorRephraseResponse` with rephrased query |

**NL2SQL Tools** (External Path via SQLcl Proxy):

| Tool | Purpose | Typical Use Case | Returns |
|------|---------|------------------|---------|
| `sqlcl_query` | Execute SELECT queries (read-only) | "List all users created last month" | Rows as JSON array |
| `sqlcl_explain` | Generate execution plan | "Explain the query plan for this SELECT" | Formatted EXPLAIN PLAN |
| `sqlcl_table_info` | Describe table structure | "Show me the columns in the EMPLOYEES table" | Column definitions |
| `sqlcl_list_tables` | List accessible tables | "What tables are in the HR schema?" | Table names |
| `sqlcl_connection_list` | List available connections | Check configured database connections | Connection names |
| `sqlcl_connection_test` | Test connection validity | Verify database connectivity | Status |
| `sqlcl_session_info` | View session details | Monitor current session metadata | Session metadata |
| `sqlcl_activity_log` | Query MCP audit log (DBTOOLS$MCP_LOG) | Audit trail of LLM interactions | Log entries |

**Query Examples by Tool**:

| User Question | Tool Selected | Rationale |
|---------------|---------------|-----------|
| "How do I configure Oracle RAC?" | `optimizer_vs-retriever` | Conceptual, documentation needed |
| "Show me all users created last month" | `sqlcl_query` | Specific data query with filter |
| "What are the recommended PGA settings?" | `optimizer_vs-retriever` | Best practices from docs |
| "What is the current value of PGA_AGGREGATE_TARGET?" | `sqlcl_query` | Current state query |
| "Is our PGA configured per best practices?" | Both (sequential) | Docs for guidelines + DB for current value |

## Usage

### Adding a New MCP Tool

1. Create a file in `tools/` directory (e.g., `tools/my_tool.py`)

2. Define Pydantic response model for type safety

3. Create implementation function (`_my_tool_impl`) with business logic

4. Create tool wrapper decorated with `@mcp.tool(name="optimizer_my-tool")`
   - Prefix with `"optimizer_"` for automatic thread_id injection
   - Tool description shown to LLM
   - Calls implementation function

5. Define `async def register(mcp, auth)` function that registers the tool

6. Tool is automatically discovered and registered on server startup

**Thread ID Injection**: Tools prefixed with `"optimizer_"` automatically receive `thread_id` parameter, enabling access to client-specific settings via `utils_settings.get_client(thread_id)`.

### Adding a New Prompt

1. Create or edit a file in `prompts/` directory

2. Define prompt function returning `PromptMessage` with text content

3. Create prompt wrapper decorated with `@mcp.prompt(name="optimizer_my-prompt", title="...")`
   - Use `get_prompt_with_override()` to support runtime overrides

4. Define `async def register(mcp)` function that registers the prompt

5. Prompt is automatically available via MCP and can be overridden at runtime

### Adding an External MCP Proxy

1. Create a file in `proxies/` directory (e.g., `proxies/my_service.py`)

2. Define `async def register(mcp)` function

3. Call `await mcp.add_server()` with server name, URL, and configuration

4. External server's tools automatically available to LangGraph

## Usage Patterns

### Pattern 1: Vector Search Only (Documentation Query)

**User Query**: *"How do I enable transparent data encryption in Oracle Database?"*

**LLM Decision**: Conceptual question requiring documentation → `optimizer_vs-retriever`

**Flow**:
```
1. LLM calls optimizer_vs-retriever(question="How do I enable TDE?")
2. Graph routes to vs_orchestrate (internal pipeline)
3. VS Pipeline:
   - Searches SECURITY_DOCS, ADMIN_GUIDES, DBA_MANUAL
   - Retrieves 8 relevant documents
   - Grades as relevant
4. Documents injected into system prompt
5. LLM generates response with citations
```

**Result**: Step-by-step guide with documentation sources

### Pattern 2: NL2SQL Only (Database Query)

**User Query**: *"Show me all users created in the last 30 days"*

**LLM Decision**: Specific data query with filter → `sqlcl_query`

**Flow**:
```
1. LLM generates SQL: SELECT username, created FROM dba_users WHERE created >= SYSDATE - 30
2. LLM calls sqlcl_query(connection="OPTIMIZER_DEFAULT", sql="...")
3. Graph routes to tools node (external execution)
4. SQLcl executes query, returns results as JSON
5. ToolMessage persists in conversation history
6. LLM formats results for user
```

**Result**: List of users with creation dates

**Follow-up**: *"What privileges does the first user have?"* → LLM has context from previous ToolMessage, can chain another `sqlcl_query`

### Pattern 3: Multi-Tool Collaboration (Best Practices + Current State)

**User Query**: *"Based on our documentation, what should PGA_AGGREGATE_TARGET be set to? Then show me the current value in our database."*

**LLM Decision**: Requires both documentation AND database query → Sequential tool invocation

**Flow**:
```
1. LLM calls optimizer_vs-retriever(question="What should PGA_AGGREGATE_TARGET be set to?")
2. VS Pipeline returns best practices (20% RAM for OLTP, 40-50% for DW)
3. LLM generates partial response with recommendations
4. LLM calls sqlcl_query(sql="SELECT value FROM v$parameter WHERE name = 'pga_aggregate_target'")
5. SQL returns current value (e.g., 8GB)
6. LLM synthesizes both results:
   - Recommendations from docs: 13GB for OLTP @ 64GB RAM
   - Current value: 8GB
   - Analysis: Below recommended minimum
```

**Result**: Comparison of best practices vs current configuration with actionable recommendations

### Best Practices for Users

**Prompt Engineering**:
- ✅ **Explicit data sources**: "Based on our docs..." or "From the database..."
- ✅ **Use trigger words**: "search", "query", "list", "count", "explain"
- ✅ **Structure complex requests**: "First check docs, then query database"
- ❌ **Avoid ambiguity**: "Tell me about X" (unclear which tool is appropriate)

**When to Use Each Tool**:

| Use Vector Search For | Use NL2SQL For |
|----------------------|----------------|
| How-to guides | Current state queries |
| Troubleshooting | Specific records |
| Concepts & explanations | Aggregations (count, sum) |
| Best practices | Metadata queries |
| Multi-source knowledge | Precise filters (dates, names) |
| Semantic understanding | Computational queries |

## Configuration

### Accessing Client Configuration

MCP tools can access configuration through the bootstrap system:
- **Client settings**: `utils_settings.get_client(thread_id)`
- **Database connection**: `utils_databases.get_client_database(thread_id)`
- **LLM model config**: `utils_models.get(client_settings.model.llm.id)`

### Graph Configuration

Graph behavior configured in `launch_server.py`:
- **Recursion limit**: Max tool call iterations (default: 50)
- **Checkpointer**: Thread-based state persistence (default: `InMemorySaver`, can use persistent checkpointer)

## Key Design Patterns

### 1. Separation of Concerns

- **MCP Tools**: Stateless, pure functions returning Pydantic models
- **Graph Orchestration**: Stateful workflow management (LangGraph)
- **Bootstrap**: Configuration and dependency injection
- **API Endpoints**: HTTP interface (`/mcp` routes)

### 2. Dual Storage for Documents

**Critical Understanding**: Documents are stored in **TWO** places for different purposes.

#### Storage Location 1: `state["documents"]` (Ephemeral)
- **Purpose**: Inject documents into system prompt for CURRENT turn only
- **Lifetime**: Cleared/replaced each turn
- **Access**: Used by `stream_completion()` via `_prepare_messages_for_completion()`
- **Format**: Formatted string ready for prompt injection
- **Why**: Allows conditional injection based on grading without persisting to history

#### Storage Location 2: ToolMessages in `state["messages"]` (Persistent)
- **Purpose**: Preserve documents for GUI display via `/chat/history` endpoint
- **Lifetime**: Persisted across all turns (part of message history)
- **Access**: GUI reads from chat history, displays to user
- **Format**: `json.dumps({"documents": [...], "context_input": "..."})` with raw document objects
- **Why**: User needs to see which documents were used in previous turns
- **Metadata**: Marked with `additional_kwargs={"internal_vs": True}` for filtering

#### Separation via `clean_messages()` Function

Filters ToolMessages marked with `internal_vs=True` metadata before sending to LLM.

**Result**:
- ✅ LLM context: Clean, no document bloat
- ✅ State/History: Complete, includes documents for GUI
- ✅ Token efficiency: Documents not sent to LLM on subsequent turns

#### Flow Diagram
```
Turn 1:
  User asks question → VS retrieves docs
  ├─→ state["documents"] = formatted_docs (for injection THIS turn)
  ├─→ ToolMessage created with raw docs (for GUI/history)
  └─→ LLM sees: system prompt + docs (injected) + question

Turn 2:
  User asks follow-up → clean_messages() called
  ├─→ state["documents"] = new_docs OR "" (replaced)
  ├─→ ToolMessage from Turn 1 FILTERED OUT (not sent to LLM)
  ├─→ GUI /chat/history: Shows Turn 1 ToolMessage ✅
  └─→ LLM sees: clean history (no old docs) + new docs if relevant ✅
```

### 3. Error Handling

All MCP tools and graph nodes follow consistent error handling patterns.

#### Tool Error Handling

- Catch exceptions and log full traceback via `logger.exception()`
- Return error response models with user-friendly messages (no tracebacks)
- Status field indicates success/error

#### Graph Error Handling

Graph errors wrapped via `_create_error_message()` helper (`graph.py`):
- Logs full exception with traceback
- Extracts clean error message (strips embedded tracebacks)
- Returns AIMessage with friendly wrapper + GitHub issues URL

**Key Principles**:
- ✅ Full exception details logged via `logger.exception()` (includes traceback)
- ✅ User receives friendly AIMessage (never raw tracebacks)
- ✅ Actual error message preserved (not generic "an error occurred")
- ✅ Issue URL provided for reporting

#### VS Pipeline Error Defaults

The VS orchestration pipeline uses graceful degradation:

- **Rephrase failure**: Falls back to original question (continues pipeline)
- **Retrieval failure**: Returns empty documents (transparent completion)
- **Grading failure**: Defaults to `relevant="yes"` (conservative - includes documents)

**Rationale**: Preserve user experience even when components fail.

### 4. Oracle Database Type Handling

**Problem**: Oracle database returns `Decimal` types that aren't JSON-serializable by default.

**Solution**: Custom `DecimalEncoder` class in `graph.py` converts Decimal to string during JSON serialization.

**Where Used**:
- ToolMessage creation in `vs_orchestrate()` (when storing raw documents)
- Any JSON serialization of database query results containing numeric types

**Critical**: Without this encoder, ToolMessage creation fails with `TypeError: Object of type Decimal is not JSON serializable`.

### 5. Metadata Streaming Pattern

The graph emits metadata to clients via the **stream writer pattern**, enabling real-time display of search details and token usage.

**Metadata Types**:

1. **VS Metadata** (when vector search is used):
   - `searched_tables`: List of table names
   - `context_input`: Rephrased query string
   - `num_documents`: Integer count

2. **Token Usage** (for all LLM responses):
   - `prompt_tokens`: Integer count
   - `completion_tokens`: Integer count
   - `total_tokens`: Integer count

**Emission Pattern** (`graph.py`):
- Get stream writer via `get_stream_writer()`
- Emit via `writer({"vs_metadata": {...}})` or `writer({"token_usage": {...}})`
- Called from `vs_orchestrate` node and `stream_completion` node

**Storage Pattern**:
- Both metadata types stored in `AIMessage.response_metadata`
- `token_usage` always present for LLM responses
- `vs_metadata` only present when VS used

**Client Access**:
- Extract from message: `message.get("response_metadata", {})`
- Access fields: `metadata.get("vs_metadata")`, `metadata.get("token_usage")`

**Benefits**:
- ✅ Real-time metadata streaming (no polling)
- ✅ Transparent cost tracking (token usage)
- ✅ Debugging visibility (tables searched)
- ✅ Clean separation (metadata != LLM context)

### 6. Thread-Based Multi-Tenancy

Each client session gets a unique `thread_id` (UUID):
- LangGraph maintains separate message history per thread
- Settings stored per client, not global
- In-memory state isolation via `InMemorySaver`
- Enables true multi-user support

**Thread ID Injection**: Tools prefixed with `"optimizer_"` automatically receive `thread_id` parameter, enabling access to client-specific configuration.

## Debugging

### Logging

Use Python logging with module-specific loggers (e.g., `logging_config.logging.getLogger("mcp.graph")`).

View logs in `apiserver_8000.log` (or console output).

**Log Locations**:
- MCP components: `mcp.*` (e.g., `mcp.graph`, `mcp.tools.retriever`)
- API endpoints: `api.v1.*` (e.g., `api.v1.chat`)
- Bootstrap: `bootstrap.*`

### Key Log Messages

**Routing Decisions**:
```
INFO - Routing to vs_orchestrate for VS tools: {'optimizer_vs-retriever'}
INFO - Routing to standard tools node for: {'sqlcl_query'}
```

**Document Injection**:
```
INFO - Injecting 2341 chars of documents into system prompt
INFO - Using system prompt without documents (transparent completion)
```

**VS Pipeline**:
```
INFO - Question rephrased: 'it' -> 'vector index accuracy'
INFO - Retrieved 5 documents from tables: ['DOCS_CHUNKS']
INFO - Grading result: yes (grading_performed: True)
INFO - Documents deemed relevant - storing in state
```

### Common Issues

**Issue**: LLM doesn't invoke VS tools
- **Cause**: System prompt not encouraging tool usage, or question answerable from LLM's training data
- **Solution**: Use `optimizer_tools-default` prompt, try more specific questions referencing "our documentation"
- **Log check**: Look for "Tools being sent" - verify VS tools are in the list

**Issue**: Recursion loop / infinite tool calls
- **Cause**: ToolMessages not created for tool calls, leaving tool_calls unresponded
- **Solution**: Verify `vs_orchestrate()` creates ToolMessages with correct `tool_call_id` matching the AIMessage tool_calls
- **Log check**: Repeated "Routing to vs_orchestrate" (25+ times) indicates this issue
- **Critical fix**: Ensure ToolMessage responses exist for ALL tool_calls in the triggering AIMessage

**Issue**: Documents not appearing in LLM response
- **Cause**: Documents graded as not relevant, or retrieval returned no documents
- **Solution**: Check grading logs for relevance decision, verify vector stores have relevant data
- **Log check**: "Documents deemed NOT relevant" or "No documents retrieved"

**Issue**: Context bloat / high token usage
- **Cause**: `clean_messages()` not filtering ToolMessages properly
- **Solution**: Verify `internal_vs=True` metadata marker is set on VS ToolMessages
- **Log check**: Count SystemMessages in logs - multiple duplicates indicate filtering issue

**Issue**: `TypeError: Object of type Decimal is not JSON serializable`
- **Cause**: Oracle database returns Decimal types, default JSON encoder fails
- **Solution**: Use `DecimalEncoder` when serializing documents with `json.dumps(..., cls=DecimalEncoder)`
- **Location**: `graph.py:36-42` defines the encoder

**Issue**: `AttributeError: 'VectorSearchSettings' object has no attribute 'enabled'`
- **Cause**: Code checking for `.enabled` attribute that doesn't exist in schema
- **Solution**: VS enablement is controlled by tool filtering in `chat.py`, not by settings attribute
- **Fixed in**: `vs_retriever.py` (removed invalid check)

**Issue**: Documents from previous turns appearing in current response
- **Cause**: `clean_messages()` not being called, or metadata filtering not working
- **Solution**: Verify metadata-based filtering in `clean_messages()` function
- **Expected behavior**: Only current turn's documents should be in context

## Testing

### Unit Tests

Test individual tool implementations by calling `_tool_impl()` functions directly with test inputs. Verify response status and expected fields.

### Integration Tests

Test graph orchestration end-to-end by creating `OptimizerState` with test messages and calling graph nodes (e.g., `vs_orchestrate()`). Verify state updates.

### End-to-End Tests

Test via API endpoints (see `tests/server/test_endpoints.py`). Send HTTP requests to `/v1/chat/completions` and verify responses.

## Performance Considerations

### Token Optimization

- **VS Documents**: Ephemeral injection (not persisted in context)
- **Message Filtering**: VS ToolMessages removed before each LLM call
- **Smart Table Selection**: LLM-based semantic matching (vs brute-force search)
- **Document Ranking**: Only top-K documents returned (configurable)

### Latency Optimization

- **Parallel Execution**: LangGraph executes independent nodes concurrently
- **Caching**: Prompt overrides cached in memory
- **Connection Pooling**: Database connections reused via connection pool
- **Async/Await**: Non-blocking I/O throughout

## Migration Notes

### From Inline Nodes to MCP Tools

The codebase migrated from inline LangGraph nodes to MCP tools for vector search (Nov 2025). Legacy reference file: `pre_mcp_chatbot.py` (root directory).

**Key Changes**:
- ✅ Vector search now MCP tools (externally accessible)
- ✅ Graph uses `vs_orchestrate` node for internal pipeline
- ✅ Documents stored in state, not message history
- ✅ Metadata-based filtering (no hardcoded tool names)
- ✅ Dual-path routing (VS vs external tools)
- ✅ DecimalEncoder for Oracle Decimal types
- ✅ Comprehensive error handling with user-friendly messages

**Deprecated**:
- ⚠️ `src/server/agents/chatbot.py` - replaced by `graph.py`
- ⚠️ `pre_mcp_chatbot.py` - reference only, can be deleted

### Implementation History

**Major Milestones** (Nov 2025):
1. ✅ OptimizerState schema updated (`documents`, `context_input` fields)
2. ✅ VS orchestration node with internal pipeline
3. ✅ Document injection in `_prepare_messages_for_completion()`
4. ✅ Dual-path routing via `should_continue()`
5. ✅ Metadata-based message filtering
6. ✅ Error handling and graceful degradation
7. ✅ System prompt refactoring (tools-agnostic)

**Critical Bug Fixes**:
- Fixed infinite recursion loop (missing ToolMessage responses)
- Fixed DecimalEncoder for Oracle types
- Removed invalid `.enabled` attribute check
- Fixed metadata-based filtering pattern

## References

- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [LangGraph Documentation](https://python.langchain.com/docs/langgraph)
- [Oracle AI Vector Search](https://docs.oracle.com/en/database/oracle/oracle-database/23/vecse/)
- Architecture Details: `CLAUDE.md` (project root)

## Contributing

### Code Style

- Follow PEP 8
- Run `pylint src/server/mcp/` before committing
- Target: 10.00/10 (no warnings/errors)

### Adding New Features

1. Read `CLAUDE.md` for architecture overview
2. Review this README for implementation patterns
3. Follow existing tool/prompt structure
4. Add tests for new components
5. Update this README if adding new patterns

### Reporting Issues

- GitHub Issues: https://github.com/oracle/ai-optimizer/issues
- Include: logs, configuration, minimal reproduction case
