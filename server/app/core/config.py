"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Application settings loaded from environment variables and .env file.
"""

import os
import secrets
from pathlib import Path
from typing import Optional

from pydantic import model_validator
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

    # Auth
    api_key: Optional[str] = None

    # Database
    db_username: Optional[str] = None
    db_password: Optional[str] = None
    db_dsn: Optional[str] = None
    db_wallet_password: Optional[str] = None
    db_wallet_location: Optional[str] = None

    @model_validator(mode="after")
    def _generate_api_key_if_missing(self) -> "Settings":
        if self.api_key is None:
            object.__setattr__(self, "_api_key_generated", True)
            self.api_key = secrets.token_urlsafe(32)
        else:
            object.__setattr__(self, "_api_key_generated", False)
        return self

    @property
    def api_key_generated(self) -> bool:
        """True when api_key was auto-generated (AIO_API_KEY not set)."""
        return getattr(self, "_api_key_generated", False)


settings = Settings()
