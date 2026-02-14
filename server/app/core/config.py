"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Application settings loaded from environment variables and .env file.
"""

import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    """Application settings populated from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_prefix="AIO_",
        env_file=PROJECT_ROOT / f".env.{os.getenv('AIO_ENV', 'dev')}",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    # Server
    env: str = "dev"
    url_prefix: str = ""
    port: int = 8000
    log_level: str = "INFO"

    # Database
    db_username: Optional[str] = None
    db_password: Optional[str] = None
    db_dsn: Optional[str] = None
    db_wallet_password: Optional[str] = None
    db_wallet_location: Optional[str] = None


settings = Settings()
