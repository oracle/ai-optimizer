# Migrate the AI Optimizer to FastMCP 4

This ExecPlan is a living document. Keep `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` current while implementation proceeds.

## Purpose

Upgrade the server from FastMCP 3.4.10 to FastMCP 4.1.6 and MCP Python SDK 2.3.0 while preserving the public `/mcp` protocol endpoint, the authenticated REST mirrors below `/mcp`, built-in AgentSpec agents and flows, and the dynamically refreshed SQLcl proxy.

After the migration:

- MCP clients use the sessionless `2026-07-28` protocol;
- the web client still receives MCP metadata with wire-format keys such as `inputSchema`, `outputSchema`, and `readOnlyHint`;
- NL2SQL and Vector Search continue to load MCP tools into LangGraph through AgentSpec;
- SQLcl tools remain available under the `sqlcl_` namespace and can be refreshed when database configuration changes;
- repository code runs with FastMCP's camelCase compatibility bridge disabled.

The implementation is complete when the targeted unit and integration tests pass, the real Oracle database MCP test passes, SQLcl integration passes when SQLcl is installed, Ruff reports no issues in touched files, and `pyright .` passes.

## Progress

- [x] (2026-11-03) Inventory FastMCP, MCP SDK, AgentSpec, LangChain, REST, proxy, documentation, and test usage.
- [x] (2026-11-03) Confirm the current environment already satisfies FastMCP 4's FastAPI, Starlette, and Pydantic floors.
- [x] (2026-11-03) Prove that `fastmcp==4.1.6` and `langchain-mcp-adapters==0.3.2` cannot resolve together.
- [x] (2026-11-03) Prove that `fastmcp==4.1.6`, `langchain[mcp]==1.4.8`, and `pyagentspec==26.3.1` resolve together with `mcp==2.3.0`.
- [x] (2026-11-03) Update dependencies and lock data; verify lock consistency, server imports, and the MCP 2.x dependency paths.
- [x] (2026-11-03) Migrate Python-side MCP models and HTTP clients to SDK v2 conventions.
- [ ] Replace PyAgentSpec's archived MCP adapter path with the first-party LangChain MCP adapter.
- [ ] Replace the SQLcl proxy's FastMCP internal API usage with a stable provider boundary.
- [x] (2026-11-03) Preserve REST wire aliases and Streamlit rendering behavior.
- [ ] Add sessionless protocol coverage and run targeted validation.
- [ ] Update public documentation and record final outcomes.

## Surprises & Discoveries

- Observation: the dependency upgrade is not a single pin change. `fastmcp-slim[client]==4.1.6` requires `mcp>=2.3.0,<3.0.0`, while `langchain-mcp-adapters==0.3.2` requires `mcp>=1.24.0,<2.0.0`.
  Evidence: an isolated `uv` resolution failed with those exact incompatible ranges.

- Observation: `langchain-mcp-adapters` is archived. LangChain 1.4.8 provides the supported replacement under `langchain.mcp`, installed by the `mcp` extra, and requires FastMCP 4.
  Evidence: the locked replacement set resolves FastMCP 4.1.6, MCP SDK 2.3.0, and HTTPX2 2.16.0; the server and `langchain.mcp.MCPAdapter` import successfully.

- Observation: PyAgentSpec 26.3.1 still checks for and imports `langchain_mcp_adapters` inside its LangGraph converter. Keeping the package is impossible under MCP SDK 2.
  Evidence: `_langgraphconverter.py` imports `StreamableHttpConnection` and `load_mcp_tools` from `langchain_mcp_adapters`, and its `langgraph-full` extra declares `langchain-mcp-adapters>=0.2.2`.

- Observation: the project already subclasses PyAgentSpec's converter in `src/server/app/runtime/langgraph/loader.py`. That is the narrowest place to bridge AgentSpec MCP transports, tools, and toolboxes to `langchain.mcp.MCPAdapter` until PyAgentSpec ships native MCP SDK 2 support.

