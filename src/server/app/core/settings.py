"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Application settings loaded from environment variables and .env file.
"""

import os
import secrets
from typing import Optional

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from server.app.core.paths import PROJECT_ROOT
from server.app.database.schemas import DatabaseConfig
from server.app.oci.schemas import OciProfileConfig
from server.app.models.schemas import ModelConfig


class SettingsBase(BaseModel):
    """Fields shared between Settings and SettingsResponse."""

    env: str = "dev"
    server_url_prefix: str = ""
    server_port: int = 8000
    log_level: str = "INFO"
    database_configs: list[DatabaseConfig] = []
    oci_profile_configs: list[OciProfileConfig] = []
    model_configs: list[ModelConfig] = []
    client_disable_testbed: bool = False
    client_disable_api: bool = False
    client_disable_tools: bool = False
    client_disable_db_cfg: bool = False
    client_disable_model_cfg: bool = False
    client_disable_oci_cfg: bool = False
    client_disable_settings: bool = False
    client_disable_mcp_cfg: bool = False
    api_key: Optional[str] = None


class Settings(SettingsBase, BaseSettings):
    """Application settings populated from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_prefix="AIO_",
        env_file=PROJECT_ROOT / f".env.{os.getenv('AIO_ENV', 'dev')}",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database — flat fields loaded from AIO_DB_* env vars (excluded from serialization)
    db_username: Optional[str] = Field(default=None, exclude=True)
    db_password: Optional[str] = Field(default=None, exclude=True)
    db_dsn: Optional[str] = Field(default=None, exclude=True)
    db_wallet_password: Optional[str] = Field(default=None, exclude=True)
    db_wallet_location: Optional[str] = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _build_core_database_config(self) -> "Settings":
        """Create the CORE database config from AIO_DB_* env vars."""
        if any([self.db_username, self.db_password, self.db_dsn]):
            core = DatabaseConfig(
                alias="CORE",
                username=self.db_username,
                password=self.db_password,
                dsn=self.db_dsn,
                wallet_password=self.db_wallet_password,
                wallet_location=self.db_wallet_location,
            )
            self.database_configs = [core]
        return self

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
