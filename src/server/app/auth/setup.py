"""One-time operator setup for the CORE authentication authority."""

import argparse
import asyncio
import logging
import os
import sys

import oracledb

from server.app.auth.oidc import discover_oidc_jwks_uri
from server.app.auth.provisioning import (
    LOGIN_DATA_ROLE,
    configure_provisioning_authority,
    install_provisioning_package,
    missing_local_user_management_capabilities,
)
from server.app.auth.repository import bind_authority
from server.app.core.settings import (
    CoreDatabaseConfigurationError,
    require_core_database_config,
    settings,
    validate_auth_authority_configuration,
)
from server.app.database.config import _build_connect_args, close_pool
from server.app.database.registry import CoreDatabaseInitializationError, init_core_database
from server.app.database.schemas import DatabaseConfig
from server.app.database.sql import execute_sql

LOGGER = logging.getLogger(__name__)
_CORE_RETRY_INTERVAL_SECONDS = 10.0


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


async def _privileged_setup_connection(core_config: DatabaseConfig) -> oracledb.AsyncConnection | None:
    username = os.getenv("AIO_AUTH_SETUP_PRIV_USERNAME")
    password = os.environ.pop("AIO_AUTH_SETUP_PRIV_PASSWORD", None)
    if not username and not password:
        return None
    if not username or not password:
        raise ValueError("AIO_AUTH_SETUP_PRIV_USERNAME and AIO_AUTH_SETUP_PRIV_PASSWORD must be configured together")
    args = _build_connect_args(core_config)
    args["user"] = username
    args["password"] = password
    return await oracledb.connect_async(**args, tcp_connect_timeout=core_config.tcp_connect_timeout)


async def _install_local_user_management(
    conn: oracledb.AsyncConnection,
    privileged_conn: oracledb.AsyncConnection | None,
    core_config: DatabaseConfig,
    login_data_role: str,
) -> bool:
    await install_provisioning_package(conn)
    capability_conn = privileged_conn or conn
    missing = await missing_local_user_management_capabilities(capability_conn)
    if missing:
        LOGGER.warning("Local member administration is unavailable: %s", ", ".join(missing))
        return False
    try:
        await _ensure_connect_role(conn)
        await _ensure_login_data_role(conn, login_data_role)
        if privileged_conn is not None:
            await configure_provisioning_authority(
                privileged_conn,
                conn,
                core_config.username or "",
            )
    except (oracledb.DatabaseError, RuntimeError) as exc:
        LOGGER.warning("Local member administration is unavailable: %s", exc)
        return False
    return True


async def setup_authentication(wait_seconds: float = 0) -> None:
    """Bind the deployment identity and install available member administration."""
    validate_auth_authority_configuration(settings)
    core_config = require_core_database_config()
    await _init_core_database_with_retry(core_config, wait_seconds)
    pool = core_config.pool
    if pool is None:
        raise CoreDatabaseConfigurationError("CORE connection pool is unavailable after initialization")
    privileged_conn = await _privileged_setup_connection(core_config)
    try:
        async with pool.acquire() as conn:
            conn.autocommit = True
            if settings.auth_mode == "local_users":
                await _install_local_user_management(
                    conn,
                    privileged_conn,
                    core_config,
                    LOGIN_DATA_ROLE,
                )
        if settings.auth_mode == "oidc":
            await discover_oidc_jwks_uri()
        await bind_authority()
    finally:
        if privileged_conn is not None:
            await privileged_conn.close()
        await close_pool(pool)
        core_config.pool = None
        core_config.usable = False


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Initialize the authentication authority")
    parser.add_argument("--wait-seconds", type=float, default=0, help="Maximum time to wait for CORE initialization")
    args = parser.parse_args()
    if args.wait_seconds < 0:
        parser.error("--wait-seconds must be non-negative")
    try:
        asyncio.run(setup_authentication(args.wait_seconds))
    except Exception as exc:
        LOGGER.error("Authentication setup failed: %s", exc)
        return 1
    LOGGER.info("Authentication authority initialized for mode=%s", settings.auth_mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
