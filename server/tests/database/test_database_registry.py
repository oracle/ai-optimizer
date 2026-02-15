"""Integration tests for database alias usability behavior."""

from __future__ import annotations

import importlib
import sys

import pytest

from ..conftest import TEST_DB_CONFIG


def _reload_db_module():
    """Reload DB modules to pick up fresh settings and registry state."""

    for module in (
        "server.app.database",
        "server.app.database.config",
        "server.app.core.config",
    ):
        sys.modules.pop(module, None)
    return importlib.import_module("server.app.database")


def _clear_registry(db_module) -> None:
    db_module.clear_database_registry()


@pytest.mark.anyio
async def test_default_alias_unusable_without_credentials(monkeypatch):
    """DEFAULT alias should exist but be unusable when env credentials are absent."""

    # Force settings reload without .env-backed credentials
    monkeypatch.setenv("AIO_ENV", "pytest-empty")
    for key in (
        "AIO_DB_USERNAME",
        "AIO_DB_PASSWORD",
        "AIO_DB_DSN",
        "AIO_DB_WALLET_PASSWORD",
        "AIO_DB_WALLET_LOCATION",
    ):
        monkeypatch.delenv(key, raising=False)

    db_module = _reload_db_module()
    _clear_registry(db_module)

    pool = await db_module.initialize_schema()

    assert pool is None
    default_alias = db_module.get_registered_database("DEFAULT")
    assert default_alias is not None
    assert default_alias.usable is False
    assert default_alias.username is None
    assert default_alias.password is None
    assert default_alias.dsn is None


@pytest.mark.db
@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.anyio
async def test_default_alias_becomes_usable_after_successful_bootstrap(configure_db_env, oracle_connection):
    """Valid env credentials should yield a usable DEFAULT alias."""

    del configure_db_env
    del oracle_connection

    db_module = _reload_db_module()
    _clear_registry(db_module)

    pool = await db_module.initialize_schema()

    assert pool is not None
    default_alias = db_module.get_registered_database("DEFAULT")
    assert default_alias is not None
    assert default_alias.usable is True
    assert default_alias.username == TEST_DB_CONFIG["db_username"]
    assert default_alias.dsn == TEST_DB_CONFIG["db_dsn"]

    await pool.close()


@pytest.mark.db
@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.usefixtures("configure_db_env")
async def test_default_alias_marks_unusable_on_failed_connect(oracle_connection, monkeypatch):
    """Failed connectivity should leave DEFAULT marked unusable."""

    del oracle_connection
    monkeypatch.setenv("AIO_DB_PASSWORD", "incorrect")

    db_module = _reload_db_module()
    _clear_registry(db_module)

    pool = await db_module.initialize_schema()

    assert pool is None
    default_alias = db_module.get_registered_database("DEFAULT")
    assert default_alias is not None
    assert default_alias.usable is False
