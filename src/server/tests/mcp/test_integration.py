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

from __future__ import annotations

import json

import pytest

from server.app.core.settings import settings
from server.app.mcp.prompts.registry import register_mcp_prompt

pytestmark = [pytest.mark.integration]

EXPECTED_TOOL_NAMES = {
    "optimizer_vs-discovery",
    "optimizer_vs-rephrase",
    "optimizer_vs-retriever",
    "optimizer_vs-grade",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_tool_result(result) -> dict:
    """Extract and parse JSON from a CallToolResult."""
    assert result.content, "CallToolResult has no content"
    return json.loads(result.content[0].text)


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
            assert tool.inputSchema


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
        "optimizer_vs-discovery",
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
        "optimizer_vs-discovery",
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
        "optimizer_vs-rephrase",
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
        "optimizer_vs-grade",
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
        "optimizer_vs-grade",
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


async def test_client_config_structure(app_client, auth_headers):
    """GET /mcp/client-config returns proper streamableHttp configuration."""
    resp = await app_client.get("/mcp/client-config", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    server_entry = body["mcpServers"]["oracle-ai-optimizer"]
    assert server_entry["type"] == "streamableHttp"
    assert server_entry["transport"] == "streamable-http"
    assert "/mcp/" in server_entry["url"]
    assert "X-API-Key" in server_entry["headers"]


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
        "optimizer_vs-discovery",
        {"thread_id": "db-test-1", "filter_enabled_models": True},
    )

    data = _parse_tool_result(result)
    assert data["status"] == "success"
    table_names = {t["table_name"] for t in data["parsed_tables"]}
    assert "PYTEST_GENAI_TABLE" in table_names
