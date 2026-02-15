"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Persistence layer for database settings in the aio_settings table.
"""

import json
import logging
from typing import Optional

from server.app.api.v1.schemas.databases import (
    ClientDatabaseSettings,
    ClientSettings,
    DatabaseConfigEntry,
    PersistedSettings,
)
from server.app.database.config import DatabaseSettings, DatabaseState, WalletConfig
from server.app.database.sql import execute_sql

LOGGER = logging.getLogger(__name__)

_SETTINGS_CLIENT = "DEFAULT"


def db_config_to_entry(state: DatabaseState) -> DatabaseConfigEntry:
    """Convert internal DatabaseState to a JSON-serialisable entry."""

    db = state.settings
    return DatabaseConfigEntry(
        alias=db.alias,
        user=db.username,
        password=db.password,
        dsn=db.dsn,
        wallet_password=db.wallet.password,
        wallet_location=db.wallet.location,
        config_dir=db.config_dir,
        tcp_connect_timeout=db.tcp_connect_timeout,
    )


def entry_to_db_settings(entry: DatabaseConfigEntry) -> DatabaseSettings:
    """Convert a persisted JSON entry back to internal DatabaseSettings."""

    return DatabaseSettings(
        alias=entry.alias,
        username=entry.user,
        password=entry.password,
        dsn=entry.dsn,
        wallet=WalletConfig(
            password=entry.wallet_password,
            location=entry.wallet_location,
        ),
        config_dir=entry.config_dir,
        tcp_connect_timeout=entry.tcp_connect_timeout,
    )


def registry_to_persisted(registry: list[DatabaseState], active_alias: str = "DEFAULT") -> PersistedSettings:
    """Build PersistedSettings from the current registry state."""

    return PersistedSettings(
        client_settings=ClientSettings(
            database=ClientDatabaseSettings(alias=active_alias),
        ),
        database_configs=[db_config_to_entry(state) for state in registry],
    )


async def load_settings(pool) -> Optional[PersistedSettings]:
    """Load persisted settings from the aio_settings table."""

    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT settings FROM aio_settings WHERE client = :client",
            {"client": _SETTINGS_CLIENT},
        )

    if not rows or rows[0][0] is None:
        return None

    data = rows[0][0]
    if isinstance(data, str):
        data = json.loads(data)
    return PersistedSettings.model_validate(data)


async def save_settings(pool, persisted: PersistedSettings) -> None:
    """Upsert persisted settings into the aio_settings table."""

    settings_json = persisted.model_dump_json()
    async with pool.acquire() as conn:
        conn.autocommit = True
        await execute_sql(
            conn,
            """
            MERGE INTO aio_settings dst
            USING (SELECT :client AS client FROM DUAL) src
            ON (dst.client = src.client)
            WHEN MATCHED THEN
                UPDATE SET settings = :settings, updated = SYSTIMESTAMP, is_current = TRUE
            WHEN NOT MATCHED THEN
                INSERT (client, settings, created, updated, is_current)
                VALUES (:client, :settings, SYSTIMESTAMP, SYSTIMESTAMP, TRUE)
            """,
            {"client": _SETTINGS_CLIENT, "settings": settings_json},
        )
