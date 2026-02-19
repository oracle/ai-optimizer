"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration test validating Oracle schema creation on startup.
"""
# pylint: disable=redefined-outer-name
# spell-checker: disable

import importlib
import sys

import anyio
import pytest

MODULE_PATH = "server.app.main"


@pytest.mark.db
@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("root_path", ["", "demo"])
def test_schema_created(configure_db_env, oracle_connection, root_path, monkeypatch):
    """Ensure startup creates required tables in Oracle."""
    del configure_db_env

    if root_path:
        monkeypatch.setenv("AIO_SERVER_URL_PREFIX", root_path)
    else:
        monkeypatch.delenv("AIO_SERVER_URL_PREFIX", raising=False)

    for mod in (
        MODULE_PATH,
        "server.app.core.config",
        "server.app.database",
        "server.app.database.config",
        "server.app.database.settings",
    ):
        sys.modules.pop(mod, None)
    app_main = importlib.import_module(MODULE_PATH)

    async def _run_lifespan():
        async with app_main.lifespan(app_main.app):
            pass

    anyio.run(_run_lifespan)

    cursor = oracle_connection.cursor()
    cursor.execute("SELECT table_name FROM user_tables WHERE table_name LIKE 'AIO_%'")
    tables = {row[0] for row in cursor.fetchall()}
    cursor.close()

    assert {"AIO_TESTSETS", "AIO_TESTSET_QA", "AIO_EVALUATIONS", "AIO_SETTINGS"}.issubset(tables)


@pytest.mark.db
@pytest.mark.slow
@pytest.mark.integration
def test_settings_persisted_on_startup(configure_db_env, oracle_connection, monkeypatch):
    """Startup should persist DEFAULT config to aio_settings."""
    del configure_db_env

    monkeypatch.delenv("AIO_SERVER_URL_PREFIX", raising=False)

    for mod in (
        MODULE_PATH,
        "server.app.core.config",
        "server.app.database",
        "server.app.database.config",
        "server.app.database.settings",
    ):
        sys.modules.pop(mod, None)
    app_main = importlib.import_module(MODULE_PATH)

    async def _run_lifespan():
        async with app_main.lifespan(app_main.app):
            pass

    anyio.run(_run_lifespan)

    cursor = oracle_connection.cursor()
    cursor.execute("SELECT settings FROM aio_settings WHERE client = 'DEFAULT'")
    row = cursor.fetchone()
    cursor.close()

    assert row is not None, "aio_settings row should exist after startup"
    assert row[0] is not None, "settings JSON should not be null"
