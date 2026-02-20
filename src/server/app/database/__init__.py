"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database initialization utilities for the FastAPI server.
"""

import logging
from typing import Optional

import oracledb

from .config import create_pool, close_pool
from .model import DatabaseConfig
from .schema import SCHEMA_DDL
from .sql import execute_sql

LOGGER = logging.getLogger(__name__)


async def init_core_database(
    core_db_config: DatabaseConfig,
) -> Optional[oracledb.AsyncConnectionPool]:
    """Create database schema using oracledb if configuration is present.

    Returns the connection pool on success so callers can manage its
    lifecycle. When configuration is incomplete or connection fails, the
    failure is logged and ``None`` is returned without interrupting startup.
    """
    pool = None
    try:
        pool = await create_pool(core_db_config)
        async with pool.acquire() as conn:
            await execute_sql(conn, "SELECT 1 FROM DUAL")
            conn.autocommit = True
            for ddl in SCHEMA_DDL:
                await execute_sql(conn, ddl)
        core_db_config.usable = True
        core_db_config.pool = pool
        LOGGER.info("Oracle schema initialized")
        return pool
    except oracledb.Error as exc:  # pragma: no cover - exercised via integration tests
        LOGGER.warning("Oracle schema initialization failed: %s", exc)
        core_db_config.usable = False
        await close_pool(pool)
        return None
