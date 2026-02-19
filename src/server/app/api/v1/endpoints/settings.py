"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoint for retrieving server settings.
"""

from fastapi import APIRouter, Query

from server.app.api.v1.schemas.settings import SettingsResponse
from server.app.core.config import settings

auth = APIRouter(prefix="/settings")

_SECRET_FIELDS = {"api_key", "db_password", "db_wallet_password"}


@auth.get("", response_model=SettingsResponse)
async def get_settings(
    include_secrets: bool = Query(
        default=False,
        description="Include secret fields (api_key, db_password, db_wallet_password) in the response.",
    ),
):
    """Return current server settings."""
    data = settings.model_dump()
    if not include_secrets:
        for field in _SECRET_FIELDS:
            data.pop(field, None)
    return SettingsResponse(**data)
