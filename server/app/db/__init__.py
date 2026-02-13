"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database initialization utilities for the FastAPI server.
"""

import logging
from typing import Optional

import oracledb

from .config import create_pool, get_database_settings
from .schema import SCHEMA_DDL

LOGGER = logging.getLogger(__name__)


async def initialize_schema() -> Optional[oracledb.AsyncConnectionPool]:
    """Create database schema using oracledb if configuration is present.

    Returns the connection pool on success so callers can manage its
    lifecycle. When configuration is incomplete or connection fails, the
    failure is logged and ``None`` is returned without interrupting startup.
    """

    settings = get_database_settings()
    if settings is None:
        LOGGER.warning("Skipping Oracle schema initialization: required DB_* environment variables missing.")
        return None

    pool = None
    try:
        pool = await create_pool(settings)
        async with pool.acquire() as conn:
            conn.autocommit = True
            async with conn.cursor() as cursor:
                for ddl in SCHEMA_DDL:
                    await cursor.execute(ddl)
        LOGGER.info(
            "Oracle schema initialized (user=%s, dsn=%s)",
            settings.username,
            settings.dsn,
        )
        return pool
    except oracledb.Error as exc:  # pragma: no cover - exercised via integration tests
        LOGGER.warning(
            "Oracle schema initialization failed for user=%s dsn=%s: %s",
            settings.username,
            settings.dsn,
            exc,
        )
        if pool is not None:
            try:
                await pool.close()
            except Exception:
                pass
        return None
