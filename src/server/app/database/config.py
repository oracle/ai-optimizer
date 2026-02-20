"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database configuration lookup utilities.
"""

import os
import logging
from typing import Optional

import oracledb

from server.app.core.paths import PROJECT_ROOT
from server.app.database.model import DatabaseConfig

LOGGER = logging.getLogger(__name__)
_CORE_TNS_ADMIN = PROJECT_ROOT / "server" / "tns_admin"


def get_database_settings(db_configs: list[DatabaseConfig], alias: str) -> DatabaseConfig:
    """Return the database config for the given alias from application settings."""
    for cfg in db_configs:
        if cfg.alias == alias:
            return cfg
    return DatabaseConfig(alias=alias)


def has_required_credentials(db_config: DatabaseConfig) -> bool:
    """Return True if the config has username, password, and dsn."""
    return all([db_config.username, db_config.password, db_config.dsn])


async def create_pool(db_config: DatabaseConfig) -> oracledb.AsyncConnectionPool:
    """Create and return an async oracledb connection pool."""

    if not has_required_credentials(db_config):
        db_config.usable = False
        raise ValueError(f"Database alias {db_config.alias} missing credentials")

    config_dir = db_config.config_dir or os.environ.get("TNS_ADMIN") or str(_CORE_TNS_ADMIN)

    connect_args = {
        "user": db_config.username,
        "password": db_config.password,
        "dsn": db_config.dsn,
        "config_dir": config_dir,
    }
    if db_config.wallet_password:
        connect_args["wallet_password"] = db_config.wallet_password
    if db_config.wallet_location:
        connect_args["wallet_location"] = db_config.wallet_location

    # If a wallet password is provided but no wallet location is set
    # default the wallet location to the config directory
    if connect_args.get("wallet_password") and not connect_args.get("wallet_location"):
        connect_args["wallet_location"] = connect_args["config_dir"]
    LOGGER.info("Connecting to Database alias=%s dsn=%s", db_config.alias, db_config.dsn)
    return oracledb.create_pool_async(
        **connect_args, min=1, max=5, increment=1, tcp_connect_timeout=db_config.tcp_connect_timeout
    )


async def close_pool(pool: Optional[oracledb.AsyncConnectionPool]) -> None:
    """Silently close a connection pool if it is not None."""
    if pool is not None:
        try:
            await pool.close()
        except oracledb.Error:
            pass
