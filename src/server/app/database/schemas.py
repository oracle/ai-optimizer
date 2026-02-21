"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models and dataclasses for database configuration.
"""

from typing import Annotated, Optional
from pydantic import BaseModel, Field

import oracledb


class DatabaseSensitive(BaseModel):
    """Sensitive database fields."""

    password: Optional[str] = None
    wallet_password: Optional[str] = None


class DatabaseConfig(DatabaseSensitive):
    """Database configurations."""

    model_config = {'arbitrary_types_allowed': True}

    alias: str
    username: Optional[str] = None
    dsn: Optional[str] = None
    wallet_location: Optional[str] = None
    config_dir: Optional[str] = None
    tcp_connect_timeout: int = 10
    usable: bool = False
    pool: Annotated[Optional[oracledb.AsyncConnectionPool], Field(exclude=True)] = None


class DatabaseUpdate(DatabaseSensitive):
    """Fields allowed in a database config update (all optional)."""

    username: Optional[str] = None
    dsn: Optional[str] = None
    wallet_location: Optional[str] = None
    config_dir: Optional[str] = None
    tcp_connect_timeout: Optional[int] = None