- Observation: MCP SDK v2 model attributes are snake_case in Python while the JSON wire format remains camelCase. The REST mirror currently calls `model_dump()` without aliases, so an unqualified upgrade would change the web-client contract from `inputSchema` to `input_schema`.

- Observation: `src/server/app/agentspec/adapters/mcp.py` passes an `httpx.AsyncClient` to the raw MCP transport. MCP SDK 2's `streamable_http_client` requires `httpx2.AsyncClient`.

- Observation: MCP SDK 2's `streamable_http_client` yields a two-item `(read, write)` transport tuple; the prior SDK also yielded session metadata as a third item.

- Observation: MCP SDK 2 spells the shared protocol exception `MCPError`. The SQLcl integration test used the former `McpError` name.

- Observation: the SQLcl proxy depends on `_create_client_factory`, `FastMCPProvider`, `Namespace`, `_list_tools`, and direct mutation of `mcp.providers`. FastMCP 4.1.6 still contains those symbols, but only `Provider` subclass hooks, `ProxyProvider`, `ProxyClient`, and `FastMCP.add_provider()` are suitable migration boundaries.

- Observation: the existing `httpx` dependency remains necessary for the web client, URL safety checks, model connectivity, and other application HTTP calls. FastMCP supplies HTTPX2 transitively for MCP SDK 2 traffic; it does not replace HTTPX in application code.

## Decision Log

- Decision: target the exact stable pin `fastmcp==4.1.6`; do not use the 4.2 prerelease line.
  Rationale: the project uses exact dependency pins, FastMCP recommends exact production pins, and 4.1.6 is the current stable release on 2026-11-03.
  Date: 2026-11-03.

- Decision: replace `langchain-mcp-adapters==0.3.2` with `langchain[mcp]==1.4.8`.
  Rationale: the old adapter's MCP SDK constraint is unsatisfiable with FastMCP 4 and the package is archived; LangChain's first-party adapter supports MCP SDK 2 and FastMCP 4.
  Date: 2026-11-03.

- Decision: keep `pyagentspec==26.3.1` and add a local compatibility layer in `LiteLlmAgentSpecLoader`.
  Rationale: no newer stable PyAgentSpec release currently provides the required migration, while this repository already owns a custom converter subclass for MCP authentication and result shaping.
  Date: 2026-11-03.

- Decision: preserve camelCase in the REST mirror by serializing MCP SDK models with `model_dump(by_alias=True)` while using snake_case everywhere in Python.
  Rationale: camelCase is the MCP wire format and is already consumed by `src/client/app/content/config/tabs/mcp.py`.
  Date: 2026-11-03.

- Decision: disable FastMCP's camelCase Python compatibility bridge during shared MCP server initialization.
  Rationale: the application targets MCP SDK 2. Snake_case is required inside Python, while camelCase remains confined to MCP and REST serialization boundaries.
  Date: 2026-11-03.

- Decision: support only the modern, sessionless `2026-07-28` protocol at the application level.
  Rationale: the migration establishes the current protocol as the compatibility baseline. Tests, documentation, and project-owned adapters will target modern discovery and request behavior. FastMCP 4 may continue to negotiate an older protocol as framework behavior because it has no server-side version restriction; the project will not add a custom rejection layer or preserve legacy-specific behavior.
  Date: 2026-11-03.

- Decision: register one stable, namespaced SQLcl provider and swap its delegate during refresh.
  Rationale: FastMCP exposes provider addition but no provider removal API. A stable project-owned provider avoids direct mutation of `mcp.providers` and removes dependencies on `_create_client_factory`, `FastMCPProvider`, and `Namespace`.
  Date: 2026-11-03.

## Context and Orientation

`pyproject.toml` currently pins FastMCP 3.4.10 and the archived LangChain MCP adapter. `uv.lock` resolves MCP SDK 1.30.0. FastAPI 0.162.0, Starlette 1.10.0, and Pydantic 2.13.5 already satisfy the FastMCP 4 floors.

