"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for update_database() update-rejection rules.

Rules:
  1. Was working + new fails  → REJECT (422), old config maintained.
  2. Was working + new works  → accept, switch to new config.
  3. Not working + new works  → accept.
  4. Not working + new fails  → accept (200 with ``error`` field).
"""
# spell-checker: disable

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from server.app.api.v1.endpoints.databases import update_database
from server.app.core.settings import settings
from server.app.database.config import close_pool
from server.app.database.registry import test_connection as _test_connection
from server.app.database.schemas import DatabaseConfig, DatabaseUpdate
from server.tests.conftest import make_core_db_config

pytestmark = [pytest.mark.db]

PATCH_PERSIST = "server.app.api.v1.endpoints.databases.persist_settings"


@pytest.fixture
async def usable_config(configure_db_env):
    """A non-CORE DatabaseConfig connected to the real test container."""
    del configure_db_env
    cfg = make_core_db_config(alias="INTEG")
    original = settings.database_configs[:]
    settings.database_configs.append(cfg)
    await _test_connection(cfg)
    assert cfg.usable is True
    yield cfg
    await close_pool(cfg.pool)
    settings.database_configs = original


@pytest.fixture
async def unusable_config(configure_db_env):
    """A non-CORE DatabaseConfig that has never been connected."""
    del configure_db_env
    cfg = DatabaseConfig(alias="INTEG", username="BADUSER", password=SecretStr("badpw"), dsn="//localhost:9999/NOPE")
    original = settings.database_configs[:]
    settings.database_configs.append(cfg)
    yield cfg
    await close_pool(cfg.pool)
    settings.database_configs = original


async def test_rule1_working_to_broken_rejects(usable_config):
    """Rule 1: working → doesn't work = REJECT (422), old config preserved."""
    cfg = usable_config
    original_pool = cfg.pool
    original_dsn = cfg.dsn
    original_vs = cfg.vector_stores[:]

    body = DatabaseUpdate(dsn="//bad-host:9999/NONEXIST")
    with patch(PATCH_PERSIST, new_callable=AsyncMock), pytest.raises(HTTPException) as exc_info:
        await update_database("INTEG", body)

    assert exc_info.value.status_code == 422
    assert cfg.usable is True
    assert cfg.dsn == original_dsn
    assert cfg.pool is original_pool
    assert cfg.vector_stores == original_vs


async def test_rule2_working_to_working_accepts(usable_config):
    """Rule 2: working → works = accept, switch to new config."""
    cfg = usable_config
    old_pool = cfg.pool

    body = DatabaseUpdate(tcp_connect_timeout=30)
    with patch(PATCH_PERSIST, new_callable=AsyncMock):
        result = await update_database("INTEG", body)

    assert cfg.usable is True
    assert cfg.tcp_connect_timeout == 30
    assert cfg.pool is not old_pool  # new pool created
    assert "error" not in result


async def test_rule3_broken_to_working_accepts(unusable_config, configure_db_env):
    """Rule 3: not working → works = accept."""
    del configure_db_env
    cfg = unusable_config
    assert cfg.usable is False

    good = make_core_db_config()
    body = DatabaseUpdate(username=good.username, password=good.password, dsn=good.dsn)
    with patch(PATCH_PERSIST, new_callable=AsyncMock):
        result = await update_database("INTEG", body)

    assert cfg.usable is True
    assert cfg.pool is not None
    assert "error" not in result


async def test_rule4_broken_to_broken_accepts(unusable_config):
    """Rule 4: not working → doesn't work = accept (with error)."""
    cfg = unusable_config
    assert cfg.usable is False

    body = DatabaseUpdate(dsn="//other-bad-host:9999/ALSO_NOPE")
    with patch(PATCH_PERSIST, new_callable=AsyncMock):
        result = await update_database("INTEG", body)

    assert cfg.usable is False
    assert cfg.dsn == "//other-bad-host:9999/ALSO_NOPE"
    assert "error" in result


async def test_rule1_preserves_vector_stores(usable_config):
    """Rule 1 rollback restores vector_stores discovered on the working config."""
    cfg = usable_config
    original_vs = cfg.vector_stores[:]

    body = DatabaseUpdate(dsn="//bad-host:9999/NONEXIST")
    with patch(PATCH_PERSIST, new_callable=AsyncMock), pytest.raises(HTTPException):
        await update_database("INTEG", body)

    assert cfg.vector_stores == original_vs
