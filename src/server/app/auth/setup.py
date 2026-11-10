"""One-time operator setup for the CORE authentication authority."""

import asyncio
import getpass
import logging
import os
import re
import sys

import oracledb

from server.app.auth.provisioning import install_provisioning_package
from server.app.auth.repository import bind_authority
from server.app.core.settings import (
    CoreDatabaseConfigurationError,
    require_core_database_config,
    settings,
    validate_auth_configuration,
)
from server.app.database.config import _build_connect_args, close_pool
from server.app.database.registry import CoreDatabaseInitializationError, init_core_database
from server.app.database.schemas import DatabaseConfig
from server.app.database.sql import execute_sql

LOGGER = logging.getLogger(__name__)
_CORE_RETRY_INTERVAL_SECONDS = 10.0


def _core_wait_seconds() -> float:
    raw_value = os.getenv("AIO_AUTH_SETUP_WAIT_SECONDS", "0")
    try:
        wait_seconds = float(raw_value)
    except ValueError:
        raise ValueError("AIO_AUTH_SETUP_WAIT_SECONDS must be a number") from None
    if wait_seconds < 0:
        raise ValueError("AIO_AUTH_SETUP_WAIT_SECONDS must be non-negative")
    return wait_seconds


async def _init_core_database_with_retry(
    core_config: DatabaseConfig,
    wait_seconds: float,
    retry_interval: float = _CORE_RETRY_INTERVAL_SECONDS,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while True:
        try:
            await init_core_database(core_config)
            return
        except CoreDatabaseInitializationError:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise
            LOGGER.info("CORE database is not initialized; retrying authentication setup")
            await asyncio.sleep(min(retry_interval, remaining))


async def _validate_local_auth_capabilities(conn: oracledb.AsyncConnection) -> None:
    """Report missing Oracle local end-user capabilities before installation."""
    missing = []
    for view, capability in (
        ("DBA_END_USERS", "local end-user accounts"),
        ("DBA_DATA_ROLES", "data roles"),
    ):
        try:
            await execute_sql(conn, f"SELECT 1 FROM {view} WHERE 1 = 0", max_rows=1)
        except oracledb.Error:
            missing.append(capability)
    try:
        rows = await execute_sql(
            conn,
            "SELECT privilege FROM USER_SYS_PRIVS WHERE privilege IN ('CREATE END USER', 'CREATE DATA ROLE')",
            max_rows=10,
        )
    except oracledb.Error:
        rows = []
    privileges = {row[0] for row in rows or []}
    for privilege, capability in (
        ("CREATE END USER", "CREATE END USER privilege"),
        ("CREATE DATA ROLE", "CREATE DATA ROLE privilege"),
    ):
        if privilege not in privileges:
            missing.append(capability)
    if missing:
        raise RuntimeError(f"CORE database is missing required authentication capabilities: {', '.join(missing)}")


async def _ensure_connect_role(conn: oracledb.AsyncConnection) -> None:
    rows = await execute_sql(
        conn,
        "SELECT admin_option FROM user_role_privs WHERE granted_role = 'AIO_DDS_ROLE'",
        max_rows=1,
    )
    if rows:
        if rows[0][0] != "YES":
            raise RuntimeError("CORE requires AIO_DDS_ROLE with admin option")
        return
    await execute_sql(
        conn,
        "CREATE ROLE AIO_DDS_ROLE",
        ignored_error_codes=frozenset({955, 1921}),
    )
    await execute_sql(conn, "GRANT CREATE SESSION TO AIO_DDS_ROLE")


async def _ensure_login_data_role(conn: oracledb.AsyncConnection, role: str) -> None:
    rows = await execute_sql(
        conn,
        "SELECT data_role FROM dba_data_roles WHERE data_role = :role",
        {"role": role},
        max_rows=1,
    )
    if not rows:
        await execute_sql(conn, f'CREATE DATA ROLE "{role}"')
    await execute_sql(conn, f'GRANT AIO_DDS_ROLE TO "{role}"')


async def setup_authentication() -> None:
    """Install local-user administration and bind the configured deployment identity."""
    validate_auth_configuration(settings)
    admin_username = settings.admin_database_username
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]{0,127}", admin_username or "") is None:
        raise ValueError("AIO_ADMIN_DATABASE_USERNAME must be a simple Oracle identifier")
    if admin_username is None:
        raise ValueError("AIO_ADMIN_DATABASE_USERNAME is required")
    core_config = require_core_database_config()
    await _init_core_database_with_retry(core_config, _core_wait_seconds())
    pool = core_config.pool
    if pool is None:
        raise CoreDatabaseConfigurationError("CORE connection pool is unavailable after initialization")
    login_data_role = settings.auth_login_data_role.upper()
    if re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,127}", login_data_role) is None:
        raise ValueError("AIO_AUTH_LOGIN_DATA_ROLE must be a simple Oracle identifier")
    try:
        async with pool.acquire() as conn:
            conn.autocommit = True
            await _validate_local_auth_capabilities(conn)
            await _ensure_connect_role(conn)
            await _ensure_login_data_role(conn, login_data_role)
            await install_provisioning_package(conn)
            admin_catalog = "dba_users" if settings.auth_mode == "oidc" else "dba_end_users"
            admin_rows = await execute_sql(
                conn,
                f"SELECT account_status FROM {admin_catalog} WHERE username = :username",
                {"username": admin_username.upper()},
                max_rows=1,
            )
            if not admin_rows or admin_rows[0][0] != "OPEN":
                raise RuntimeError("The mapped Admin Oracle local end user is missing or unavailable")
            if settings.auth_mode != "oidc":
                await execute_sql(conn, f'GRANT DATA ROLE "{login_data_role}" TO "{admin_username.upper()}"')

        if settings.auth_mode != "oidc":
            password = os.environ.pop("AIO_AUTH_ADMIN_PASSWORD", None)
            if not password:
                password = getpass.getpass(f"Password for mapped Admin end user {admin_username}: ")
            args = _build_connect_args(core_config)
            args["user"] = admin_username.upper()
            args["password"] = password
            try:
                verification = await oracledb.connect_async(
                    **args,
                    tcp_connect_timeout=core_config.tcp_connect_timeout,
                )
            except oracledb.Error:
                raise RuntimeError("The mapped Admin database end user could not be verified") from None
            await verification.close()
        await bind_authority()
    finally:
        await close_pool(pool)
        core_config.pool = None
        core_config.usable = False


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(setup_authentication())
    except Exception as exc:
        LOGGER.error("Authentication setup failed: %s", exc)
        return 1
    LOGGER.info("Authentication authority initialized for mode=%s", settings.auth_mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
