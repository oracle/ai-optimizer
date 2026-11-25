"""Real Oracle checks for repeatable authentication schema installation."""

from contextlib import asynccontextmanager, suppress

import oracledb
import pytest
from pydantic import SecretStr

from server.app.auth import local, repository, users
from server.app.auth.models import RequestCredential
from server.app.auth.provisioning import (
    configure_provisioning_authority,
    install_provisioning_package,
    local_user_management_issues,
    package_role_name,
    provisioning_package_available,
)
from server.app.auth.setup import _ensure_login_data_role
from server.app.core.settings import Settings, settings
from server.app.database.objects import RENAME_DDL, REQUIRED_SCHEMA_INDEXES, REQUIRED_SCHEMA_TABLES, SCHEMA_DDL
from server.app.database.schemas import DatabaseConfig
from server.app.database.sql import execute_sql
from tests.oracle import TEST_DB_CONFIG

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


async def test_legacy_authentication_authority_schema_is_upgraded(async_oracle_connection):
    conn = async_oracle_connection
    conn.autocommit = True
    try:
        await execute_sql(conn, "DROP TABLE aio_auth_authority PURGE")
        await execute_sql(
            conn,
            "CREATE TABLE aio_auth_authority ("
            "installation_id VARCHAR2(255) NOT NULL, auth_mode VARCHAR2(32) NOT NULL, "
            "schema_version NUMBER(9) NOT NULL, database_identity VARCHAR2(255) NOT NULL, "
            "application_schema VARCHAR2(128) NOT NULL, admin_database_username VARCHAR2(128) NOT NULL, "
            "oidc_issuer VARCHAR2(2048), oidc_admin_subject VARCHAR2(1024), "
            "initialized TIMESTAMP(9) WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL, "
            "last_validated TIMESTAMP(9) WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL, "
            "CONSTRAINT aio_auth_authority_pk PRIMARY KEY (installation_id), "
            "CONSTRAINT aio_auth_authority_mode_ck CHECK (auth_mode IN ('SINGLE_USER', 'LOCAL_USERS', 'OIDC')), "
            "CONSTRAINT aio_auth_authority_oidc_ck CHECK ((auth_mode = 'OIDC' AND oidc_issuer IS NOT NULL "
            "AND oidc_admin_subject IS NOT NULL) OR (auth_mode <> 'OIDC' AND oidc_issuer IS NULL "
            "AND oidc_admin_subject IS NULL)))",
        )
        await execute_sql(
            conn,
            "INSERT INTO aio_auth_authority (installation_id, auth_mode, schema_version, database_identity, "
            "application_schema, admin_database_username) VALUES "
            "('legacy-installation', 'SINGLE_USER', 1, 'LEGACY_DB', 'LEGACY_SCHEMA', 'LEGACY_ADMIN')",
        )

        for ddl in (*RENAME_DDL, *SCHEMA_DDL):
            await execute_sql(conn, ddl)

        columns = await execute_sql(
            conn,
            "SELECT column_name FROM user_tab_columns WHERE table_name = 'AIO_AUTH_AUTHORITY'",
        )
        column_names = {row[0] for row in columns or []}
        assert "AUTHORITY_ID" in column_names
        assert "INSTALLATION_ID" not in column_names
        assert "ADMIN_DATABASE_USERNAME" not in column_names
        rows = await execute_sql(
            conn,
            "SELECT authority_id, auth_mode, database_identity, application_schema FROM aio_auth_authority",
            max_rows=1,
        )
        assert rows == [(1, "LOCAL_USERS", "LEGACY_DB", "LEGACY_SCHEMA")]
    finally:
        await execute_sql(conn, "DELETE FROM aio_auth_authority")


