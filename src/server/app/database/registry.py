"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database initialization utilities for the server.
"""

# spell-checker: ignore genai enquote oraclevs vectorstores
import asyncio
import json
import logging

import oracledb
from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy

from server.app.embed.schemas import VectorStoreConfig
from server.app.models.schemas import ModelIdentity

from .config import close_pool, create_pool
from .objects import RENAME_DDL, REQUIRED_SCHEMA_INDEXES, REQUIRED_SCHEMA_TABLES, SCHEMA_DDL
from .schemas import DatabaseConfig
from .sql import execute_sql, validate_vs_table_name

LOGGER = logging.getLogger(__name__)

_DISCOVERY_TIMEOUT_SECONDS = 2.0
_STRICT_DDL_ERROR_CODES = frozenset()


class CoreSchemaInitializationError(RuntimeError):
    """Raised when CORE schema bootstrap postconditions are not satisfied."""


class CoreDatabaseInitializationError(RuntimeError):
    """Raised when CORE connection or schema initialization fails."""


def _catalog_query(object_type: str, names: frozenset[str]) -> str:
    quoted_names = ", ".join(f"'{name}'" for name in sorted(names))
    catalog = {"table": "user_tables", "index": "user_indexes"}[object_type]
    return f"SELECT {object_type}_name FROM {catalog} WHERE {object_type}_name IN ({quoted_names})"


async def verify_core_schema(conn: oracledb.AsyncConnection) -> None:
    """Verify every required CORE table and index exists."""
    table_rows = await execute_sql(
        conn,
        _catalog_query("table", REQUIRED_SCHEMA_TABLES),
        ignored_error_codes=_STRICT_DDL_ERROR_CODES,
    )
    index_rows = await execute_sql(
        conn,
        _catalog_query("index", REQUIRED_SCHEMA_INDEXES),
        ignored_error_codes=_STRICT_DDL_ERROR_CODES,
    )
    present_tables = {row[0].upper() for row in table_rows or []}
    present_indexes = {row[0].upper() for row in index_rows or []}
    missing_tables = sorted(REQUIRED_SCHEMA_TABLES - present_tables)
    missing_indexes = sorted(REQUIRED_SCHEMA_INDEXES - present_indexes)
    if missing_tables or missing_indexes:
        details = []
        if missing_tables:
            details.append(f"tables: {', '.join(missing_tables)}")
        if missing_indexes:
            details.append(f"indexes: {', '.join(missing_indexes)}")
        raise CoreSchemaInitializationError(f"CORE schema verification failed; missing {'; '.join(details)}")


async def discover_vector_stores(conn: oracledb.AsyncConnection) -> list[VectorStoreConfig]:
    """Query the database for GENAI vector storage tables.

    Parses JSON metadata from ``all_tab_comments`` rows whose comments
    start with ``GENAI:`` and returns ``VectorStoreConfig`` objects.
    Discovery failures are logged but never prevent a connection from
    being marked usable.
    """
    try:
        sql = """SELECT ut.table_name,
                        REPLACE(utc.comments, 'GENAI: ', '') AS comments
                    FROM all_tab_comments utc, all_tables ut
                    WHERE utc.table_name = ut.table_name
                    AND utc.owner = ut.owner
                    AND utc.comments LIKE 'GENAI:%'"""
        rows = await execute_sql(conn, sql)
        if not rows:
            return []
        stores: list[VectorStoreConfig] = []
        for table_name, comments in rows:
            try:
                comments_dict = json.loads(comments)

                # Legacy field mapping: model -> embedding_model
                if "model" in comments_dict:
                    raw_model = comments_dict.pop("model")
                    if "/" in raw_model:
                        provider, model_id = raw_model.split("/", 1)
                    else:
                        provider, model_id = "unknown", raw_model
                    comments_dict["embedding_model"] = ModelIdentity(provider=provider, id=model_id)

                # Legacy field mapping: distance_metric -> distance_strategy
                if "distance_metric" in comments_dict:
                    comments_dict["distance_strategy"] = DistanceStrategy(comments_dict.pop("distance_metric"))
                elif "distance_strategy" in comments_dict:
                    comments_dict["distance_strategy"] = DistanceStrategy(comments_dict.pop("distance_strategy"))

                # Remove non-schema fields from legacy comments
                comments_dict.pop("parse_status", None)

                stores.append(VectorStoreConfig(vector_store=table_name, **comments_dict))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                LOGGER.warning("Skipping vector store %s - bad metadata: %s", table_name, exc)
        LOGGER.debug("Discovered vector stores: %s", stores)
        return stores
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        LOGGER.warning("Vector store discovery failed: %s", exc)
        return []


async def refresh_db_vector_stores(db_config: DatabaseConfig) -> None:
    """Re-run discovery and update ``db_config.vector_stores`` in place.

    No-op when the config has no live pool. Discovery is bounded by
    ``_DISCOVERY_TIMEOUT_SECONDS`` so a stale pool entry or a slow
    listener can't block aggregate callers like ``GET /v1/settings``.
    Errors and timeouts are logged and the cached list is left
    untouched.

    If the config's pool is rotated (e.g. a concurrent
    ``PUT /v1/databases/{alias}``) while discovery is in flight, the
    stale result is discarded rather than overwriting the fresh stores
    published against the new pool — which would also leak into the
    next ``persist_settings()``.
    """
    pool = db_config.pool
    if pool is None or not db_config.usable:
        return

    async def _discover() -> list:
        async with pool.acquire() as conn:
            return await discover_vector_stores(conn)

    try:
        result = await asyncio.wait_for(_discover(), timeout=_DISCOVERY_TIMEOUT_SECONDS)
    except (oracledb.Error, TimeoutError) as exc:
        LOGGER.warning(
            "vector store refresh failed for %s; keeping cached list: %s",
            db_config.alias,
            exc,
        )
        return

    if db_config.pool is pool:
        db_config.vector_stores = result
    else:
        LOGGER.info(
            "vector store refresh for %s discarded: pool rotated during discovery",
            db_config.alias,
        )


async def drop_vector_store(conn: oracledb.AsyncConnection, table_name: str) -> None:
    """Drop a GENAI vector store table.

    Runs ``DROP TABLE <name> PURGE``. Safe to call if the table does not
    exist — ``execute_sql`` silently ignores ORA-00942.
    """
    safe_name = validate_vs_table_name(table_name)
    LOGGER.info("Dropping vector store: %s", table_name)
    await execute_sql(conn, f"DROP TABLE {oracledb.enquote_name(safe_name, capitalize=False)} PURGE")


async def test_connection(db_config: DatabaseConfig) -> None:
    """Test database connectivity by creating a pool and running SELECT 1.

    On success, sets ``db_config.usable = True`` and stores the pool.
    On failure, sets ``db_config.usable = False``, closes the pool, and
    re-raises the exception so the caller can surface the error.
    """
    pool = None
    try:
        pool = await create_pool(db_config)
        async with pool.acquire() as conn:
            await execute_sql(conn, "SELECT 1 FROM DUAL")
            db_config.vector_stores = await discover_vector_stores(conn)
        db_config.usable = True
        db_config.pool = pool
    except (oracledb.Error, ValueError, OSError, TimeoutError):
        db_config.usable = False
        db_config.vector_stores = []
        await close_pool(pool)
        raise


async def init_core_database(
    core_db_config: DatabaseConfig,
) -> oracledb.AsyncConnectionPool:
    """Connect CORE, initialize its schema, and return the live pool."""
    stage = "connection"
    try:
        await test_connection(core_db_config)
        stage = "schema initialization"
        if core_db_config.pool is None:
            raise CoreSchemaInitializationError("CORE connection did not publish a pool")
        async with core_db_config.pool.acquire() as conn:
            conn.autocommit = True
            for rename in RENAME_DDL:
                await execute_sql(conn, rename, ignored_error_codes=_STRICT_DDL_ERROR_CODES)
            for ddl in SCHEMA_DDL:
                await execute_sql(conn, ddl, ignored_error_codes=_STRICT_DDL_ERROR_CODES)
            await verify_core_schema(conn)
        LOGGER.info("Oracle schema initialized")
        return core_db_config.pool
    except Exception as exc:
        core_db_config.usable = False
        core_db_config.vector_stores = []
        await close_pool(core_db_config.pool)
        core_db_config.pool = None
        if isinstance(exc, CoreSchemaInitializationError):
            raise
        LOGGER.error("CORE database %s failed; category=%s", stage, type(exc).__name__)
        raise CoreDatabaseInitializationError(f"CORE database {stage} failed") from None
