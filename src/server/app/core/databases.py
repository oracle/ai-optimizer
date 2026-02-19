"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models and dataclasses for database configuration.
"""

from typing import Optional
from pydantic import BaseModel


class DatabaseConfig(BaseModel):
    """Connection fields shared across database config and API schemas."""

    alias: str
    username: Optional[str] = None
    password: Optional[str] = None
    dsn: Optional[str] = None
    wallet_password: Optional[str] = None
    wallet_location: Optional[str] = None
    config_dir: Optional[str] = None
    tcp_connect_timeout: int = 10
