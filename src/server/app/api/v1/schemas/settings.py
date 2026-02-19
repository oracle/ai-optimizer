"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Response models for settings endpoint.
"""

from typing import Optional

from pydantic import BaseModel

from server.app.core.databases import DatabaseConfig
from server.app.core.oci_profiles import OciProfileConfig


class SettingsResponse(BaseModel):
    """Response for the settings endpoint."""

    env: str
    server_url_prefix: str
    server_port: int
    log_level: str
    database_configs: list[DatabaseConfig] = []
    oci_profile_configs: list[OciProfileConfig] = []
    client_disable_testbed: bool = False
    client_disable_api: bool = False
    client_disable_tools: bool = False
    client_disable_db_cfg: bool = False
    client_disable_model_cfg: bool = False
    client_disable_oci_cfg: bool = False
    client_disable_settings: bool = False
    client_disable_mcp_cfg: bool = False
    api_key: Optional[str] = None
