"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from typing import Any, Optional, List

from pydantic import BaseModel

import server.api.utils.databases as utils_databases
import server.api.utils.models as utils_models

from common.functions import parse_vs_comment
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
            t.num_rows,
            t.last_analyzed,
            tc.comments as table_comment
        FROM all_tab_columns c
        JOIN all_tables t ON c.owner = t.owner AND c.table_name = t.table_name
        JOIN all_tab_comments tc ON c.owner = tc.owner AND c.table_name = tc.table_name
        WHERE c.data_type = 'VECTOR'
          AND c.column_name = 'EMBEDDING'
          AND t.num_rows > 0
          AND tc.comments IS NOT NULL
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
            model_provider=provider,
            model_id=model_name,
            model_type="embed",
            include_disabled=False
        )
        if models:
            logger.debug("Model %s is enabled (found %d configs)", model_id, len(models))
            return True
        else:
            logger.info("Model %s not found in enabled embed models", model_id)
            return False
    except utils_models.UnknownModelError:
        logger.info("Model %s (provider=%s, id=%s) not found", model_id, provider, model_name)
        return False
    except Exception as ex:
        logger.warning("Failed to check if model %s is enabled: %s", model_id, ex)
        return False


def parse_vector_table_row(row: tuple) -> VectorTable:
    """Parse a single vector table result row into VectorTable object

    All metadata is extracted from the table comment JSON.
    Tables without comments are filtered out at the SQL level.
    """
    schema_name, table_name, num_rows, last_analyzed, table_comment = row

    # Parse metadata from comment (single source of truth)
    parsed = parse_vs_comment(table_comment)

    return VectorTable(
        schema_name=schema_name,
        table_name=table_name,
        num_rows=num_rows,
        last_analyzed=last_analyzed.isoformat() if last_analyzed else None,
        table_comment=table_comment,
        parsed=DatabaseVectorStorage(
            vector_store=table_name,
            alias=parsed.get("alias"),
            description=parsed.get("description"),  # Optional, may be None
            model=parsed.get("model"),
            chunk_size=int(parsed.get("chunk_size", 0)) if parsed.get("chunk_size") else 0,
            chunk_overlap=int(parsed.get("chunk_overlap", 0)) if parsed.get("chunk_overlap") else 0,
            distance_metric=parsed.get("distance_metric"),
            index_type=parsed.get("index_type"),
        ),
    )


async def register(mcp, auth):
    """Invoke Registration of Vector Storage discovery"""

    @mcp.tool(name="optimizer_vs-storage")
    @auth.get("/vs_storage", operation_id="vs_storage", include_in_schema=False)
    def vector_storage(
        thread_id: str,
        filter_enabled_models: bool = True,
        mcp_client: str = "Optimizer",
        model: str = "UNKNOWN-LLM",
    ) -> VectorStoreListResponse:
        """
        List Oracle Database Vector Storage.

        Searches the Oracle data dictionary to identify tables with VECTOR data type
        columns. Optionally filters to only include tables whose embedding models
        are currently enabled in the configuration.

        Args:
            thread_id: Optimizer Client ID (chat thread), used for looking up
                configuration (required)
            filter_enabled_models: Only return tables with enabled embedding models
                (default: True)
            mcp_client: Name of the MCP client implementation being used
                (Default: Optimizer)
            model: Name and version of the language model being used (optional)

        Returns:
            Dictionary containing:
            - raw_results: List of tuples from SQL query
                (schema_name, table_name, num_rows, last_analyzed, table_comment)
            - parsed_tables: List of structured objects with schema info and
                parsed metadata, filtered by embedding model enabled status
            - status: "success" or "error"
            - error: Error message if status is "error" (optional)
        """
        try:
            logger.info(
                "Searching for vector tables (Thread ID: %s, Filter: %s, MCP: %s, Model: %s)",
                thread_id,
                filter_enabled_models,
                mcp_client,
                model,
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
