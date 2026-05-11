"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.mcp.tools.vs_discovery.
"""
# spell-checker: disable

from typing import cast

import pytest
from fastmcp.tools.function_tool import FunctionTool

from server.app.core.mcp import mcp
from server.app.core.settings import settings
from server.app.embed.schemas import VectorStoreConfig
from server.app.mcp.tools import vs_discovery
from server.app.mcp.tools.schemas import VectorStoreListResponse, VectorTable
from server.app.models.schemas import ModelIdentity


def test_find_embedding_model_config_basic() -> None:
    """Models without provider/id should return None."""
    assert vs_discovery._find_embedding_model_config(None) is None
    assert vs_discovery._find_embedding_model_config(ModelIdentity(provider=None, id=None)) is None


def test_find_embedding_model_config_found(model_config_factory) -> None:
    """Enabled models should be found."""
    model_config_factory(
        provider="openai",
        model_id="text-embed",
        model_type="embed",
        enabled=True,
    )

    assert vs_discovery._find_embedding_model_config(ModelIdentity(provider="openai", id="text-embed")) is not None


def test_is_model_usable_false_when_unreachable(model_config_factory) -> None:
    """Enabled but unreachable models should be considered unusable."""
    mc = model_config_factory(
        provider="ollama",
        model_id="nomic-embed",
        model_type="embed",
        enabled=True,
    )
    mc.usable = False

    assert vs_discovery._is_model_usable(ModelIdentity(provider="ollama", id="nomic-embed")) is False


def test_is_model_usable_true_when_reachable(model_config_factory) -> None:
    """Enabled and reachable models should be considered usable."""
    model_config_factory(
        provider="openai",
        model_id="text-embed",
        model_type="embed",
        enabled=True,
    )
    # Factory defaults usable=True

    assert vs_discovery._is_model_usable(ModelIdentity(provider="openai", id="text-embed")) is True


async def test_vs_discovery_disabled_returns_configured_table(model_config_factory):
    """When discovery disabled, tool returns configured table metadata."""
    model_config_factory(provider="openai", model_id="text-embed", model_type="embed")
    vs_settings = settings.client_settings.vector_search
    vs_settings.discovery = False
    vs_settings.provider = "openai"
    vs_settings.id = "text-embed"
    vs_settings.chunk_size = 256
    vs_settings.chunk_overlap = 32
    vs_settings.distance_strategy = "UNKNOWN"
    vs_settings.index_type = "HNSW"
    vs_settings.alias = "DOCS"
    vs_settings.description = "Docs table"

    response = await vs_discovery._vs_discovery_impl()

    assert response.status == "success"
    assert len(response.parsed_tables) == 1
    table = response.parsed_tables[0]
    assert table.table_name.startswith("DOCS_OPENAI_TEXT_EMBED")
    assert table.parsed.distance_strategy is None


async def test_vs_discovery_disabled_missing_settings_error(model_config_factory):
    """Missing settings should trigger error response."""
    model_config_factory(provider="openai", model_id="text-embed", model_type="embed")
    vs_settings = settings.client_settings.vector_search
    vs_settings.discovery = False
    vs_settings.provider = "openai"
    vs_settings.id = "text-embed"
    vs_settings.chunk_size = 256
    vs_settings.chunk_overlap = None  # type: ignore[assignment]
    vs_settings.distance_strategy = "COSINE"

    response = await vs_discovery._vs_discovery_impl()

    assert response.status == "error"
    assert response.error == "Vector search settings incomplete — chunk_size and chunk_overlap are required"


async def test_vs_discovery_no_pool_returns_error():
    """Error out when no database pool available."""
    settings.database_configs = []
    settings.client_settings.vector_search.discovery = True

    response = await vs_discovery._vs_discovery_impl()

    assert response.status == "error"
    assert response.error == "No database connection pool available"


@pytest.mark.db
async def test_vs_discovery_filters_without_enabled_model(vector_db_config, vector_store_table):
    """Filtering removes tables lacking enabled models."""
    del vector_store_table
    settings.client_settings.vector_search.discovery = True

    response = await vs_discovery._vs_discovery_impl(filter_enabled_models=True)

    assert response.status == "success"
    assert response.parsed_tables == []


@pytest.mark.db
async def test_vs_discovery_database_round_trip(
    vector_db_config,
    vector_store_table,
    model_config_factory,
):
    """Database-backed discovery returns seeded table."""
    del vector_store_table
    model_config_factory(
        provider="openai",
        model_id="text-embed",
        model_type="embed",
        enabled=True,
    )
    settings.client_settings.vector_search.discovery = True

    response = await vs_discovery._vs_discovery_impl(filter_enabled_models=True)

    assert response.status == "success"
    assert response.parsed_tables
    names = {table.table_name for table in response.parsed_tables}
    assert "PYTEST_GENAI_TABLE" in names


async def test_vs_discovery_exception_path(monkeypatch: pytest.MonkeyPatch):
    """Unexpected errors propagate into error response."""
    settings.client_settings.vector_search.discovery = True

    def _boom(client="CONFIGURED"):
        raise RuntimeError("explode")

    monkeypatch.setattr(vs_discovery, "get_database_pool", _boom)

    response = await vs_discovery._vs_discovery_impl()

    assert response.status == "error"
    assert response.error == "explode"


async def test_register_discovery_tool(monkeypatch: pytest.MonkeyPatch):
    """Registered tool should invoke implementation and emit context info."""

    async def _fake_impl(filter_enabled_models: bool = True, client: str = "CONFIGURED") -> VectorStoreListResponse:
        return VectorStoreListResponse(
            parsed_tables=[
                VectorTable(
                    table_name="T",
                    table_comment=None,
                    parsed=VectorStoreConfig(),
                )
            ],
            status=f"filters={filter_enabled_models}",
        )

    monkeypatch.setattr(vs_discovery, "_vs_discovery_impl", _fake_impl)

    vs_discovery.register_discovery_tool()

    tool = cast(FunctionTool, await mcp.local_provider.get_tool("optimizer_vs-discovery"))

    class _Ctx:
        """Collects MCP context messages."""

        def __init__(self):
            self.messages: list[str] = []

        async def info(self, message: str) -> None:
            self.messages.append(message)

    ctx = _Ctx()
    response = await tool.fn(thread_id="abc", filter_enabled_models=False, ctx=ctx)

    assert response.status == "filters=False"
    assert ctx.messages == ["VS Discovery (Thread ID: abc, Filter: False)"]
