"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoint for retrieving server settings.
"""

from fastapi import APIRouter, Query

from server.app.api.v1.schemas.settings import SettingsResponse
from server.app.database.schemas import DatabaseSensitive
from server.app.models.schemas import ModelSensitive
from server.app.oci.schemas import OciSensitive
from server.app.core.settings import settings

auth = APIRouter(prefix="/settings")

SENSITIVE_FIELDS = {
    "api_key": True,
    "database_configs": {"__all__": set(DatabaseSensitive.model_fields.keys())},
    "model_configs": {"__all__": set(ModelSensitive.model_fields.keys())},
    "oci_configs": {"__all__": set(OciSensitive.model_fields.keys())},
}


@auth.get("", response_model=SettingsResponse, response_model_exclude_unset=True)
async def get_settings(include_sensitive: bool = Query(default=False)):
    """Return current application settings."""
    exclude = None if include_sensitive else SENSITIVE_FIELDS
    return settings.model_dump(exclude=exclude)