`src/server/app/core/mcp.py` owns the shared `FastMCP` server. `src/server/app/main.py` builds `mcp.http_app(path="/")`, wraps it with API-key middleware, combines its lifespan with FastAPI, and mounts it at `/mcp`.

`src/server/app/mcp/tools/` registers four Vector Search tools. Their annotations are supplied as camelCase dictionaries. `src/server/app/mcp/prompts/registry.py` registers prompts through the local provider. `src/server/app/api/mcp/endpoints/{tools,prompts,resources}.py` mirrors protocol metadata to authenticated REST callers. The Streamlit MCP configuration tab consumes the wire-format schema names returned by these endpoints.

`src/server/app/agentspec/adapters/mcp.py` builds AgentSpec transports, connects SQLcl to a selected database, and fetches MCP prompts. It uses raw MCP SDK sessions for the last two operations. `src/server/app/runtime/langgraph/loader.py` subclasses PyAgentSpec's LangGraph loader to preserve sensitive headers and unwrap MCP text content. PyAgentSpec's base implementation currently calls the incompatible `langchain_mcp_adapters` package.

`src/server/app/mcp/proxies/sqlcl.py` launches SQLcl over stdio, verifies its capabilities, sanitizes malformed schema defaults, namespaces the proxy as `sqlcl`, and rebuilds it when database settings change. Its provider lifecycle is the most FastMCP-internal part of the repository.

Relevant upstream references:

- FastMCP 3 to 4 guide: https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3
- FastMCP proxy provider: https://gofastmcp.com/servers/providers/proxy
- LangChain MCP integration: https://docs.langchain.com/oss/python/langchain/mcp
- FastMCP releases: https://github.com/PrefectHQ/fastmcp/releases
- Archived LangChain MCP adapter: https://github.com/langchain-ai/langchain-mcp-adapters

## Plan of Work

### Milestone 1: resolve the MCP SDK 2 dependency graph

Edit `pyproject.toml` so the server dependency set contains:

    fastmcp==4.1.6
    langchain[mcp]==1.4.8

Remove `langchain-mcp-adapters==0.3.2`. Keep the existing `httpx==0.28.1` common dependency because the application imports and uses HTTPX independently of MCP. Do not add `mcp` or `httpx2` to `pyproject.toml`; FastMCP and LangChain supply compatible versions transitively, and `uv.lock` records the exact resolved artifacts.

Regenerate `uv.lock` with `uv lock`. Confirm that it contains FastMCP/FastMCP Slim 4.1.6, MCP 2.3.0, HTTPX2 2.16.0, and no `langchain-mcp-adapters` package. Use `uv sync --extra server --group dev` before validation.

Acceptance for this milestone:

- `uv lock` resolves on every required environment represented in the lock file;
- importing `fastmcp`, `mcp`, `langchain.mcp`, and the project's server modules succeeds;
- `uv.lock` has no MCP SDK 1.x requirement path.

### Milestone 2: migrate SDK models, HTTP transport, and REST aliases

In `src/server/app/agentspec/adapters/mcp.py`, use `httpx2.AsyncClient` for clients passed to `mcp.client.streamable_http.streamable_http_client`. Keep ordinary application HTTP on `httpx`. Replace `isError` and `structuredContent` reads with `is_error` and `structured_content`.

Update MCP model construction and assertions in production and tests:

- use `mime_type` in `ImageContent` construction;
- use `input_schema` and `output_schema` for Python attribute access;
- use `read_only_hint`, `destructive_hint`, `idempotent_hint`, and `open_world_hint` in Python annotation dictionaries;
- update `SimpleNamespace` test doubles to expose `is_error` and `structured_content`.

In the REST mirror endpoints, call `model_dump(by_alias=True)` so their JSON remains in MCP wire form. Strengthen API tests to assert `inputSchema`, `outputSchema`, `_meta`, and camelCase annotation keys and to reject snake_case equivalents in the response. Leave the Streamlit client on the existing camelCase contract.

Add a targeted compatibility test that disables `fastmcp.settings.mcp_camelcase_compat` and exercises tool listing, prompt retrieval, REST serialization, and SQLcl connection error handling. The test must restore the setting after use because it is process-global.

