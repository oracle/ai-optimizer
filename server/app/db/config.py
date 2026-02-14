"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database connection configuration for the FastAPI server.
"""

import logging
import os
from dataclasses import dataclass, replace
from typing import Optional

import oracledb

from server.app.core.config import PROJECT_ROOT, settings

LOGGER = logging.getLogger(__name__)
_DEFAULT_TNS_ADMIN = PROJECT_ROOT / "server" / "tns_admin"


@dataclass(frozen=True)
class DatabaseSettings:
    """Configuration for connecting to an Oracle database alias."""

    alias: str
    username: Optional[str] = None
    password: Optional[str] = None
    dsn: Optional[str] = None
    wallet_password: Optional[str] = None
    wallet_location: Optional[str] = None
    usable: bool = False

    def has_credentials(self) -> bool:
        """Return True when username, password, and dsn are populated."""

        return bool(self.username and self.password and self.dsn)

    def mark_usable(self, usable: bool) -> "DatabaseSettings":
        """Return a copy with the usable flag updated."""

        return replace(self, usable=usable)


def get_database_settings() -> DatabaseSettings:
    """Return the DEFAULT database alias populated from environment variables."""

    return DatabaseSettings(
        alias="DEFAULT",
        username=settings.db_username,
        password=settings.db_password,
        dsn=settings.db_dsn,
        wallet_password=settings.db_wallet_password,
        wallet_location=settings.db_wallet_location,
    )


async def create_pool(db_settings: DatabaseSettings) -> oracledb.AsyncConnectionPool:
    """Create and return an async oracledb connection pool."""

    if not db_settings.has_credentials():
        raise ValueError(f"Database alias {db_settings.alias} missing credentials")

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
    LOGGER.info("Connecting to Database alias=%s dsn=%s", db_settings.alias, db_settings.dsn)
    return oracledb.create_pool_async(**connect_args, min=1, max=5, increment=1, tcp_connect_timeout=10)
