"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai

from typing import Any, Optional, List

from pydantic import BaseModel

import server.api.utils.databases as utils_databases
import server.api.utils.models as utils_models
import server.api.utils.settings as utils_settings

from common.functions import parse_vs_comment, get_vs_table
from common.schema import DatabaseVectorStorage

from common import logging_config

logger = logging_config.logging.getLogger("mcp.tools.vector_storage")


class DatabaseConnectionError(Exception):
    """Raised when database connection is not available"""


class VectorTable(BaseModel):
    """Information about a vector table"""

    schema_name: str
    table_name: str
    num_rows: Optional[int]
    last_analyzed: Optional[str]  # ISO format datetime string
    table_comment: Optional[str]  # Raw table comment JSON
    parsed: DatabaseVectorStorage


class VectorStoreListResponse(BaseModel):
    """Response from the optimizer_vs_list tool"""

    raw_results: List[Any]  # Raw SQL results as tuples
    parsed_tables: List[VectorTable]
    status: str  # "success" or "error"
    error: Optional[str] = None


def execute_vector_table_query(thread_id: str) -> list:
    """Execute SQL query to find vector tables with JSON comments

    Only returns tables that have properly formatted JSON comments.
    Tables without comments are considered unsupported and ignored.
    """
    base_sql = """
        SELECT
            c.owner as schema_name,
            c.table_name,
            tc.comments as table_comment
        FROM all_tab_columns c
        JOIN all_tables t ON c.owner = t.owner AND c.table_name = t.table_name
        JOIN all_tab_comments tc ON c.owner = tc.owner AND c.table_name = tc.table_name
        WHERE c.data_type = 'VECTOR'
          AND tc.comments like 'GENAI%'
    """

    db_client = utils_databases.get_client_database(thread_id, False)
    if not db_client or not db_client.connection:
        raise DatabaseConnectionError("No database connection available")

    results = utils_databases.execute_sql(db_client.connection, base_sql)
    logger.info("Found %d vector store tables", len(results))
    return results


def is_model_enabled(model_id: str) -> bool:
    """Check if an embedding model is enabled in the configuration

    Model ID format: "provider/model-name" (e.g., "openai/text-embedding-3-small")
    Matches against provider and id fields in model configuration.
    """
    if not model_id:
        return False

    # Skip legacy model IDs without provider prefix (e.g., "text-embedding-3-small")
    if "/" not in model_id:
        logger.debug("Skipping legacy model ID without provider prefix: %s", model_id)
        return False

    # Split into provider and model name
    # e.g., "openai/text-embedding-3-small" -> provider="openai", model_name="text-embedding-3-small"
    provider, model_name = model_id.split("/", 1)

    try:
        # Query for enabled embedding models matching both provider and model_id
        models = utils_models.get(
            model_provider=provider, model_id=model_name, model_type="embed", include_disabled=False
        )
        if models:
            logger.debug("Model %s is enabled (found %d configs)", model_id, len(models))
            return True
        logger.info("Model %s not found in enabled embed models", model_id)
        return False
    except utils_models.UnknownModelError:
        logger.info("Model %s (provider=%s, id=%s) not found", model_id, provider, model_name)
        return False
    except Exception as ex:
        logger.warning("Failed to check if model %s is enabled: %s", model_id, ex)
        return False


def build_vector_table(
    table_name: str,
    schema_name: str = "",
    table_comment: Optional[str] = None,
    alias: Optional[str] = None,
    description: Optional[str] = None,
    model: Optional[str] = None,
    chunk_size: int = 0,
    chunk_overlap: int = 0,
    distance_metric: Optional[str] = None,
    index_type: Optional[str] = None,
) -> VectorTable:
    """Build VectorTable from storage parameters"""
    return VectorTable(
        schema_name=schema_name,
        table_name=table_name,
        num_rows=None,
        last_analyzed=None,
        table_comment=table_comment,
        parsed=DatabaseVectorStorage(
            vector_store=table_name,
            alias=alias,
            description=description,
            model=model,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            distance_metric=distance_metric,
            index_type=index_type,
        ),
    )


