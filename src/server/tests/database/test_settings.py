"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for persist_settings() and load_settings() against a real Oracle container.
"""
# spell-checker: disable

import json
from unittest.mock import AsyncMock, patch

import pytest

from server.app.core.settings import SettingsBase, settings
from server.app.database.config import close_pool
from server.app.database.registry import init_core_database
from server.app.database.schemas import DatabaseConfig
from server.app.database.settings import (
    delete_row,
    load_client_settings,
    load_settings,
    persist_settings,
    row_exists,
)
from server.app.database.sql import execute_sql
from server.tests.conftest import make_core_db_config

pytestmark = [pytest.mark.db]

_READ_SQL = "SELECT client, settings, is_current FROM aio_settings WHERE client = :client"
_DELETE_SQL = "DELETE FROM aio_settings WHERE client = :client"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def core_pool(oracle_db_container):
    """Create a CORE pool and ensure aio_settings is clean before tests."""
    del oracle_db_container

    cfg = make_core_db_config()

    pool = await init_core_database(cfg)
    assert pool is not None

    saved_configs = list(settings.database_configs)
    settings.database_configs = [cfg]

    try:
        async with pool.acquire() as conn:
            await execute_sql(conn, _DELETE_SQL, {"client": "CONFIGURED"})
            await execute_sql(conn, _DELETE_SQL, {"client": "FACTORY"})
            await conn.commit()
        yield cfg
    finally:
        settings.database_configs = saved_configs
        await close_pool(pool)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _read_aio_settings(cfg: DatabaseConfig, client: str = "CONFIGURED") -> list:
    """SELECT the persisted row for the given client."""
    assert cfg.pool is not None
    async with cfg.pool.acquire() as conn:
        rows = await execute_sql(conn, _READ_SQL, {"client": client})
    return rows or []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_persist_settings_inserts_row(core_pool):
    """persist_settings() should INSERT a row on first call."""
    await persist_settings()

    rows = await _read_aio_settings(core_pool)
    assert len(rows) == 1
    client, payload, is_current = rows[0]
    assert client == "CONFIGURED"
    assert is_current == 1

    data = json.loads(payload) if isinstance(payload, str) else payload
    assert "database_configs" in data
    assert "env" in data


async def test_persist_settings_upsert_updates(core_pool):
    """Two calls should result in one row with the latest value."""
    original_level = settings.log_level

    await persist_settings()

    # Mutate a setting
    settings.log_level = "DEBUG"
    try:
        await persist_settings()

        rows = await _read_aio_settings(core_pool)
        assert len(rows) == 1

        data = json.loads(rows[0][1]) if isinstance(rows[0][1], str) else rows[0][1]
        assert data["log_level"] == "DEBUG"
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


async def test_persist_settings_factory_row(core_pool):
    """persist_settings('FACTORY', is_current=False) creates a non-current row."""
    await persist_settings("FACTORY", is_current=False)

    rows = await _read_aio_settings(core_pool, client="FACTORY")
    assert len(rows) == 1
    client, payload, is_current = rows[0]
    assert client == "FACTORY"
    assert is_current == 0

    data = json.loads(payload) if isinstance(payload, str) else payload
    assert "env" in data


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
    # API_KEY is never returned
    assert restored.api_key is None


# ---------------------------------------------------------------------------
# load_settings tests
# ---------------------------------------------------------------------------


async def test_load_settings_returns_settings_base(core_pool):
    """load_settings() returns a SettingsBase after persist_settings()."""
    del core_pool
    await persist_settings()

    result = await load_settings()

    assert isinstance(result, SettingsBase)
    assert result.env == settings.env
    assert result.log_level == settings.log_level
    # API_KEY is never returned
    assert result.api_key is None


async def test_load_settings_empty_table(core_pool):
    """load_settings() returns None when no rows exist."""
    del core_pool
    result = await load_settings()
    assert result is None


async def test_load_settings_no_pool_returns_none(core_pool):
    """load_settings() returns None when CORE pool is unavailable."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        result = await load_settings()
        assert result is None
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable


async def test_load_client_settings_round_trip(core_pool):
    """client_settings is excluded from persistence, so load returns None."""
    del core_pool
    await persist_settings()

    result = await load_client_settings()

    assert result is None


async def test_load_client_settings_error_path(core_pool):
    """JSON decode errors are handled and return None."""
    cfg = core_pool
    assert cfg.pool is not None

    with patch(
        "server.app.database.settings.execute_sql",
        new_callable=AsyncMock,
        return_value=[("not-json",)],
    ) as mock_exec:
        result = await load_client_settings()

    mock_exec.assert_awaited()
    assert result is None


async def test_row_exists_true(core_pool):
    """row_exists() returns True when the row has been persisted."""
    del core_pool
    await persist_settings()
    assert await row_exists("CONFIGURED") is True


async def test_row_exists_false(core_pool):
    """row_exists() returns False when no row exists."""
    del core_pool
    assert await row_exists("CONFIGURED") is False


async def test_row_exists_no_pool(core_pool):
    """row_exists() returns False when CORE pool is unavailable."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        assert await row_exists("CONFIGURED") is False
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable


# ---------------------------------------------------------------------------
# delete_row tests
# ---------------------------------------------------------------------------


async def test_delete_row_removes_row(core_pool):
    """delete_row() removes the specified row."""
    del core_pool
    await persist_settings("TEMP_CLIENT", is_current=False)
    assert await row_exists("TEMP_CLIENT") is True

    await delete_row("TEMP_CLIENT")
    assert await row_exists("TEMP_CLIENT") is False


async def test_delete_row_refuses_factory(core_pool):
    """delete_row() refuses to delete the FACTORY row."""
    del core_pool
    await persist_settings("FACTORY", is_current=False)
    assert await row_exists("FACTORY") is True

    await delete_row("FACTORY")
    assert await row_exists("FACTORY") is True


async def test_load_client_settings_empty_table(core_pool):
    """load_client_settings() returns None when no rows exist."""
    del core_pool
    result = await load_client_settings()
    assert result is None


async def test_load_client_settings_no_pool(core_pool):
    """load_client_settings() returns None when CORE pool is unavailable."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        result = await load_client_settings()
        assert result is None
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable


async def test_delete_row_no_pool(core_pool):
    """delete_row() is a graceful no-op when CORE pool is unavailable."""
    saved_pool = core_pool.pool
    saved_usable = core_pool.usable
    core_pool.pool = None
    core_pool.usable = False

    try:
        await delete_row("CONFIGURED")  # Should not raise
    finally:
        core_pool.pool = saved_pool
        core_pool.usable = saved_usable