Acceptance for this milestone:

- no production or test code reads bridged camelCase model attributes;
- the REST response consumed by Streamlit is unchanged;
- MCP-focused tests pass with the compatibility bridge disabled.

### Milestone 3: bridge AgentSpec to LangChain's first-party MCP adapter

Keep AgentSpec objects as the portable configuration format. Change only their conversion to LangChain tools.

In `src/server/app/runtime/langgraph/loader.py`:

1. Intercept `pyagentspec.mcp.MCPTool` and `MCPToolBox` in `LiteLlmAgentSpecLoader.convert()` before PyAgentSpec's base converter runs its `langchain_mcp_adapters` availability check.
2. Convert AgentSpec client transports to public FastMCP 4 transport objects:
   - `StdioTransport` to `fastmcp.client.transports.StdioTransport`;
   - `SSETransport` and `SSEmTLSTransport` to `fastmcp.client.transports.SSETransport`;
   - `StreamableHTTPTransport` and `StreamableHTTPmTLSTransport` to `fastmcp.client.transports.StreamableHttpTransport`.
3. Merge `headers` and `sensitive_headers` without writing credentials back into the AgentSpec object.
4. Port the existing TLS behavior to an `httpx2.AsyncClient` factory: use the configured CA as the trust set, require both client certificate and key for mTLS, preserve hostname verification, and apply the AgentSpec read timeout.
5. Build `langchain.mcp.MCPAdapter` from the FastMCP transport, discover tools through `MCPAdapter.list_tools()`, and cache them in `tool_registry` under the existing `<transport id>::<tool name>` keys.
6. Preserve MCPTool selection, MCPToolBox filtering, AgentSpec callback attachment, tool descriptions and schemas, and `_unwrap_tool_content_blocks()` behavior.
7. Raise a specific error for an unsupported AgentSpec transport or auth mode; do not silently fall back to the archived adapter.

Keep this compatibility layer isolated in the loader and give its helper functions project-owned names. Do not create a fake `langchain_mcp_adapters` package. Add a comment identifying PyAgentSpec 26.3.1 as the source of the compatibility boundary so it can be removed after an upstream migration.

Expand `src/server/tests/runtime/langgraph/test_loader.py` to cover:

- Streamable HTTP header merging without mutating the source AgentSpec;
- modern FastMCP transport construction and timeout propagation;
- tool discovery and call execution through an in-process FastMCP server;
- MCPTool selecting one named tool;
- MCPToolBox filtering the NL2SQL allowlist;
- text content unwrapping and structured artifact preservation;
- unsupported transport and TLS configuration failures;
- absence of imports from `langchain_mcp_adapters`.

Run the existing AgentSpec definition tests because their serialized structures are public behavior.

Acceptance for this milestone:

- NL2SQL and Vector Search specs load without `langchain-mcp-adapters` installed;
- loaded LangGraph tools can call an MCP server and preserve current result shapes;
- sensitive headers remain available at runtime and absent from exported AgentSpec data.

### Milestone 4: give the SQLcl proxy a stable provider lifecycle

Refactor `src/server/app/mcp/proxies/sqlcl.py` around a project-owned provider registered once with `mcp.add_provider(provider, namespace="sqlcl")`.

The stable provider holds an optional `ProxyProvider` delegate. Implement the documented `Provider` subclass hooks for tools, resources, templates, and prompts by forwarding to the current delegate. Keep schema-default sanitation in its tool-list path. When no delegate is installed, list methods return empty sequences and get methods return `None`.

Build each delegate with public `ProxyProvider` and `ProxyClient` APIs around the active SQLcl `StdioTransport`. Replace the delegate only after preflight and capability verification succeed. On refresh, make the new delegate visible under `_refresh_lock`, then close the old transport. On failed refresh, clear the delegate, close the old transport, and leave `settings.nl2sql_available` false.

