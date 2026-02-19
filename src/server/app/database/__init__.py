"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database initialization utilities for the FastAPI server.
"""

import json
import logging
from typing import TYPE_CHECKING, Dict, Optional, Tuple
from pydantic import ValidationError

import oracledb

from server.app.oci import get_all_oci_profiles
from server.app.oci.settings import oci_config_to_entry

from .config import DatabaseSettings, DatabaseState, create_pool, get_database_settings
from .schema import SCHEMA_DDL
from .settings import entry_to_db_settings, load_settings, registry_to_persisted, save_settings
from .sql import execute_sql

if TYPE_CHECKING:
    from server.app.api.v1.schemas.databases import PersistedSettings

LOGGER = logging.getLogger(__name__)


async def close_pool(pool: Optional[oracledb.AsyncConnectionPool]) -> None:
    """Silently close a connection pool if it is not None."""
    if pool is not None:
        try:
            await pool.close()
        except oracledb.Error:
            pass


_DATABASE_REGISTRY: Dict[str, DatabaseState] = {}

_ACTIVE_ALIAS: Dict[str, str] = {"value": "CORE"}


def get_active_alias() -> str:
    """Return the is_current active database alias."""

    return _ACTIVE_ALIAS["value"]


def set_active_alias(alias: str) -> None:
    """Set the is_current database alias."""

    _ACTIVE_ALIAS["value"] = alias


def clear_database_registry() -> None:
    """Remove all tracked database aliases."""

    _DATABASE_REGISTRY.clear()


def register_database(settings: DatabaseSettings) -> DatabaseState:
    """Store or update the state for a database alias.

    If the alias already exists, updates its settings while preserving
    runtime state (usable, pool).  Otherwise creates a new DatabaseState.
    """

    existing = _DATABASE_REGISTRY.get(settings.alias)
    if existing is not None:
        existing.settings = settings
        return existing
    state = DatabaseState(settings=settings)
    _DATABASE_REGISTRY[state.alias] = state
    return state


def get_registered_database(alias: str) -> Optional[DatabaseState]:
    """Return the stored state for ``alias`` if present."""

    return _DATABASE_REGISTRY.get(alias)


def get_all_registered_databases() -> list[DatabaseState]:
    """Return all registered database states."""

    return list(_DATABASE_REGISTRY.values())


def remove_registered_database(alias: str) -> bool:
    """Remove a database alias from the registry. Returns True if it existed."""

    return _DATABASE_REGISTRY.pop(alias, None) is not None


async def initialize_schema(
    db_settings: DatabaseSettings | None = None,
) -> Optional[oracledb.AsyncConnectionPool]:
    """Create database schema using oracledb if configuration is present.

    When *db_settings* is ``None`` (startup path), falls back to the CORE
    alias built from environment variables. When provided (endpoint path),
    uses the given settings directly.

    Returns the connection pool on success so callers can manage its
    lifecycle. When configuration is incomplete or connection fails, the
    failure is logged and ``None`` is returned without interrupting startup.
    """
    if db_settings is None:
        db_settings = get_database_settings()
    state = register_database(db_settings)
    if not state.settings.has_credentials():
        LOGGER.info("Skipping Oracle schema initialization: alias=%s missing credentials.", state.alias)
        return None

    pool = None
    try:
        pool = await create_pool(state.settings)
        async with pool.acquire() as conn:
            await execute_sql(conn, "SELECT 1 FROM DUAL")
            conn.autocommit = True
            for ddl in SCHEMA_DDL:
                await execute_sql(conn, ddl)
        state.usable = True
        state.pool = pool
        LOGGER.info("Oracle schema initialized")
        return pool
    except oracledb.Error as exc:  # pragma: no cover - exercised via integration tests
        LOGGER.warning("Oracle schema initialization failed")
        LOGGER.warning("Database error: %s", exc)
        state.usable = False
        await close_pool(pool)
        return None


async def load_persisted_databases() -> None:
    """Load persisted database configs from aio_settings after CORE init."""

    persisted, pool = await load_core_settings()
    if pool is None:
        return

    if persisted is not None:
        # Restore active alias
        set_active_alias(persisted.client_settings.database.alias)

        # Load non-CORE databases from persisted configs
        for entry in persisted.database_configs:
            if entry.alias == "CORE":
                continue
            if get_registered_database(entry.alias) is not None:
                continue
            db_settings = entry_to_db_settings(entry)
            try:
                await initialize_schema(db_settings)
            except (oracledb.Error, ValueError):
                LOGGER.warning("Failed to restore persisted database alias=%s", entry.alias)

    # Persist current DB state. Preserve any OCI configs already in the
    # persisted data — the OCI registry hasn't been populated yet so we
    # must carry forward whatever was stored rather than overwriting with [].
    try:
        persisted_oci = persisted.oci_configs if persisted is not None else []
        is_current = registry_to_persisted(get_all_registered_databases(), get_active_alias())
        is_current.oci_configs = persisted_oci
        await save_settings(pool, is_current)
    except oracledb.Error:
        LOGGER.warning("Failed to save settings to aio_settings")


# ---------------------------------------------------------------------------
# Core pool helpers (moved here so database.settings has no back-import)
# ---------------------------------------------------------------------------


def get_core_pool():
    """Return the CORE database pool if available, else None."""

    core_db = get_registered_database("CORE")
    if core_db is None or not core_db.usable or core_db.pool is None:
        return None
    return core_db.pool


async def load_core_settings() -> Tuple[Optional["PersistedSettings"], Optional[oracledb.AsyncConnectionPool]]:
    """Load persisted settings from the CORE database.

    Returns (persisted, pool) — both are None when the CORE pool is
    unavailable or the load fails.
    """

    pool = get_core_pool()
    if pool is None:
        return None, None
    try:
        persisted = await load_settings(pool)
    except (oracledb.Error, json.JSONDecodeError, ValidationError):
        LOGGER.warning("Failed to load persisted settings from aio_settings")
        return None, None
    return persisted, pool


async def persist_settings() -> None:
    """Persist current registry state to aio_settings."""

    pool = get_core_pool()
    if pool is None:
        return
    oci_configs = [oci_config_to_entry(p).model_dump() for p in get_all_oci_profiles()]

    try:
        current = registry_to_persisted(
            get_all_registered_databases(),
            get_active_alias(),
            oci_configs,
        )
        await save_settings(pool, current)
    except oracledb.Error:
        LOGGER.warning("Failed to persist settings")
