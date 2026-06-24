"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP tool: Vector Store Discovery.
"""
# spell-checker:ignore genai fastmcp vectorstores hnsw litellm oraclevs

import contextlib
import logging
from typing import Optional

from fastmcp import Context
from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy

from server.app.core.mcp import mcp
from server.app.core.settings import resolve_client
from server.app.database.config import DdsConnectionError
from server.app.database.registry import discover_vector_stores
from server.app.embed.schemas import VectorStoreConfig
from server.app.embed.vector_store import generate_vs_metadata
from server.app.models.litellm_utils import find_model
from server.app.models.schemas import ModelIdentity

from .schemas import (
    VectorStoreListResponse,
    VectorTable,
    get_database_pool,
)

LOGGER = logging.getLogger(__name__)


def _find_embedding_model_config(embedding_model: Optional[ModelIdentity]):
    """Look up the ModelConfig for an embedding model, or return None."""
    if not embedding_model or not embedding_model.provider or not embedding_model.id:
        return None
    return find_model(embedding_model.provider, embedding_model.id, model_type="embed", enabled_only=True)


def _is_model_usable(embedding_model: Optional[ModelIdentity]) -> bool:
    """Check if an embedding model is enabled and its endpoint is reachable."""
    mc = _find_embedding_model_config(embedding_model)
    return mc is not None and mc.usable


async def _vs_discovery_impl(
    filter_enabled_models: bool = True,
    client: str = "CONFIGURED",
) -> VectorStoreListResponse:
    """Implementation of vector storage discovery."""
    try:
        vector_search = resolve_client(client).vector_search

        # Discovery disabled — use configured vector store from settings
        if not vector_search.discovery:
            LOGGER.info("Discovery disabled — using configured vector store settings")
            embedding_model = ModelIdentity(provider=vector_search.provider, id=vector_search.id)
            if vector_search.chunk_size is None or vector_search.chunk_overlap is None:
                return VectorStoreListResponse(
                    parsed_tables=[],
                    status="error",
                    error="Vector search settings incomplete — chunk_size and chunk_overlap are required",
                )
            table_name, table_comment = generate_vs_metadata(
                embedding_model=embedding_model,
                chunk_size=vector_search.chunk_size,
                chunk_overlap=vector_search.chunk_overlap,
                distance_strategy=vector_search.distance_strategy or "",
                index_type=vector_search.index_type or "HNSW",
                alias=vector_search.alias,
                description=vector_search.description,
            )
            if not table_name:
                return VectorStoreListResponse(
                    parsed_tables=[],
                    status="error",
                    error="Vector search settings incomplete — cannot determine table name",
                )

            distance_strategy = None
            if vector_search.distance_strategy:
                with contextlib.suppress(ValueError):
                    distance_strategy = DistanceStrategy(vector_search.distance_strategy)

            configured_table = VectorTable(
                table_name=table_name,
                table_comment=f"GENAI: {table_comment}" if table_comment else None,
                parsed=VectorStoreConfig(
                    vector_store=table_name,
                    alias=vector_search.alias,
                    description=vector_search.description,
                    embedding_model=embedding_model,
                    chunk_size=vector_search.chunk_size,
                    chunk_overlap=vector_search.chunk_overlap,
                    distance_strategy=distance_strategy,
                    index_type=vector_search.index_type,
                ),
            )
            return VectorStoreListResponse(parsed_tables=[configured_table], status="success")

        # Discovery enabled — query database for all vector tables
        pool = get_database_pool(client)
        if not pool:
            return VectorStoreListResponse(
                parsed_tables=[],
                status="error",
                error="No database connection pool available",
            )

        async with pool.acquire() as conn:
            stores = await discover_vector_stores(conn)

        parsed_tables = [
            VectorTable(
                table_name=s.vector_store,
                parsed=s,
            )
            for s in stores
            if s.vector_store
        ]

        if filter_enabled_models:
            original_count = len(parsed_tables)
            parsed_tables = [t for t in parsed_tables if _is_model_usable(t.parsed.embedding_model)]
            LOGGER.info("Filtered %d tables to %d with usable models", original_count, len(parsed_tables))

        return VectorStoreListResponse(parsed_tables=parsed_tables, status="success")
    except DdsConnectionError:
        # Propagate distinctly so callers (e.g. the retriever) surface the DDS error
        # rather than masking it as "no vector stores"; never fall back to the owner.
        raise
    except Exception as ex:
        LOGGER.error("Vector store discovery failed: %s", ex)
        return VectorStoreListResponse(parsed_tables=[], status="error", error=str(ex))


def register_discovery_tool():
    """Register the VS discovery tool with FastMCP."""

    @mcp.tool(
        name="optimizer_vs_discovery",
        title="Vector Store Discovery",
        tags={"vector-search", "optimizer"},
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    )
    async def vector_storage_discovery(
        thread_id: str,
        filter_enabled_models: bool = True,
        ctx: Optional[Context] = None,
    ) -> VectorStoreListResponse:
        """List available vector storage tables in the database."""
        if ctx:
            await ctx.info(f"VS Discovery (Thread ID: {thread_id}, Filter: {filter_enabled_models})")
        try:
            return await _vs_discovery_impl(filter_enabled_models, client=thread_id)
        except DdsConnectionError as ex:
            return VectorStoreListResponse(parsed_tables=[], status="error", error=str(ex))