Remove imports and tests for `_create_client_factory`, `FastMCPProvider`, `FastMCPServer`, `Namespace`, and direct `mcp.providers` mutation. Preserve `_verify_backend`, restrict-level validation, connection-store creation, preflight behavior, schema sanitation, and transport closure.

Update `src/server/tests/mcp/proxies/test_sqlcl.py` to assert behavior at the project provider boundary rather than FastMCP construction details. Add a test that refresh swaps delegates without growing the server provider list and a test that an already-discovered proxy tool routes through the active delegate after refresh.

Run `src/server/tests/mcp/proxies/test_sqlcl_integration.py` against the installed SQLcl binary. A missing SQLcl binary may skip these existing guarded tests; record the skip in `Outcomes & Retrospective`.

Acceptance for this milestone:

- one SQLcl provider exists for the process lifetime;
- refresh does not append or remove entries in `mcp.providers`;
- `sqlcl_` tool names and calls survive successful refresh;
- failed refresh removes SQLcl capabilities and closes the active process.

### Milestone 5: exercise sessionless, mounted, and database-backed behavior

Extend `src/server/tests/mcp/test_integration.py` and its fixtures so representative list, call, and prompt flows run with `Client(mcp, mode="auto")`. Assert that the client negotiates the sessionless `2026-07-28` protocol. Do not add `mode="legacy"` coverage or compatibility branches.

Add a mounted HTTP integration test through the FastAPI ASGI app at `/mcp/`. It must prove:

- a missing or wrong `X-API-Key` is rejected;
- a valid key permits modern discovery, tool listing, and one tool call;
- `/mcp/tools` still returns REST metadata rather than protocol traffic;
- the configured root path/prefix does not change the canonical client URL behavior.

Run the real Oracle database test `test_call_discovery_with_real_db` so SDK v2 request parsing, tool execution, serialization, and database discovery are covered together.

Review OpenTelemetry behavior for MCP calls. FastMCP and the raw SDK now use HTTPX2, while the project's generic client instrumentor targets HTTPX. Update `src/server/app/otel/setup.py`, its tests, and `docs/content/advanced-guides/observability/intro.mdx` only for behavior demonstrated by a focused trace test. At minimum, ensure HTTPX2/HTTPCore2 exporter logs remain excluded and remove any claim that the HTTPX instrumentor traces MCP if it no longer does.

Acceptance for this milestone:

- the sessionless protocol lists and calls tools;
- the mounted HTTP endpoint enforces authentication and works with the modern client;
- the real Oracle database discovery test passes;
- observability documentation matches emitted spans.

### Milestone 6: documentation and final cleanup

Update public documentation only where behavior changed:

- `docs/content/guides/mcp-clients.mdx`: state that clients must support the sessionless `2026-07-28` protocol and keep configuration examples in wire format;
- `docs/content/advanced-guides/mcp-custom.mdx`: show snake_case Python annotation fields if the documented argument is a Python model, while retaining camelCase for JSON examples;
- `docs/content/advanced-guides/agents/intro.mdx`: describe the LangChain MCP adapter boundary only if users need it to extend AgentSpec transports;
- `docs/content/advanced-guides/observability/intro.mdx`: record verified HTTPX2/FastMCP trace coverage.

Search the repository once more for every signal in FastMCP's v3-to-v4 checklist: removed imports, camelCase attribute reads, `httpx` clients passed to MCP, `ctx.elicit`, `ctx.sample`, `ctx.list_roots`, `on_initialize`, session-state calls, task decorators, removed tool arguments, and bare script strings passed to `Client`.

Run Ruff formatting only on touched Python files, then Ruff linting on every touched Python file, followed by `pyright .` and the targeted tests below. Fix every report in touched files.

## Concrete Validation Commands

Run from the repository root. Do not run the full test suite.

Dependency and import checks:

    uv lock
    uv sync --extra server --extra client --extra otel --group dev
    uv run python -c "import fastmcp, mcp, httpx2; from langchain.mcp import MCPAdapter"
    uv tree --package fastmcp --depth 2
    uv tree --package mcp --depth 2

