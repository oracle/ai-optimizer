"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Persist and load application settings from the aio_settings table.
"""

import json
import logging

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


async def persist_settings() -> None:
    """Serialize current settings and upsert into aio_settings."""
    core_cfg = get_database_settings(settings.database_configs, 'CORE')
    if not core_cfg.pool or not core_cfg.usable:
        LOGGER.warning('persist_settings: CORE database not available — skipping')
        return

    payload = json.dumps(
        SettingsBase.model_validate(settings).model_dump(mode='json')
    )

    async with core_cfg.pool.acquire() as conn:
        await execute_sql(conn, _UPSERT_SQL, {'client': 'DEFAULT', 'settings': payload})
        await conn.commit()
    LOGGER.info('Settings persisted to aio_settings')


async def load_settings() -> None:
    """Load settings from aio_settings (placeholder for future use)."""
