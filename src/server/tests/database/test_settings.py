"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for persist_settings() against a real Oracle container.
"""
# pylint: disable=redefined-outer-name

import json

import pytest

from server.app.core.settings import SettingsBase, settings
from server.app.database import init_core_database, close_pool
from server.app.database.config import get_database_settings
from server.app.database.model import DatabaseConfig
from server.app.database.settings import persist_settings
from server.app.database.sql import execute_sql
from server.tests.conftest import TEST_DB_CONFIG


pytestmark = [pytest.mark.db, pytest.mark.anyio]

_READ_SQL = "SELECT client, settings FROM aio_settings WHERE client = :client"
_DELETE_SQL = "DELETE FROM aio_settings WHERE client = :client"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def core_pool(oracle_db_container):
    """Create a CORE pool, bootstrap schema, inject into settings, then clean up."""
    del oracle_db_container

    cfg = DatabaseConfig(
        alias='CORE',
        username=TEST_DB_CONFIG['db_username'],
        password=TEST_DB_CONFIG['db_password'],
        dsn=TEST_DB_CONFIG['db_dsn'],
    )

    pool = await init_core_database(cfg)
    assert pool is not None, 'Failed to initialise CORE pool against container'

    saved = list(settings.database_configs)
    settings.database_configs = [cfg]

    # Clean any leftover rows from previous test runs
    async with pool.acquire() as conn:
        await execute_sql(conn, _DELETE_SQL, {'client': 'DEFAULT'})
        await conn.commit()

    yield cfg

    # Teardown: restore settings and close pool
    settings.database_configs = saved
    await close_pool(pool)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _read_aio_settings(cfg: DatabaseConfig) -> list:
    """SELECT the persisted row for client='DEFAULT'."""
    async with cfg.pool.acquire() as conn:
        rows = await execute_sql(conn, _READ_SQL, {'client': 'DEFAULT'})
    return rows or []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_persist_settings_inserts_row(core_pool):
    """persist_settings() should INSERT a row on first call."""
    await persist_settings()

    rows = await _read_aio_settings(core_pool)
    assert len(rows) == 1
    client, payload = rows[0]
    assert client == 'DEFAULT'

    data = json.loads(payload) if isinstance(payload, str) else payload
    assert 'database_configs' in data
    assert 'env' in data


async def test_persist_settings_upsert_updates(core_pool):
    """Two calls should result in one row with the latest value."""
    original_level = settings.log_level

    await persist_settings()

    # Mutate a setting
    settings.log_level = 'DEBUG'
    try:
        await persist_settings()

        rows = await _read_aio_settings(core_pool)
        assert len(rows) == 1

        data = json.loads(rows[0][1]) if isinstance(rows[0][1], str) else rows[0][1]
        assert data['log_level'] == 'DEBUG'
    finally:
        settings.log_level = original_level


async def test_persist_settings_no_pool_is_noop(core_pool):
    """When the pool is removed, persist_settings() is a graceful no-op."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        # Should not raise
        await persist_settings()
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable


async def test_persist_settings_round_trip_json(core_pool):
    """Persisted JSON should deserialize back into SettingsBase with matching fields."""
    await persist_settings()

    rows = await _read_aio_settings(core_pool)
    assert len(rows) == 1

    raw = json.loads(rows[0][1]) if isinstance(rows[0][1], str) else rows[0][1]
    restored = SettingsBase.model_validate(raw)

    assert restored.env == settings.env
    assert restored.server_port == settings.server_port
    assert restored.log_level == settings.log_level
    assert restored.api_key == settings.api_key
