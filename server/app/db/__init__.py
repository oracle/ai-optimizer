"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database initialization utilities for the FastAPI server.
"""

import logging
from typing import Dict, Optional

import oracledb

from .config import DatabaseSettings, create_pool, get_database_settings
from .schema import SCHEMA_DDL

LOGGER = logging.getLogger(__name__)

_DATABASE_REGISTRY: Dict[str, DatabaseSettings] = {}


def clear_database_registry() -> None:
    """Remove all tracked database aliases."""

    _DATABASE_REGISTRY.clear()


def register_database(settings: DatabaseSettings) -> DatabaseSettings:
    """Store the latest state for a database alias."""

    _DATABASE_REGISTRY[settings.alias] = settings
    return settings


def get_registered_database(alias: str) -> Optional[DatabaseSettings]:
    """Return the stored settings for ``alias`` if present."""

    return _DATABASE_REGISTRY.get(alias)


async def initialize_schema() -> Optional[oracledb.AsyncConnectionPool]:
    """Create database schema using oracledb if configuration is present.

    Returns the connection pool on success so callers can manage its
    lifecycle. When configuration is incomplete or connection fails, the
    failure is logged and ``None`` is returned without interrupting startup.
    """
    settings = register_database(get_database_settings())
    if not settings.has_credentials():
        LOGGER.info("Skipping Oracle schema initialization: alias=%s missing credentials.", settings.alias)
        return None

    pool = None
    try:
        pool = await create_pool(settings)
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1 FROM DUAL")
            conn.autocommit = True
            async with conn.cursor() as cursor:
                for ddl in SCHEMA_DDL:
                    await cursor.execute(ddl)
        register_database(settings.mark_usable(True))
        LOGGER.info("Oracle schema initialized")
        return pool
    except oracledb.Error as exc:  # pragma: no cover - exercised via integration tests
        LOGGER.warning("Oracle schema initialization failed")
        LOGGER.warning("Database error: %s", exc)
        register_database(settings.mark_usable(False))
        if pool is not None:
            try:
                await pool.close()
            except oracledb.Error:
                pass
        return None