async def test_authentication_package_and_authority_setup_are_repeatable(async_oracle_connection, monkeypatch):
    conn = async_oracle_connection
    conn.autocommit = True
    for ddl in SCHEMA_DDL:
        await execute_sql(conn, ddl)
    await execute_sql(conn, "DELETE FROM aio_auth_audit")
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
            "db_username": "AIO_M1_ADMIN",
        }
    )

    first = await repository.bind_authority(app_settings)
    second = await repository.bind_authority(app_settings)

    assert first.auth_mode == second.auth_mode
    assert first.database_identity == second.database_identity
    assert first.application_schema == second.application_schema
    assert first.initialized == second.initialized


async def test_database_members_sessions_password_change_and_revocation(async_oracle_connection, monkeypatch):
    conn = async_oracle_connection
    conn.autocommit = True
    admin_username = "AIO_M2_ADMIN"
    member_username = "AIO_M2_MEMBER"
    admin_password = "M2_Admin_41_Strong"
    initial_password = "M2_Initial_41_Strong"
    member_password = "M2_Member_42_Strong"

    async def _drop_end_user(username: str) -> None:
        with suppress(oracledb.DatabaseError):
            await execute_sql(conn, f'DROP END USER "{username}"', ignored_error_codes=frozenset())

    for ddl in SCHEMA_DDL:
        await execute_sql(conn, ddl)
    await execute_sql(conn, "DELETE FROM aio_auth_audit")
    await execute_sql(conn, "DELETE FROM aio_auth_sessions")
    await execute_sql(conn, "DELETE FROM aio_users")
    await execute_sql(conn, "DELETE FROM aio_auth_authority")
    await _drop_end_user(member_username)
    await _drop_end_user(admin_username)
    await _ensure_login_data_role(conn, "AIO_LOGIN_ROLE")
    await install_provisioning_package(conn)
    assert await local_user_management_issues(conn) == []
    await execute_sql(conn, f'CREATE END USER "{admin_username}" IDENTIFIED BY "{admin_password}"')
    await execute_sql(conn, f'GRANT DATA ROLE "AIO_LOGIN_ROLE" TO "{admin_username}"')

    @asynccontextmanager
    async def _acquire():
        yield conn

    class Pool:
        acquire = staticmethod(_acquire)

    core = DatabaseConfig(
        alias="CORE",
        username=TEST_DB_CONFIG["db_username"],
        password=SecretStr(TEST_DB_CONFIG["db_password"]),
        dsn=TEST_DB_CONFIG["db_dsn"],
    )
    core.pool = Pool()  # type: ignore[assignment]
    core.usable = True
    monkeypatch.setattr(repository, "require_core_pool", Pool)
    monkeypatch.setattr(local, "require_core_pool", Pool)
    monkeypatch.setattr(settings, "database_configs", [core])
    app_settings = Settings.model_validate(
        {
            "db_username": admin_username,
        }
    )
    try:
        await repository.bind_authority(app_settings)
        admin_session, admin_principal = await local.login_database_user(admin_username, admin_password)
        assert admin_principal.user_id == repository.ADMIN_USER_ID
        await local.logout_database_session(admin_session.token)

        member = await users.create_member(member_username, initial_password, "Member", None)
        initial_session, _ = await local.login_database_user(member_username, initial_password)
        await local.change_database_password(member_username, initial_password, member_password)
        with pytest.raises(local.AuthenticationError):
            await local.DatabaseSessionAuthenticator().authenticate(
                RequestCredential(kind="bearer", value=initial_session.token)
            )

        issued, principal = await local.login_database_user(member_username, member_password, "127.0.0.1")
        assert principal.user_id == member.user_id
        digest_rows = await execute_sql(
            conn,
            "SELECT token_digest FROM aio_auth_sessions WHERE user_id = :user_id AND revoked IS NULL",
            {"user_id": member.user_id.bytes},
            max_rows=1,
        )
        assert digest_rows and bytes(digest_rows[0][0]) == local.session_token_digest(issued.token)

        second_instance = local.DatabaseSessionAuthenticator()
        authenticated = await second_instance.authenticate(RequestCredential(kind="bearer", value=issued.token))
        assert authenticated.user_id == member.user_id

        await users.update_member(member.user_id, True, member.display_name, member.email)
        with pytest.raises(local.AuthenticationError):
            await second_instance.authenticate(RequestCredential(kind="bearer", value=issued.token))

        await users.update_member(member.user_id, False, member.display_name, member.email)
        await users.reset_member_password(member.user_id, initial_password)
        reset_session, _ = await local.login_database_user(member_username, initial_password)
        await local.change_database_password(member_username, initial_password, member_password)
        with pytest.raises(local.AuthenticationError):
            await local.DatabaseSessionAuthenticator().authenticate(
                RequestCredential(kind="bearer", value=reset_session.token)
            )
        replacement, _ = await local.login_database_user(member_username, member_password)
        await local.logout_database_session(replacement.token)
        with pytest.raises(local.AuthenticationError):
            await second_instance.authenticate(RequestCredential(kind="bearer", value=replacement.token))
    finally:
        await _drop_end_user(member_username)
        await _drop_end_user(admin_username)
        await execute_sql(conn, "DELETE FROM aio_auth_audit")
        await execute_sql(conn, "DELETE FROM aio_auth_sessions")
        await execute_sql(conn, "DELETE FROM aio_users")
        await execute_sql(conn, "DELETE FROM aio_auth_authority")


