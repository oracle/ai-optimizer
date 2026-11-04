"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for fail-closed startup settings persistence.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.app.core.settings import settings
from server.app.database.schemas import DatabaseConfig
from server.app.database.settings import (
    SettingsPersistenceError,
    load_settings,
    persist_settings,
    row_exists,
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@pytest.fixture(autouse=True)
def _restore_database_configs():
    saved = list(settings.database_configs)
    yield
    settings.database_configs = saved


def _set_core_pool() -> MagicMock:
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    config = DatabaseConfig(alias="CORE", usable=True)
    config.pool = pool
    settings.database_configs = [config]
    return pool


async def test_persist_settings_required_pool():
    settings.database_configs = []

    with pytest.raises(SettingsPersistenceError, match="CORE database unavailable"):
        await persist_settings(raise_on_error=True)


async def test_row_exists_propagates_startup_query_failure():
    _set_core_pool()
    with (
        patch("server.app.database.settings.execute_sql", new_callable=AsyncMock, side_effect=RuntimeError("lost")),
        pytest.raises(SettingsPersistenceError, match="row check failed"),
    ):
        await row_exists("CONFIGURED", raise_on_error=True)


async def test_load_settings_propagates_startup_query_failure():
    _set_core_pool()
    with (
        patch("server.app.database.settings.execute_sql", new_callable=AsyncMock, side_effect=RuntimeError("lost")),
        pytest.raises(SettingsPersistenceError, match="load_settings failed"),
    ):
        await load_settings("CONFIGURED", raise_on_error=True)


async def test_load_settings_keeps_malformed_payload_distinct_from_query_failure():
    _set_core_pool()
    with patch(
        "server.app.database.settings.execute_sql",
        new_callable=AsyncMock,
        return_value=[("not-json",)],
    ):
        result = await load_settings("CONFIGURED", raise_on_error=True)

    assert result is None
