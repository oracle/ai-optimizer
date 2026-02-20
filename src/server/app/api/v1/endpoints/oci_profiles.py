"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for retrieving OCI profile configurations.
"""

from fastapi import APIRouter, HTTPException, Query

from server.app.oci.schema import OciProfileConfig, OciSensitive
from server.app.core.settings import settings

auth = APIRouter(prefix="/oci-profiles")

SENSITIVE_FIELDS = set(OciSensitive.model_fields.keys())


@auth.get("", response_model=list[OciProfileConfig], response_model_exclude_unset=True)
async def list_oci_profiles(include_sensitive: bool = Query(default=False)):
    """Return all OCI profile configurations."""
    exclude = None if include_sensitive else SENSITIVE_FIELDS
    return [cfg.model_dump(exclude=exclude) for cfg in settings.oci_profile_configs]


@auth.get("/{auth_profile}", response_model=OciProfileConfig, response_model_exclude_unset=True)
async def get_oci_profile(auth_profile: str, include_sensitive: bool = Query(default=False)):
    """Return a single OCI profile configuration by auth_profile (case-insensitive)."""
    for cfg in settings.oci_profile_configs:
        if cfg.auth_profile.lower() == auth_profile.lower():
            exclude = None if include_sensitive else SENSITIVE_FIELDS
            return cfg.model_dump(exclude=exclude)
    raise HTTPException(status_code=404, detail=f"OCI profile config not found: {auth_profile}")