async def test_provisioning_package_holds_end_user_privileges(oracle_db_container, monkeypatch):
    del oracle_db_container
    owner = "AIO_M2_PACKAGE_OWNER"
    member = "AIO_M2_PACKAGE_USER"
    password = "M2_Package_43_Strong"
    system = await oracledb.connect_async(
        user="SYSTEM",
        password=TEST_DB_CONFIG["db_password"],
        dsn=TEST_DB_CONFIG["db_dsn"],
    )
    system.autocommit = True
    owner_conn = None
    try:
        for statement in (f'DROP END USER "{member}"', f'DROP USER "{owner}" CASCADE'):
            with suppress(oracledb.DatabaseError):
                await execute_sql(system, statement, ignored_error_codes=frozenset())
        await execute_sql(system, f'CREATE USER "{owner}" IDENTIFIED BY "{password}"')
        await execute_sql(system, f'GRANT CREATE SESSION, CREATE PROCEDURE TO "{owner}"')
        owner_conn = await oracledb.connect_async(
            user=owner,
            password=password,
            dsn=TEST_DB_CONFIG["db_dsn"],
        )
        owner_conn.autocommit = True
        await _ensure_login_data_role(system, "AIO_LOGIN_ROLE")
        await install_provisioning_package(owner_conn)
        assert await provisioning_package_available(owner_conn)
        await configure_provisioning_authority(system, owner_conn, owner)
        await configure_provisioning_authority(system, owner_conn, owner)
        assert await provisioning_package_available(owner_conn)
        delegated_roles = await execute_sql(
            owner_conn,
            "SELECT granted_role, delegate_option FROM user_role_privs",
        )
        assert (package_role_name(owner), "YES") in (delegated_roles or [])
        assert await local_user_management_issues(owner_conn) == []

        with pytest.raises(oracledb.DatabaseError):
            await execute_sql(
                owner_conn,
                f'CREATE END USER "{member}" IDENTIFIED BY "{password}"',
                ignored_error_codes=frozenset(),
            )
        async with owner_conn.cursor() as cursor:
            await cursor.callproc("AIO_AUTH_ADMIN.CREATE_USER", [member, password])
            account_status = cursor.var(str, size=128)
            await cursor.callproc("AIO_AUTH_ADMIN.ACCOUNT_STATUS", [member, account_status])
            assert account_status.getvalue() == "OPEN"
    finally:
        if owner_conn is not None:
            await owner_conn.close()
        for statement in (f'DROP END USER "{member}"', f'DROP USER "{owner}" CASCADE'):
            with suppress(oracledb.DatabaseError):
                await execute_sql(system, statement, ignored_error_codes=frozenset())
        await system.close()