def parse_vector_table_row(row: tuple) -> VectorTable:
    """Parse a single vector table result row into VectorTable object

    All metadata is extracted from the table comment JSON.
    Tables without comments are filtered out at the SQL level.
    """
    schema_name, table_name, table_comment = row
    parsed = parse_vs_comment(table_comment)

    return build_vector_table(
        table_name=table_name,
        schema_name=schema_name,
        table_comment=table_comment,
        alias=parsed.get("alias"),
        description=parsed.get("description"),
        model=parsed.get("model"),
        chunk_size=int(parsed.get("chunk_size", 0)) if parsed.get("chunk_size") else 0,
        chunk_overlap=int(parsed.get("chunk_overlap", 0)) if parsed.get("chunk_overlap") else 0,
        distance_metric=parsed.get("distance_metric"),
        index_type=parsed.get("index_type"),
    )


def _vs_discovery_impl(
    thread_id: str,
    filter_enabled_models: bool = True,
) -> VectorStoreListResponse:
    """Implementation of vector storage discovery.

    Handles discovery setting:
    - Discovery enabled: queries database for all vector tables
    - Discovery disabled: returns configured vector store from settings
    """
    try:
        # Check if discovery is disabled - use configured vector store instead
        client_settings = utils_settings.get_client(thread_id)
        vector_search = client_settings.vector_search

        if not vector_search.discovery:
            logger.info("Discovery disabled - using configured vector store settings")

            # Generate table name from configured settings
            table_name, table_comment = get_vs_table(
                model=vector_search.model,
                chunk_size=vector_search.chunk_size,
                chunk_overlap=vector_search.chunk_overlap,
                distance_metric=vector_search.distance_metric,
                index_type=vector_search.index_type,
                alias=vector_search.alias,
                description=vector_search.description,
            )

            if not table_name:
                logger.error("Failed to generate table name from vector search settings")
                return VectorStoreListResponse(
                    raw_results=[],
                    parsed_tables=[],
                    status="error",
                    error="Vector search settings incomplete - cannot determine table name",
                )

            # Build VectorTable from configured settings
            configured_table = build_vector_table(
                table_name=table_name,
                table_comment=f"GENAI: {table_comment}" if table_comment else None,
                alias=vector_search.alias,
                description=vector_search.description,
                model=vector_search.model,
                chunk_size=vector_search.chunk_size,
                chunk_overlap=vector_search.chunk_overlap,
                distance_metric=vector_search.distance_metric,
                index_type=vector_search.index_type,
            )

            logger.info("Returning configured vector store: %s", table_name)
            return VectorStoreListResponse(
                raw_results=[],
                parsed_tables=[configured_table],
                status="success",
            )

        # Execute query to find vector tables
        results = execute_vector_table_query(thread_id)

        # Parse each table row
        parsed_tables = [parse_vector_table_row(row) for row in results]

        # Filter by enabled models if requested
        if filter_enabled_models:
            original_count = len(parsed_tables)
            parsed_tables = [table for table in parsed_tables if is_model_enabled(table.parsed.model)]
            logger.info("Filtered %d tables to %d with enabled models", original_count, len(parsed_tables))

        return VectorStoreListResponse(raw_results=results, parsed_tables=parsed_tables, status="success")
    except Exception as ex:
        logger.error("Vector store info retrieval failed: %s", ex)
        return VectorStoreListResponse(raw_results=[], parsed_tables=[], status="error", error=str(ex))


async def register(mcp, auth):
    """Invoke Registration of Vector Storage discovery"""

    # Note: Keep docstring SHORT for small LLMs. See _vs_discovery_impl for full documentation.
    @mcp.tool(name="optimizer_vs-discovery")
    @auth.get("/vs_discovery", operation_id="vs_discovery", include_in_schema=False)
    def vector_storage_discovery(
        thread_id: str,
        filter_enabled_models: bool = True,
        mcp_client: str = "Optimizer",
        model: str = "UNKNOWN-LLM",
    ) -> VectorStoreListResponse:
        """List available vector storage tables in the database."""
        logger.info(
            "VS Discovery (Thread ID: %s, Filter: %s, MCP: %s, Model: %s)",
            thread_id,
            filter_enabled_models,
            mcp_client,
            model,
        )
        return _vs_discovery_impl(thread_id, filter_enabled_models)