Targeted tests:

    uv run pytest src/server/tests/agentspec/adapters/test_mcp.py src/server/tests/agentspec/test_agent_nl2sql.py src/server/tests/agentspec/test_flow_vecsearch.py
    uv run pytest src/server/tests/runtime/langgraph/test_loader.py src/server/tests/runtime/langgraph/test_multi_tool.py
    uv run pytest src/server/tests/mcp src/server/tests/api/test_mcp_tools.py src/server/tests/api/test_mcp_prompts.py src/server/tests/api/test_mcp_resources.py src/server/tests/api/test_mcp_probes.py src/server/tests/api/test_mcp_client_config.py -m "not db"
    uv run pytest src/client/tests/content/config/tabs/test_mcp.py
    uv run pytest src/server/tests/mcp/test_integration.py::test_call_discovery_with_real_db -m db
    uv run pytest src/server/tests/mcp/proxies/test_sqlcl_integration.py

Compatibility bridge check:

    FASTMCP_MCP_CAMELCASE_COMPAT=false uv run pytest src/server/tests/mcp src/server/tests/agentspec/adapters/test_mcp.py src/server/tests/runtime/langgraph/test_loader.py -m "not db"

Static checks:

    uv run ruff format <touched Python files>
    uv run ruff check <touched Python files>
    uv run pyright .

If broader confidence is wanted after review, the user may run additional test groups; this plan does not call the full project suite.

## Idempotence and Recovery

Dependency locking and test commands are repeatable. The SQLcl provider registration must be idempotent: repeated startup registration or refresh calls reuse the same project provider, close superseded transports, and do not grow `mcp.providers`.

If dependency resolution fails, inspect the remaining path to MCP SDK 1.x with `uv tree --invert mcp`; do not force incompatible packages with `--no-deps`. If the AgentSpec bridge fails, keep the dependency migration and bridge changes in the same working state because neither is independently runnable. Reverting the dependency edits and lock file together restores the FastMCP 3 environment.

Tests that mutate the process-global FastMCP server or compatibility setting must restore their original values in fixtures, including on assertion failure. SQLcl integration tests must close transports and child processes in `finally` blocks.

## Interfaces and Dependencies

The implementation should end with these project-owned interfaces:

- `build_mcp_transport(server_url: str, api_key: str) -> pyagentspec.mcp.StreamableHTTPTransport` remains unchanged for callers.
- `LiteLlmAgentSpecLoader` accepts current AgentSpec `MCPTool`, `MCPToolBox`, and supported client transports, but converts them through `langchain.mcp.MCPAdapter`.
- a private project helper converts an AgentSpec client transport to a FastMCP 4 `ClientTransport` without mutating the AgentSpec object.
- a private project HTTPX2 client factory owns TLS, mTLS, timeout, and header construction for AgentSpec MCP traffic.
- a project-owned SQLcl provider subclasses FastMCP's public `Provider` contract, owns an optional `ProxyProvider` delegate, and is registered once under the `sqlcl` namespace.
- REST mirror endpoints intentionally emit aliases with `model_dump(by_alias=True)`.

No application feature in this migration needs background tasks, server-initiated sampling, roots, elicitation, FastMCP session state, OAuth, or custom middleware hooks. If implementation discovers one of those surfaces, pause and update this plan before choosing a migration strategy.

## Outcomes & Retrospective

Milestone 2 is complete. Python code uses MCP SDK 2 snake_case model fields, the application disables FastMCP's legacy camelCase Python bridge before creating the shared server, raw streamable HTTP sessions use HTTPX2 and the SDK 2 stream tuple, and REST mirrors explicitly serialize MCP wire aliases. The targeted MCP and API tests passed with the bridge disabled; focused tool-registration and SQLcl integration tests also passed. Ruff and `pyright .` report no issues.

At migration completion, add the changed AgentSpec and SQLcl provider interfaces, measured protocol-era behavior, and any upstream PyAgentSpec issue that can later remove the local compatibility layer.
