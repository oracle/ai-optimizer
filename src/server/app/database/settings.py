"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Persist and load application settings from the aio_settings table.
"""

import json
import logging
from typing import Optional

from server.app.core.settings import SettingsBase, settings
from .config import get_database_settings
from .sql import execute_sql

LOGGER = logging.getLogger(__name__)

_UPSERT_SQL = """
MERGE INTO aio_settings dst
USING (SELECT :client AS client FROM DUAL) src
ON (dst.client = src.client)
WHEN MATCHED THEN
    UPDATE SET settings = :settings, updated = SYSTIMESTAMP, is_current = 1
WHEN NOT MATCHED THEN
    INSERT (client, settings, created, updated, is_current)
    VALUES (:client, :settings, SYSTIMESTAMP, SYSTIMESTAMP, 1)
"""

_SELECT_SQL = """
SELECT settings FROM aio_settings WHERE client = :client AND is_current = 1
"""


async def persist_settings() -> None:
    """Serialize current settings and upsert into aio_settings."""
    core_cfg = get_database_settings(settings.database_configs, 'CORE')
    if not core_cfg.pool or not core_cfg.usable:
        LOGGER.warning('persist_settings: CORE database not available — skipping')
        return

    payload = json.dumps(
        SettingsBase.model_validate(settings).model_dump(
            mode='json', exclude={'oci_profile_configs'}
        )
    )

    try:
        async with core_cfg.pool.acquire() as conn:
            await execute_sql(conn, _UPSERT_SQL, {'client': 'DEFAULT', 'settings': payload})
            await conn.commit()
        LOGGER.info('Settings persisted to aio_settings')
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning('persist_settings: Failed to persist to database: %s', exc)


async def load_settings() -> Optional[SettingsBase]:
    """Load settings from aio_settings for client='DEFAULT'.

    Returns a SettingsBase instance, or None if the CORE database is not
    available, no matching row exists, or any error occurs.
    """
    core_cfg = get_database_settings(settings.database_configs, 'CORE')
    if not core_cfg.pool or not core_cfg.usable:
        LOGGER.info('load_settings: CORE database not available — skipping')
        return None

    try:
        async with core_cfg.pool.acquire() as conn:
            rows = await execute_sql(conn, _SELECT_SQL, {'client': 'DEFAULT'})

        if not rows:
            LOGGER.info('load_settings: No persisted settings found')
            return None

        raw = rows[0][0]
        data = json.loads(raw) if isinstance(raw, str) else raw
        return SettingsBase.model_validate(data)

    except Exception as exc:  # noqa: BLE001
        LOGGER.warning('load_settings: Failed to load from database: %s', exc)
        return None
