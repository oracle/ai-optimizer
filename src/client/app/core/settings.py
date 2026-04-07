"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Client settings loaded from environment variables and .env file.
"""
# should be identical to server.app.core.settings

import os
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ClientSettings(BaseSettings):
    """Client settings populated from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_prefix="AIO_",
        env_file=PROJECT_ROOT / f".env.{os.getenv('AIO_ENV', 'dev')}",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: Optional[str] = None
    server_url: str = "http://localhost"
    server_port: int = 8000
    server_url_prefix: str = ""

    @field_validator("server_url_prefix")
    @classmethod
    def _normalize_url_prefix(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not v.startswith("/"):
            v = f"/{v}"
        return v

    client_address: str = "localhost"
    client_port: int = 8501
    client_url_prefix: str = ""
    client_ssl: bool = False
    client_ssl_cert_file: str = ""
    client_ssl_key_file: str = ""


settings = ClientSettings()
