"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for retrieving OCI profile configurations.
"""

from fastapi import APIRouter, HTTPException, Query

from server.app.oci.schemas import OciProfileConfig, OciProfileUpdate, OciSensitive
from server.app.database.settings import persist_settings
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


@auth.post("", response_model=OciProfileConfig, status_code=201, response_model_exclude_unset=True)
async def create_oci_profile(body: OciProfileConfig):
    """Add a new OCI profile configuration."""
    for cfg in settings.oci_profile_configs:
        if cfg.auth_profile.lower() == body.auth_profile.lower():
            raise HTTPException(status_code=409, detail=f"OCI profile config already exists: {body.auth_profile}")
    settings.oci_profile_configs.append(body)
    await persist_settings()
    return body.model_dump(exclude=SENSITIVE_FIELDS)


@auth.put("/{auth_profile}", response_model=OciProfileConfig, response_model_exclude_unset=True)
async def update_oci_profile(auth_profile: str, body: OciProfileUpdate):
    """Update an existing OCI profile configuration by auth_profile (case-insensitive)."""
    for cfg in settings.oci_profile_configs:
        if cfg.auth_profile.lower() == auth_profile.lower():
            updates = body.model_dump(exclude_unset=True)
            for field, value in updates.items():
                setattr(cfg, field, value)
            await persist_settings()
            return cfg.model_dump(exclude=SENSITIVE_FIELDS)
    raise HTTPException(status_code=404, detail=f"OCI profile config not found: {auth_profile}")


@auth.delete("/{auth_profile}", status_code=204)
async def delete_oci_profile(auth_profile: str):
    """Remove an OCI profile configuration by auth_profile (case-insensitive)."""
    for i, cfg in enumerate(settings.oci_profile_configs):
        if cfg.auth_profile.lower() == auth_profile.lower():
            settings.oci_profile_configs.pop(i)
            await persist_settings()
            return None
    raise HTTPException(status_code=404, detail=f"OCI profile config not found: {auth_profile}")
