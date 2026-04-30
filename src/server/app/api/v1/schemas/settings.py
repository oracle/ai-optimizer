"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Response models for settings endpoint.
"""

from typing import Optional

from pydantic import BaseModel

from server.app.core.schemas import ClientSettings
from server.app.core.settings import SettingsBase
from server.app.database.schemas import DatabaseConfig
from server.app.mcp.prompts.schemas import PromptConfig
from server.app.models.schemas import ModelConfig
from server.app.oci.schemas import OciProfileConfig


class SettingsResponse(SettingsBase):
    """Response for the settings endpoint."""


class SettingsImport(BaseModel):
    """Request body for POST /settings/import — all fields optional."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "log_level": "INFO",
                "database_configs": [
                    {
                        "alias": "CORE",
                        "username": "ADMIN",
                        "password": "MyStrongPassword#1",
                        "dsn": "adb.example.oraclecloud.com:1521/mydb_high",
                    }
                ],
                "model_configs": [
                    {
                        "type": "ll",
                        "provider": "openai",
                        "id": "gpt-4o-mini",
                        "api_key": "sk-...",
                        "enabled": True,
                    }
                ],
                "oci_configs": [
                    {
                        "auth_profile": "DEFAULT",
                        "authentication": "api_key",
                        "region": "us-ashburn-1",
                    }
                ],
            }
        }
    }

    log_level: Optional[str] = None
    database_configs: Optional[list[DatabaseConfig]] = None
    model_configs: Optional[list[ModelConfig]] = None
    oci_configs: Optional[list[OciProfileConfig]] = None
    prompt_configs: Optional[list[PromptConfig]] = None
    client_settings: Optional[ClientSettings] = None


class ImportSectionResult(BaseModel):
    """Per-section summary of an import operation."""

    created: int = 0
    updated: int = 0
    skipped: int = 0


class SettingsImportResult(BaseModel):
    """Top-level response for POST /settings/import."""

    database_configs: Optional[ImportSectionResult] = None
    model_configs: Optional[ImportSectionResult] = None
    oci_configs: Optional[ImportSectionResult] = None
    prompt_configs: Optional[ImportSectionResult] = None
    client_settings: Optional[bool] = None
    scalars: Optional[dict[str, str]] = None
