"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoint for retrieving server settings.
"""

from fastapi import APIRouter, Query

from server.app.api.v1.schemas.settings import SettingsResponse
from server.app.database.model import DatabaseSensitive
from server.app.core.oci_profiles import OciSensitive
from server.app.core.settings import settings

auth = APIRouter(prefix="/settings")

SENSITIVE_FIELDS = {
    "api_key": True,
    "database_configs": {"__all__": set(DatabaseSensitive.model_fields.keys())},
    "oci_profile_configs": {"__all__": set(OciSensitive.model_fields.keys())},
}


@auth.get("", response_model=SettingsResponse, response_model_exclude_unset=True)
async def get_settings(include_sensitive: bool = Query(default=False)):
    """Return current application settings."""
    exclude = None if include_sensitive else SENSITIVE_FIELDS
    return settings.model_dump(exclude=exclude)
