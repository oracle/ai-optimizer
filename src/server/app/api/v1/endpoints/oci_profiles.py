"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

CRUD endpoints for OCI profile configuration management.
"""
# spell-checker:ignore genai
# pylint: disable=duplicate-code  # _to_response flattens same dataclass as oci_config_to_entry

import dataclasses
import logging

from fastapi import APIRouter, HTTPException

from server.app.api.v1.schemas.oci_profiles import (
    OCIProfileCreate,
    OCIProfileResponse,
    OCIProfileUpdate,
)
from server.app.database import persist_settings
from server.app.oci import (
    get_all_oci_profiles,
    get_oci_profile,
    register_oci_profile,
    remove_oci_profile,
)
from server.app.oci.config import OCIAuthConfig, OCIProfileSettings

LOGGER = logging.getLogger(__name__)

# Auth fields live on OCIAuthConfig; the rest live on OCIProfileSettings.
_AUTH_FIELDS = frozenset(f.name for f in dataclasses.fields(OCIAuthConfig))

# Fields with non-None defaults that must not be set to None via partial update.
_NON_NONE_DEFAULTS = {"authentication", "log_requests", "additional_user_agent"}

auth = APIRouter(prefix="/oci")


def _to_response(state) -> OCIProfileResponse:
    """Map internal OCIProfileState to the public response model."""
    s = state.settings
    a = s.auth
    return OCIProfileResponse(
        auth_profile=s.auth_profile,
        user=a.user,
        authentication=a.authentication,
        security_token_file=a.security_token_file,
        fingerprint=a.fingerprint,
        tenancy=a.tenancy,
        region=s.region,
        genai_compartment_id=s.genai_compartment_id,
        genai_region=s.genai_region,
        log_requests=s.log_requests,
        additional_user_agent=s.additional_user_agent,
        usable=state.usable,
    )


# --- CRUD endpoints ---


@auth.get("", response_model=list[OCIProfileResponse])
async def list_oci_profiles():
    """List all registered OCI profiles."""
    return [_to_response(p) for p in get_all_oci_profiles()]


@auth.get("/{profile}", response_model=OCIProfileResponse)
async def get_profile(profile: str):
    """Get configuration for a single OCI profile."""
    state = get_oci_profile(profile)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Profile '{profile}' not found")
    return _to_response(state)


@auth.post("", response_model=OCIProfileResponse, status_code=201)
async def create_oci_profile(body: OCIProfileCreate):
    """Create a new OCI profile configuration."""
    if get_oci_profile(body.auth_profile) is not None:
        raise HTTPException(status_code=409, detail=f"Profile '{body.auth_profile}' already exists")

    new_settings = OCIProfileSettings(
        auth_profile=body.auth_profile,
        auth=OCIAuthConfig(
            user=body.user,
            authentication=body.authentication or "api_key",
            security_token_file=body.security_token_file,
            fingerprint=body.fingerprint,
            tenancy=body.tenancy,
            key=body.key,
            pass_phrase=body.pass_phrase,
        ),
        region=body.region,
        genai_compartment_id=body.genai_compartment_id,
        genai_region=body.genai_region,
        log_requests=body.log_requests or False,
        additional_user_agent=body.additional_user_agent or "",
    )

    state = register_oci_profile(new_settings)
    await persist_settings()
    return _to_response(state)


@auth.put("/{profile}", response_model=OCIProfileResponse)
async def update_oci_profile(profile: str, body: OCIProfileUpdate):
    """Update an existing OCI profile configuration."""
    state = get_oci_profile(profile)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Profile '{profile}' not found")

    updates = body.model_dump(exclude_unset=True)

    # Drop null values for fields that have non-None defaults so
    # dataclasses.replace() keeps the current value instead.
    updates = {k: v for k, v in updates.items() if v is not None or k not in _NON_NONE_DEFAULTS}

    # Split updates between auth sub-dataclass and top-level settings.
    auth_updates = {k: v for k, v in updates.items() if k in _AUTH_FIELDS}
    settings_updates = {k: v for k, v in updates.items() if k not in _AUTH_FIELDS}

    current = state.settings
    if auth_updates:
        settings_updates["auth"] = dataclasses.replace(current.auth, **auth_updates)

    new_settings = dataclasses.replace(current, **settings_updates)
    state.settings = new_settings

    await persist_settings()
    return _to_response(state)


@auth.delete("/{profile}", status_code=204)
async def delete_oci_profile(profile: str):
    """Remove an OCI profile configuration."""
    if not remove_oci_profile(profile):
        raise HTTPException(status_code=404, detail=f"Profile '{profile}' not found")

    await persist_settings()
