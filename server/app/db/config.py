"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database connection configuration for the FastAPI server.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import oracledb

from server.app.core.config import PROJECT_ROOT, settings

LOGGER = logging.getLogger(__name__)
_DEFAULT_TNS_ADMIN = PROJECT_ROOT / "server" / "tns_admin"


@dataclass(frozen=True)
class DatabaseSettings:
    """Configuration for connecting to the Oracle database."""

    username: str
    password: str
    dsn: str
    wallet_password: Optional[str] = None
    wallet_location: Optional[str] = None


def get_database_settings() -> Optional[DatabaseSettings]:
    """Return configured database settings or ``None`` if incomplete."""

    username = settings.db_username
    password = settings.db_password
    dsn = settings.db_dsn

    if username is None or password is None or dsn is None:
        return None

    return DatabaseSettings(
        username=username,
        password=password,
        dsn=dsn,
        wallet_password=settings.db_wallet_password,
        wallet_location=settings.db_wallet_location,
    )


async def create_pool(db_settings: DatabaseSettings) -> oracledb.AsyncConnectionPool:
    """Create and return an async oracledb connection pool."""

    tns_admin = os.environ.get("TNS_ADMIN") or str(_DEFAULT_TNS_ADMIN)

    connect_args = {
        "user": db_settings.username,
        "password": db_settings.password,
        "dsn": db_settings.dsn,
        "config_dir": tns_admin,
    }
    if db_settings.wallet_password:
        connect_args["wallet_password"] = db_settings.wallet_password
    if db_settings.wallet_location:
        connect_args["wallet_location"] = db_settings.wallet_location
    # If a wallet password is provided but no wallet location is set
    # default the wallet location to the config directory
    if connect_args.get("wallet_password") and not connect_args.get("wallet_location"):
        connect_args["wallet_location"] = connect_args["config_dir"]
    LOGGER.info("Connecting to Database: %s", db_settings.dsn)
    return oracledb.create_pool_async(**connect_args, min=1, max=5, increment=1, tcp_connect_timeout=10)
