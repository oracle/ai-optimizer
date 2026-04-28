"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Persist and load application settings from the aio_settings table.
"""
# spell-checker: ignore systimestamp

import json
import logging
from typing import Optional

import oracledb

from server.app.core.schemas import ClientSettings
from server.app.core.secrets import REVEAL_KEY
from server.app.core.settings import _PROTECTED_CLIENTS, SettingsBase, settings

from .config import get_core_pool
from .sql import execute_sql

LOGGER = logging.getLogger(__name__)

_UPSERT_SQL = """
MERGE INTO aio_settings dst
USING (SELECT :client AS client FROM DUAL) src
ON (dst.client = src.client)
WHEN MATCHED THEN
    UPDATE SET settings = :settings, updated = SYSTIMESTAMP, is_current = :is_current
WHEN NOT MATCHED THEN
    INSERT (client, settings, created, updated, is_current)
    VALUES (:client, :settings, SYSTIMESTAMP, SYSTIMESTAMP, :is_current)
"""

_SELECT_SQL = """
SELECT settings FROM aio_settings WHERE client = :client
"""

_ROW_EXISTS_SQL = """
SELECT 1 FROM aio_settings WHERE client = :client
"""

_DELETE_SQL = """
DELETE FROM aio_settings WHERE client = :client
"""


async def persist_settings(client: str = "CONFIGURED", is_current: bool = True) -> bool:
    """Serialize current settings and upsert into aio_settings.

    Returns ``True`` on success or when the CORE pool is unavailable
    (best-effort — the in-memory change is kept).  Returns ``False``
    only when a pool exists and the write fails.
    """
    pool = get_core_pool()
    if not pool:
        LOGGER.warning("persist_settings: CORE database not available — skipping")
        return True

    payload = SettingsBase.model_validate(settings).model_dump(
        mode="json",
        context={REVEAL_KEY: True},
        exclude={"oci_configs", "client_settings"},
    )

    try:
        async with pool.acquire() as conn:
            await execute_sql(
                conn,
                _UPSERT_SQL,
                {"client": client, "settings": payload, "is_current": 1 if is_current else 0},
                input_sizes={"settings": oracledb.DB_TYPE_JSON},
            )
            await conn.commit()
        LOGGER.info("Settings persisted to aio_settings (client=%s)", client)
        return True
    except Exception as exc:
        LOGGER.error("persist_settings: Failed to persist to database: %s", exc)
        return False


async def load_settings(client: str = "CONFIGURED") -> Optional[SettingsBase]:
    """Load settings from aio_settings for the given client.

    Returns a SettingsBase instance, or None if the CORE database is not
    available, no matching row exists, or any error occurs.
    """
    pool = get_core_pool()
    if not pool:
        LOGGER.info("load_settings: CORE database not available — skipping")
        return None

    try:
        async with pool.acquire() as conn:
            rows = await execute_sql(conn, _SELECT_SQL, {"client": client})

        if not rows:
            LOGGER.info("load_settings: No persisted settings found for client=%s", client)
            return None

        raw = rows[0][0]
        data = json.loads(raw) if isinstance(raw, str) else raw
        return SettingsBase.model_validate(data)

    except Exception as exc:
        LOGGER.warning("load_settings: Failed to load from database: %s", exc)
        return None


async def load_client_settings(client: str = "CONFIGURED") -> Optional[ClientSettings]:
    """Load client settings from aio_settings for the given client.

    Returns a ClientSettings instance, or None if the CORE database is not
    available, no matching row exists, or any error occurs.
    """
    pool = get_core_pool()
    if not pool:
        LOGGER.info("load_client_settings: CORE database not available — skipping")
        return None

    try:
        async with pool.acquire() as conn:
            rows = await execute_sql(conn, _SELECT_SQL, {"client": client})

        if not rows:
            LOGGER.info("load_client_settings: No settings found for client=%s", client)
            return None

        raw = rows[0][0]
        data = json.loads(raw) if isinstance(raw, str) else raw
        cs_data = data.get("client_settings")
        if cs_data is None:
            return None
        return ClientSettings.model_validate(cs_data)

    except Exception as exc:
        LOGGER.warning("load_client_settings: Failed to load for client=%s: %s", client, exc)
        return None


async def row_exists(client: str) -> bool:
    """Check whether a row exists in aio_settings for the given client."""
    pool = get_core_pool()
    if not pool:
        return False

    try:
        async with pool.acquire() as conn:
            rows = await execute_sql(conn, _ROW_EXISTS_SQL, {"client": client})
        return bool(rows)
    except Exception:
        return False


async def persist_client_settings(client: str, cs: ClientSettings, is_current: bool = False) -> bool:
    """Serialize a ClientSettings object and upsert into aio_settings.

    Returns ``True`` on success or when the CORE pool is unavailable
    (best-effort — the in-memory change is kept).  Returns ``False``
    only when a pool exists and the write fails.
    """
    pool = get_core_pool()
    if not pool:
        LOGGER.warning("persist_client_settings: CORE database not available — skipping")
        return True

    payload = {"client_settings": cs.model_dump(mode="json", context={REVEAL_KEY: True})}

    try:
        async with pool.acquire() as conn:
            await execute_sql(
                conn,
                _UPSERT_SQL,
                {"client": client, "settings": payload, "is_current": 1 if is_current else 0},
                input_sizes={"settings": oracledb.DB_TYPE_JSON},
            )
            await conn.commit()
        LOGGER.info("Client settings persisted to aio_settings (client=%s)", client)
        return True
    except Exception as exc:
        LOGGER.error("persist_client_settings: Failed to persist for client=%s: %s", client, exc)
        return False


async def delete_row(client: str) -> None:
    """Delete a row from aio_settings. Refuses to delete FACTORY or server."""
    if client in _PROTECTED_CLIENTS:
        LOGGER.warning("delete_row: Refusing to delete %s row", client)
        return

    pool = get_core_pool()
    if not pool:
        LOGGER.warning("delete_row: CORE database not available — skipping")
        return

    try:
        async with pool.acquire() as conn:
            await execute_sql(conn, _DELETE_SQL, {"client": client})
            await conn.commit()
        LOGGER.info("Deleted aio_settings row for client=%s", client)
    except Exception as exc:
        LOGGER.warning("delete_row: Failed to delete for client=%s: %s", client, exc)
