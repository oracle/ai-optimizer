"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for database configuration endpoints.
"""

from typing import Optional

from pydantic import BaseModel, Field


class _DatabaseFields(BaseModel):
    """Connection fields shared by create and update payloads."""

    username: Optional[str] = None
    password: Optional[str] = None
    dsn: Optional[str] = None
    wallet_password: Optional[str] = None
    wallet_location: Optional[str] = None
    config_dir: Optional[str] = None
    tcp_connect_timeout: Optional[int] = None


class DatabaseCreate(_DatabaseFields):
    """Payload for creating a new database alias."""

    alias: str = Field(..., pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")


class DatabaseUpdate(_DatabaseFields):
    """Payload for updating an existing database alias."""


class DatabaseResponse(BaseModel):
    """Sanitised database configuration returned to clients."""

    alias: str
    username: Optional[str] = None
    dsn: Optional[str] = None
    wallet_location: Optional[str] = None
    has_credentials: bool
    usable: bool


class ActiveDatabase(BaseModel):
    """Active database alias."""

    alias: str


# --- Persistence models for aio_settings ---


class DatabaseConfigEntry(BaseModel):
    """Single database config as stored in the settings JSON."""

    alias: str
    user: Optional[str] = None
    password: Optional[str] = None
    dsn: Optional[str] = None
    wallet_password: Optional[str] = None
    wallet_location: Optional[str] = None
    config_dir: Optional[str] = None
    tcp_connect_timeout: int = 10


class ClientDatabaseSettings(BaseModel):
    """Tracks which database alias is_current."""

    alias: str = "DEFAULT"


class ClientSettings(BaseModel):
    """Client-level settings wrapper."""

    database: ClientDatabaseSettings = ClientDatabaseSettings()


class PersistedSettings(BaseModel):
    """Top-level structure persisted in the aio_settings table."""

    client_settings: ClientSettings = ClientSettings()
    database_configs: list[DatabaseConfigEntry] = []
