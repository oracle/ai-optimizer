"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database connection configuration for the FastAPI server.
"""

import os
from dataclasses import dataclass
from typing import Optional

import oracledb


@dataclass(frozen=True)
class DatabaseSettings:
    """Configuration for connecting to the Oracle database."""

    username: str
    password: str
    dsn: str
    wallet_password: Optional[str] = None


REQUIRED_VARS = ("DB_USERNAME", "DB_PASSWORD", "DB_DSN")


def get_database_settings() -> Optional[DatabaseSettings]:
    """Return configured database settings or ``None`` if incomplete."""

    missing = [env for env in REQUIRED_VARS if not os.environ.get(env)]
    if missing:
        return None

    return DatabaseSettings(
        username=os.environ["DB_USERNAME"],
        password=os.environ["DB_PASSWORD"],
        dsn=os.environ["DB_DSN"],
        wallet_password=os.environ.get("DB_WALLET_PASSWORD"),
    )


async def create_pool(settings: DatabaseSettings) -> oracledb.AsyncConnectionPool:
    """Create and return an async oracledb connection pool."""

    connect_args = {
        "user": settings.username,
        "password": settings.password,
        "dsn": settings.dsn,
    }
    if settings.wallet_password:
        connect_args["wallet_password"] = settings.wallet_password

    return oracledb.create_pool_async(**connect_args, min=1, max=5, increment=1)
