"""Real Oracle checks for repeatable authentication schema installation."""

from contextlib import asynccontextmanager

import pytest

from server.app.auth import repository
from server.app.auth.provisioning import install_provisioning_package
from server.app.auth.setup import _ensure_login_data_role
from server.app.core.settings import Settings
from server.app.database.objects import REQUIRED_SCHEMA_INDEXES, REQUIRED_SCHEMA_TABLES, SCHEMA_DDL
from server.app.database.sql import execute_sql

pytestmark = [pytest.mark.db, pytest.mark.integration]


async def _row_counts(conn) -> dict[str, int]:
    counts = {}
    for table in ("AIO_SETTINGS", "AIO_TESTSETS", "AIO_TESTSET_QA", "AIO_EVALUATIONS", "AIO_EMBED_JOBS"):
        rows = await execute_sql(conn, f"SELECT COUNT(*) FROM {table}", max_rows=1)
        assert rows is not None
        counts[table] = int(rows[0][0])
    return counts


async def test_authentication_schema_ddl_is_repeatable(async_oracle_connection):
    conn = async_oracle_connection
    conn.autocommit = True
    for ddl in SCHEMA_DDL:
        await execute_sql(conn, ddl)
    before = await _row_counts(conn)
    for ddl in SCHEMA_DDL:
        await execute_sql(conn, ddl)
    after = await _row_counts(conn)
    assert after == before

    table_names = ", ".join(f"'{name}'" for name in sorted(REQUIRED_SCHEMA_TABLES))
    index_names = ", ".join(f"'{name}'" for name in sorted(REQUIRED_SCHEMA_INDEXES))
    table_rows = await execute_sql(conn, f"SELECT table_name FROM user_tables WHERE table_name IN ({table_names})")
    index_rows = await execute_sql(conn, f"SELECT index_name FROM user_indexes WHERE index_name IN ({index_names})")
    assert len(table_rows or []) == len(REQUIRED_SCHEMA_TABLES)
    assert len(index_rows or []) == len(REQUIRED_SCHEMA_INDEXES)


async def test_authentication_package_and_authority_setup_are_repeatable(async_oracle_connection, monkeypatch):
    conn = async_oracle_connection
    conn.autocommit = True
    for ddl in SCHEMA_DDL:
        await execute_sql(conn, ddl)
    await execute_sql(conn, "DELETE FROM aio_auth_sessions")
    await execute_sql(conn, "DELETE FROM aio_users")
    await execute_sql(conn, "DELETE FROM aio_auth_authority")
    await _ensure_login_data_role(conn, "AIO_LOGIN_ROLE")
    await execute_sql(conn, 'CREATE END USER "AIO_M1_ADMIN" IDENTIFIED BY "OrA_41_3xPl0d3r"')
    await execute_sql(conn, 'GRANT DATA ROLE "AIO_LOGIN_ROLE" TO "AIO_M1_ADMIN"')

    await install_provisioning_package(conn)
    await install_provisioning_package(conn)

    @asynccontextmanager
    async def _acquire():
        yield conn

    class Pool:
        acquire = staticmethod(_acquire)

    monkeypatch.setattr(repository, "require_core_pool", Pool)
    app_settings = Settings.model_validate(
        {
            "auth_mode": "single_user",
            "installation_id": "milestone-1-integration",
            "admin_database_username": "AIO_M1_ADMIN",
        }
    )

    first = await repository.bind_authority(app_settings)
    second = await repository.bind_authority(app_settings)

    assert first.installation_id == second.installation_id
    assert first.auth_mode == second.auth_mode
    assert first.database_identity == second.database_identity
    assert first.application_schema == second.application_schema
    assert first.initialized == second.initialized
    assert first.admin_database_username == "AIO_M1_ADMIN"
