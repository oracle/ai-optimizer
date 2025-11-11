"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from typing import Any, Optional, List

from pydantic import BaseModel

import server.api.utils.databases as utils_databases

from common.functions import parse_vs_table
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
    parsed: DatabaseVectorStorage


class VectorStoreListResponse(BaseModel):
    """Response from the optimizer_vs_list tool"""

    raw_results: List[Any]  # Raw SQL results as tuples
    parsed_tables: List[VectorTable]
    status: str  # "success" or "error"
    error: Optional[str] = None


def _execute_vector_table_query(thread_id: str) -> list:
    """Execute SQL query to find vector tables"""
    base_sql = """
        SELECT
            c.owner as schema_name,
            c.table_name,
            t.num_rows,
            t.last_analyzed
        FROM all_tab_columns c
        JOIN all_tables t ON c.owner = t.owner AND c.table_name = t.table_name
        WHERE c.data_type = 'VECTOR'
          AND c.column_name = 'EMBEDDING'
          AND t.num_rows > 0
    """

    db_client = utils_databases.get_client_database(thread_id, False)
    if not db_client or not db_client.connection:
        raise DatabaseConnectionError("No database connection available")

    results = utils_databases.execute_sql(db_client.connection, base_sql)
    logger.info("Found %d vector store tables", len(results))
    return results


def _parse_vector_table_row(row: tuple) -> VectorTable:
    """Parse a single vector table result row into VectorTable object"""
    schema_name, table_name, num_rows, last_analyzed = row
    parsed_info = parse_vs_table(table_name)

    return VectorTable(
        schema_name=schema_name,
        table_name=table_name,
        num_rows=num_rows,
        last_analyzed=last_analyzed.isoformat() if last_analyzed else None,
        parsed=DatabaseVectorStorage(
            vector_store=table_name,
            alias=parsed_info.get("alias"),
            model=parsed_info.get("embedding_model"),
            chunk_size=int(parsed_info.get("chunk_size", 0)) if parsed_info.get("chunk_size", "").isdigit() else 0,
            chunk_overlap=int(parsed_info.get("overlap", 0)) if parsed_info.get("overlap", "").isdigit() else 0,
            distance_metric=parsed_info.get("distance_metric"),
            index_type=parsed_info.get("index_type"),
        ),
    )


async def register(mcp, auth):
    """Invoke Registration of Vector Storage discovery"""

    @mcp.tool(name="optimizer_vs-storage")
    @auth.get("/vs_storage", operation_id="vs_storage")
    def vector_storage(
        thread_id: str, mcp_client: str = "Optimizer", model: str = "UNKNOWN-LLM"
    ) -> VectorStoreListResponse:
        """
        List Oracle Database Vector Storage.

        Searches the Oracle data dictionary to identify tables with VECTOR data type
        columns. Useful for discovering what vector-enabled tables are available for
        semantic search performed in the retriever tool.

        Args:
            thread_id: Optimizer Client ID (chat thread), used for looking up
                configuration (required)
            mcp_client: Name of the MCP client implementation being used
                (Default: Optimizer)
            model: Name and version of the language model being used (optional)

        Returns:
            Dictionary containing:
            - raw_results: List of tuples from SQL query
                (schema_name, table_name, num_rows, last_analyzed)
            - parsed_tables: List of structured objects with schema info and
                parsed metadata
            - status: "success" or "error"
            - error: Error message if status is "error" (optional)
        """
        try:
            logger.info(
                "Searching for vector tables (Thread ID: %s, MCP: %s, Model: %s)", thread_id, mcp_client, model
            )

            # Execute query to find vector tables
            results = _execute_vector_table_query(thread_id)

            # Parse each table row
            parsed_tables = [_parse_vector_table_row(row) for row in results]

            return VectorStoreListResponse(raw_results=results, parsed_tables=parsed_tables, status="success")
        except Exception as ex:
            logger.error("Vector store info retrieval failed: %s", ex)
            return VectorStoreListResponse(raw_results=[], parsed_tables=[], status="error", error=str(ex))
