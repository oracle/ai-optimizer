"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests — end-to-end MCP protocol flows with the real FastMCP server.

These tests exercise the full MCP protocol path via ``fastmcp.Client``:
argument schema validation, tool dispatch, implementation logic, and
response serialization.  External dependencies (LLM, database) are
avoided by using disabled code paths unless explicitly marked ``@pytest.mark.db``.
"""
# spell-checker: disable

import asyncio
import json
from typing import Any
from urllib.parse import urlparse

import httpx2
import pytest
from fastmcp import Client
from fastmcp import settings as fastmcp_settings
from fastmcp.client.transports import StreamableHttpTransport
from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy

from server.app.core.settings import settings
from server.app.embed.schemas import VectorStoreConfig
from server.app.main import app, mcp_app
from server.app.mcp.prompts.registry import register_mcp_prompt
from server.app.mcp.tools import vs_retriever
from server.app.mcp.tools.schemas import VectorTable
from server.app.models.schemas import ModelIdentity

pytestmark = [pytest.mark.integration]

EXPECTED_TOOL_NAMES = {
    "optimizer_vs_discovery",
    "optimizer_vs_rephrase",
    "optimizer_vs_retriever",
    "optimizer_vs_grade",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_tool_result(result) -> dict:
    """Extract and parse JSON from a CallToolResult."""
    assert result.content, "CallToolResult has no content"
    return json.loads(result.content[0].text)


def _asgi_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx2.Timeout | None = None,
    auth: httpx2.Auth | None = None,
    **kwargs: Any,
) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
        auth=auth,
        **({"timeout": timeout} if timeout is not None else {}),
        **kwargs,
    )


def _vector_table(name: str, alias: str) -> VectorTable:
    return VectorTable(
        table_name=name,
        parsed=VectorStoreConfig(
            alias=alias,
            embedding_model=ModelIdentity(provider="openai", id="embed"),
            distance_strategy=DistanceStrategy.COSINE,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Tool discovery via MCP protocol
# ---------------------------------------------------------------------------


async def test_list_tools_returns_all_four(_register_tools, mcp_client):
    """All 4 VS tools are discoverable via the MCP protocol after registration."""
    tools = await mcp_client.list_tools()
    tool_names = {t.name for t in tools}
    assert EXPECTED_TOOL_NAMES.issubset(tool_names)
    for tool in tools:
        if tool.name in EXPECTED_TOOL_NAMES:
            assert tool.description
            assert tool.input_schema


# ---------------------------------------------------------------------------
# 2. Tool invocation — VS Discovery (disabled path, no DB/LLM)
# ---------------------------------------------------------------------------


async def test_call_discovery_disabled(_register_tools, mcp_client, model_config_factory):
    """Discovery tool returns configured table when discovery is disabled."""
    model_config_factory(provider="openai", model_id="text-embed", model_type="embed")
    vs = settings.client_settings.vector_search
    vs.discovery = False
    vs.provider = "openai"
    vs.id = "text-embed"
    vs.chunk_size = 256
    vs.chunk_overlap = 32
    vs.distance_strategy = "COSINE"
    vs.index_type = "HNSW"
    vs.alias = "DOCS"
    vs.description = "Test documents"

    result = await mcp_client.call_tool(
        "optimizer_vs_discovery",
        {"thread_id": "int-test-1", "filter_enabled_models": False},
    )

    data = _parse_tool_result(result)
    assert data["status"] == "success"
    assert len(data["parsed_tables"]) == 1
    assert data["parsed_tables"][0]["table_name"].startswith("DOCS_OPENAI_TEXT_EMBED")


async def test_call_discovery_incomplete_settings(_register_tools, mcp_client, model_config_factory):
    """Discovery tool returns error when settings are incomplete."""
    model_config_factory(provider="openai", model_id="text-embed", model_type="embed")
    vs = settings.client_settings.vector_search
    vs.discovery = False
    vs.provider = "openai"
    vs.id = "text-embed"
    vs.chunk_size = 256
    vs.chunk_overlap = None  # type: ignore[assignment]
    vs.distance_strategy = "COSINE"

    result = await mcp_client.call_tool(
        "optimizer_vs_discovery",
        {"thread_id": "int-test-2", "filter_enabled_models": False},
    )

    data = _parse_tool_result(result)
    assert data["status"] == "error"
    assert "chunk_size and chunk_overlap" in data["error"]


# ---------------------------------------------------------------------------
# 3. Tool invocation — VS Rephrase (disabled path, no LLM)
# ---------------------------------------------------------------------------


async def test_call_rephrase_disabled(_register_tools, mcp_client):
    """Rephrase tool returns original question when rephrase is disabled."""
    settings.client_settings.vector_search.rephrase = False

    result = await mcp_client.call_tool(
        "optimizer_vs_rephrase",
        {"thread_id": "int-test-3", "question": "What is Oracle?"},
    )

    data = _parse_tool_result(result)
    assert data["status"] == "success"
    assert data["was_rephrased"] is False
    assert data["rephrased_prompt"] == "What is Oracle?"
    assert data["original_prompt"] == "What is Oracle?"


# ---------------------------------------------------------------------------
# 4. Tool invocation — VS Grade (disabled path, no LLM)
# ---------------------------------------------------------------------------


async def test_call_grade_disabled(_register_tools, mcp_client):
    """Grade tool skips grading when disabled and returns documents as relevant."""
    settings.client_settings.vector_search.grade = False

    result = await mcp_client.call_tool(
        "optimizer_vs_grade",
        {
            "thread_id": "int-test-4",
            "question": "What is X?",
            "documents": [{"page_content": "X is a database"}],
        },
    )

    data = _parse_tool_result(result)
    assert data["status"] == "success"
    assert data["relevant"] == "yes"
    assert data["grading_performed"] is False
    assert data["formatted_documents"] == "X is a database"
    assert data["num_documents"] == 1


async def test_call_grade_disabled_empty_docs(_register_tools, mcp_client):
    """Grade tool handles empty document list gracefully."""
    settings.client_settings.vector_search.grade = False

    result = await mcp_client.call_tool(
        "optimizer_vs_grade",
        {
            "thread_id": "int-test-5",
            "question": "Anything?",
            "documents": [],
        },
    )

    data = _parse_tool_result(result)
    assert data["status"] == "success"
    assert data["relevant"] == "yes"
    assert data["num_documents"] == 0
    assert data["formatted_documents"] == ""


# ---------------------------------------------------------------------------
# 5. Prompt operations via MCP protocol
# ---------------------------------------------------------------------------


async def test_list_prompts_after_registration(mcp_client, prompt_config_factory):
    """Prompts registered via register_mcp_prompt are discoverable through MCP."""
    pc1 = prompt_config_factory("int-test-prompt-a", "Prompt A text")
    pc2 = prompt_config_factory("int-test-prompt-b", "Prompt B text")
    register_mcp_prompt(pc1)
    register_mcp_prompt(pc2)

    prompts = await mcp_client.list_prompts()
    prompt_names = {p.name for p in prompts}

    assert "int-test-prompt-a" in prompt_names
    assert "int-test-prompt-b" in prompt_names


async def test_get_prompt_returns_text(mcp_client, prompt_config_factory):
    """Fetching a prompt via MCP returns its text content."""
    pc = prompt_config_factory("int-test-fetch", "Expected prompt text here")
    register_mcp_prompt(pc)

    result = await mcp_client.get_prompt("int-test-fetch")

    assert result.messages
    content_text = result.messages[0].content.text
    assert "Expected prompt text here" in content_text


# ---------------------------------------------------------------------------
# 6. HTTP-level integration (via app_client)
# ---------------------------------------------------------------------------


async def test_healthz_includes_registered_tools(_register_tools, app_client):
    """GET /mcp/healthz lists all 4 registered tool names."""
    resp = await app_client.get("/mcp/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["available_tools"]) >= EXPECTED_TOOL_NAMES


async def test_tools_endpoint_lists_registered_tools(_register_tools, app_client, auth_headers):
    """GET /mcp/tools returns all 4 registered tools."""
    resp = await app_client.get("/mcp/tools", headers=auth_headers)
    assert resp.status_code == 200
    tool_names = {t["name"] for t in resp.json()}
    assert EXPECTED_TOOL_NAMES.issubset(tool_names)


async def test_sdk_v2_models_without_camelcase_bridge(
    _register_tools,
    mcp_client,
    prompt_config_factory,
    app_client,
    auth_headers,
):
    """Python models use SDK v2 names while REST emits MCP wire aliases."""
    assert fastmcp_settings.mcp_camelcase_compat is False

    tools = await mcp_client.list_tools()
    optimizer_tool = next(tool for tool in tools if tool.name == "optimizer_vs_discovery")
    assert optimizer_tool.input_schema["type"] == "object"
    assert optimizer_tool.annotations is not None
    assert optimizer_tool.annotations.read_only_hint is True
    with pytest.raises(AttributeError):
        getattr(optimizer_tool, "inputSchema")

    prompt = prompt_config_factory("sdk-v2-prompt", "SDK v2 prompt text")
    register_mcp_prompt(prompt)
    result = await mcp_client.get_prompt("sdk-v2-prompt")
    assert result.messages[0].content.text == "SDK v2 prompt text"

    response = await app_client.get("/mcp/tools", headers=auth_headers)
    assert response.status_code == 200
    rest_tool = next(tool for tool in response.json() if tool["name"] == "optimizer_vs_discovery")
    assert "inputSchema" in rest_tool
    assert "input_schema" not in rest_tool
    assert rest_tool["annotations"]["readOnlyHint"] is True
    assert "read_only_hint" not in rest_tool["annotations"]


async def test_client_config_structure(app_client, auth_headers):
    """GET /mcp/client-config returns proper streamableHttp configuration."""
    resp = await app_client.get("/mcp/client-config", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    server_entry = body["mcpServers"]["oracle-ai-optimizer"]
    assert server_entry["type"] == "streamableHttp"
    assert server_entry["transport"] == "streamable-http"
    assert urlparse(server_entry["url"]).path.endswith("/mcp")
    assert "X-API-Key" in server_entry["headers"]


async def test_mounted_http_modern_protocol_and_authentication(
    _register_tools,
    app_client,
    auth_headers,
    monkeypatch,
):
    """The mounted endpoint authenticates and serves the modern MCP protocol."""
    missing = await app_client.post("/mcp/", json={})
    wrong = await app_client.post("/mcp/", headers={"X-API-Key": "wrong"}, json={})
    assert missing.status_code == 403
    assert wrong.status_code == 403

    rest_response = await app_client.get("/mcp/tools", headers=auth_headers)
    assert rest_response.status_code == 200
    assert EXPECTED_TOOL_NAMES.issubset({tool["name"] for tool in rest_response.json()})

    prefix = "/optimizer"
    monkeypatch.setattr(settings, "server_url_prefix", prefix)
    monkeypatch.setattr(app, "root_path", prefix)
    config_response = await app_client.get("/mcp/client-config", headers=auth_headers)
    assert config_response.status_code == 200
    server_config = config_response.json()["mcpServers"]["oracle-ai-optimizer"]
    assert server_config["url"] == "http://test/optimizer/mcp"

    transport = StreamableHttpTransport(
        server_config["url"],
        headers=server_config["headers"],
        httpx_client_factory=_asgi_client_factory,
    )
    settings.client_settings.vector_search.rephrase = False

    async with mcp_app.router.lifespan_context(mcp_app), Client(transport, mode="auto") as client:
        assert client.protocol_version == "2026-07-28"
        assert client.initialize_result is None
        tools = await client.list_tools()
        assert EXPECTED_TOOL_NAMES.issubset({tool.name for tool in tools})

        result = await client.call_tool(
            "optimizer_vs_rephrase",
            {"thread_id": "mounted-http", "question": "What is Oracle?"},
        )

    assert _parse_tool_result(result)["rephrased_prompt"] == "What is Oracle?"


async def test_retriever_reports_ordered_phase_progress(_register_tools, mcp_client, monkeypatch):
    """The retriever emits request-scoped progress with phase messages."""
    table = _vector_table("DOCS_TABLE", "DOCS")

    async def available_tables(client: str = "CONFIGURED") -> list[VectorTable]:
        return [table]

    async def search_tables(*args: Any) -> None:
        response = args[-1]
        response.searched_tables.append(table.table_name)

    progress_events: list[tuple[float, float | None, str | None]] = []

    async def record_progress(progress: float, total: float | None, message: str | None) -> None:
        progress_events.append((progress, total, message))

    monkeypatch.setattr(vs_retriever, "_get_available_vector_stores", available_tables)
    monkeypatch.setattr(vs_retriever, "get_database_pool", lambda client="CONFIGURED": object())
    monkeypatch.setattr(vs_retriever, "_search_tables", search_tables)

    result = await mcp_client.call_tool(
        "optimizer_vs_retriever",
        {
            "thread_id": "CONFIGURED",
            "question": "How do I configure this?",
            "collection_alias": "DOCS",
        },
        progress_handler=record_progress,
    )

    assert result.is_error is False
    assert progress_events == [
        (1, 4, "discovering vector stores"),
        (2, 4, "selecting tables"),
        (3, 4, "searching selected tables"),
        (4, 4, "preparing results"),
    ]


async def test_mounted_http_cancellation_stops_retriever_work(
    _register_tools,
    auth_headers,
    monkeypatch,
):
    """Cancelling a modern HTTP call stops its handler and table searches."""
    tables = [_vector_table("TABLE_ONE", "ONE"), _vector_table("TABLE_TWO", "TWO")]
    all_started = asyncio.Event()
    all_stopped = asyncio.Event()
    handler_cancelled = asyncio.Event()
    blocker = asyncio.Event()
    started: set[str] = set()
    stopped: set[str] = set()
    cancelled: set[str] = set()
    acquired: list[int] = []
    released: list[int] = []
    results: list[object] = []
    progress_events: list[tuple[float, float | None, str | None]] = []

    class AcquireContext:
        def __init__(self, identifier: int) -> None:
            self.identifier = identifier

        async def __aenter__(self) -> object:
            acquired.append(self.identifier)
            return object()

        async def __aexit__(self, exc_type, exc, traceback) -> bool:
            released.append(self.identifier)
            return False

    class TrackingPool:
        def acquire(self) -> AcquireContext:
            return AcquireContext(len(acquired))

    class SpecFactory:
        @staticmethod
        def from_ll_model_settings(*_args: Any, **_kwargs: Any) -> object:
            return object()

    async def available_tables(client: str = "CONFIGURED") -> list[VectorTable]:
        return tables

    async def select_tables(*args: Any, **kwargs: Any) -> list[str]:
        return [table.table_name for table in tables]

    async def blocking_search(table_name: str, *args: Any, **kwargs: Any) -> list[dict]:
        task = asyncio.current_task()
        started.add(table_name)
        if len(started) == len(tables):
            all_started.set()
        try:
            await blocker.wait()
            raise AssertionError("cancelled search resumed")
        finally:
            if task is not None and task.cancelling():
                cancelled.add(table_name)
            stopped.add(table_name)
            if len(stopped) == len(tables):
                all_stopped.set()

    real_retrieve = vs_retriever._vs_retrieve_impl

    async def tracked_retrieve(*args: Any, **kwargs: Any):
        try:
            return await real_retrieve(*args, **kwargs)
        except asyncio.CancelledError:
            handler_cancelled.set()
            raise

    async def record_progress(progress: float, total: float | None, message: str | None) -> None:
        progress_events.append((progress, total, message))

    monkeypatch.setattr(vs_retriever, "_get_available_vector_stores", available_tables)
    monkeypatch.setattr(vs_retriever, "_select_tables_with_llm", select_tables)
    monkeypatch.setattr(vs_retriever, "LiteLlmModelSpec", SpecFactory)
    monkeypatch.setattr(vs_retriever, "get_database_pool", lambda client="CONFIGURED": TrackingPool())
    monkeypatch.setattr(vs_retriever, "get_client_embed", lambda *args, **kwargs: object())
    monkeypatch.setattr(vs_retriever, "_search_table", blocking_search)
    monkeypatch.setattr(vs_retriever, "_vs_retrieve_impl", tracked_retrieve)

    transport = StreamableHttpTransport(
        "http://test/mcp",
        headers=auth_headers,
        httpx_client_factory=_asgi_client_factory,
    )

    async with mcp_app.router.lifespan_context(mcp_app), Client(transport, mode="2026-07-28") as client:

        async def call_retriever() -> None:
            result = await client.call_tool(
                "optimizer_vs_retriever",
                {"thread_id": "CONFIGURED", "question": "Cancel this search"},
                progress_handler=record_progress,
            )
            results.append(result)

        call = asyncio.create_task(call_retriever())
        await asyncio.wait_for(all_started.wait(), timeout=2)
        progress_at_cancellation = list(progress_events)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(call, timeout=2)
        await asyncio.wait_for(handler_cancelled.wait(), timeout=2)
        await asyncio.wait_for(all_stopped.wait(), timeout=2)
        await asyncio.sleep(0)

    assert started == {"TABLE_ONE", "TABLE_TWO"}
    assert cancelled == started
    assert stopped == started
    assert len(acquired) == len(released) == 2
    assert set(acquired) == set(released)
    assert results == []
    assert progress_events == progress_at_cancellation
    assert all(message != "preparing results" for _, _, message in progress_events)


# ---------------------------------------------------------------------------
# 7. DB-backed discovery (requires Oracle container)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_call_discovery_with_real_db(
    _register_tools,
    mcp_client,
    vector_db_config,
    vector_store_table,
    model_config_factory,
):
    """Discovery tool finds seeded table in a real Oracle database."""
    del vector_store_table
    model_config_factory(provider="openai", model_id="text-embed", model_type="embed", enabled=True)
    settings.client_settings.vector_search.discovery = True

    result = await mcp_client.call_tool(
        "optimizer_vs_discovery",
        {"thread_id": "db-test-1", "filter_enabled_models": True},
    )

    data = _parse_tool_result(result)
    assert data["status"] == "success"
    table_names = {t["table_name"] for t in data["parsed_tables"]}
    assert "PYTEST_GENAI_TABLE" in table_names
