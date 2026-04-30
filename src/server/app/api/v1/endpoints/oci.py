"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for retrieving OCI profile configurations.
"""
# spell-checker: ignore genai

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from server.app.api.v1.endpoints._helpers import _build_updates, _log_sensitive_read
from server.app.api.v1.schemas.common import ClientId
from server.app.core.error_detail import response_error_detail
from server.app.core.file_utils import get_temp_directory
from server.app.core.secrets import REVEAL_KEY
from server.app.core.settings import _settings_lock, settings
from server.app.database.settings import persist_settings
from server.app.models.connectivity import check_single_model
from server.app.oci.bucket import (
    download_object,
    get_bucket_object_names,
    get_buckets,
    get_compartments,
)
from server.app.oci.config import _check_usable
from server.app.oci.schemas import OciProfileConfig, OciProfileUpdate, OciSensitive
from server.app.oci.service import create_genai_models as _create_genai_models
from server.app.oci.service import get_genai_models as _get_genai_models

LOGGER = logging.getLogger(__name__)

auth = APIRouter(prefix="/oci")

SENSITIVE_FIELDS = set(OciSensitive.model_fields.keys())
# Fields where a blank submission means "preserve existing".  Narrower than
# ``SENSITIVE_FIELDS``: ``fingerprint`` (public identifier) and
# ``security_token_file`` (path) are response-masked but are not credential
# values and must remain clearable via PUT.
SECRET_UPDATE_FIELDS = frozenset({"key_content", "pass_phrase"})

_PERSIST_FAIL = "Failed to persist settings"


@auth.get("", response_model=list[OciProfileConfig], response_model_exclude_unset=True)
async def list_oci_profiles():
    """Return all OCI profile configurations.  Sensitive fields are always
    omitted from list responses.
    """
    return [cfg.model_dump(exclude=SENSITIVE_FIELDS) for cfg in settings.oci_configs]


@auth.get("/{auth_profile}", response_model=OciProfileConfig, response_model_exclude_unset=True)
async def get_oci_profile(
    auth_profile: str,
    request: Request,
    include_sensitive: bool = Query(default=False),
):
    """Return a single OCI profile configuration by auth_profile (case-insensitive)."""
    for cfg in settings.oci_configs:
        if cfg.auth_profile.lower() == auth_profile.lower():
            if include_sensitive:
                _log_sensitive_read(LOGGER, "oci", cfg.auth_profile, request)
                return JSONResponse(content=cfg.model_dump(mode="json", context={REVEAL_KEY: True}))
            return cfg.model_dump(exclude=SENSITIVE_FIELDS)
    raise HTTPException(status_code=404, detail=f"OCI profile config not found: {auth_profile}")


@auth.post("", response_model=OciProfileConfig, status_code=201, response_model_exclude_unset=True)
async def create_oci_profile(body: OciProfileConfig):
    """Add a new OCI profile configuration."""
    async with _settings_lock:
        for cfg in settings.oci_configs:
            if cfg.auth_profile.lower() == body.auth_profile.lower():
                raise HTTPException(status_code=409, detail=f"OCI profile config already exists: {body.auth_profile}")
        settings.oci_configs.append(body)
        error = _check_usable(body)
        if not await persist_settings():
            settings.oci_configs.remove(body)
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
        if error:
            raise HTTPException(status_code=422, detail=f"OCI profile not usable: {error}")
        return body.model_dump(exclude=SENSITIVE_FIELDS)


@auth.put("/{auth_profile}", response_model=OciProfileConfig, response_model_exclude_unset=True)
async def update_oci_profile(auth_profile: str, body: OciProfileUpdate):
    """Update an existing OCI profile configuration by auth_profile (case-insensitive)."""
    async with _settings_lock:
        cfg = next(
            (c for c in settings.oci_configs if c.auth_profile.lower() == auth_profile.lower()),
            None,
        )
        if cfg is None:
            raise HTTPException(status_code=404, detail=f"OCI profile config not found: {auth_profile}")
        was_usable = cfg.usable
        old_genai_region = cfg.genai_region
        updates = _build_updates(body, SECRET_UPDATE_FIELDS)
        originals = {field: getattr(cfg, field) for field in updates}
        for field, value in updates.items():
            setattr(cfg, field, value)
        error = _check_usable(cfg)
        if error:
            if was_usable:
                for field, value in originals.items():
                    setattr(cfg, field, value)
                cfg.usable = True
            if not await persist_settings():
                # Persistence failed — ensure all mutations are rolled back
                for field, value in originals.items():
                    setattr(cfg, field, value)
                raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
            raise HTTPException(status_code=422, detail=f"OCI profile not usable: {error}")
        # Purge stale OCI models when genai_region changes
        saved_model_configs = settings.model_configs[:]
        if cfg.genai_region != old_genai_region:
            settings.model_configs = [m for m in settings.model_configs if m.provider != "oci"]
        if not await persist_settings():
            for field, value in originals.items():
                setattr(cfg, field, value)
            cfg.usable = was_usable
            settings.model_configs = saved_model_configs
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
        return cfg.model_dump(exclude=SENSITIVE_FIELDS)


@auth.delete("/{auth_profile}", status_code=204)
async def delete_oci_profile(auth_profile: str):
    """Remove an OCI profile configuration by auth_profile (case-insensitive)."""
    async with _settings_lock:
        for i, cfg in enumerate(settings.oci_configs):
            if cfg.auth_profile.lower() == auth_profile.lower():
                settings.oci_configs.pop(i)
                if not await persist_settings():
                    settings.oci_configs.insert(i, cfg)
                    raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
                return None
        raise HTTPException(status_code=404, detail=f"OCI profile config not found: {auth_profile}")


def _find_oci_profile(auth_profile: str) -> OciProfileConfig:
    """Look up an OCI profile by auth_profile (case-insensitive) or raise 404."""
    for cfg in settings.oci_configs:
        if cfg.auth_profile.lower() == auth_profile.lower():
            return cfg
    raise HTTPException(status_code=404, detail=f"OCI profile config not found: {auth_profile}")


@auth.get("/genai/{auth_profile}", response_model=list)
async def list_genai_models(auth_profile: str):
    """List available GenAI models across subscribed regions."""
    profile = _find_oci_profile(auth_profile)
    try:
        return _get_genai_models(profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@auth.post("/genai/{auth_profile}", response_model=list)
async def enable_genai_models(auth_profile: str):
    """Enable GenAI models for the configured region."""
    async with _settings_lock:
        profile = _find_oci_profile(auth_profile)
        saved_model_configs = settings.model_configs[:]
        try:
            models = await _create_genai_models(profile)
            for model in models:
                await check_single_model(model)
        except ValueError as exc:
            settings.model_configs = saved_model_configs
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not await persist_settings():
            settings.model_configs = saved_model_configs
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
        return [m.model_dump() for m in models]


# ---------------------------------------------------------------------------
# Object Storage Browsing
# ---------------------------------------------------------------------------


@auth.get("/compartments/{auth_profile}", response_model=dict)
async def oci_list_compartments(auth_profile: str):
    """List OCI compartments as path-to-OCID mapping."""
    profile = _find_oci_profile(auth_profile)
    try:
        return get_compartments(profile)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=response_error_detail(exc, "OCI compartment listing failed."),
        ) from exc


@auth.get("/buckets/{compartment_ocid}/{auth_profile}", response_model=list[str])
async def oci_list_buckets(compartment_ocid: str, auth_profile: str):
    """List bucket names in a compartment."""
    profile = _find_oci_profile(auth_profile)
    try:
        return get_buckets(compartment_ocid, profile)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=response_error_detail(exc, "OCI bucket listing failed."),
        ) from exc


@auth.get("/objects/{bucket_name}/{auth_profile}", response_model=list[str])
async def oci_list_bucket_objects(bucket_name: str, auth_profile: str):
    """List object names in a bucket."""
    profile = _find_oci_profile(auth_profile)
    try:
        return get_bucket_object_names(bucket_name, profile)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=response_error_detail(exc, "OCI object listing failed."),
        ) from exc


@auth.post("/objects/download/{bucket_name}/{auth_profile}", response_model=list[str])
async def oci_download_objects(
    bucket_name: str,
    auth_profile: str,
    request: list[str] = Body(
        ...,
        examples=[["product-catalog.pdf", "release-notes/2026-q2.md"]],
    ),
    client: Annotated[ClientId, Header()] = "server",
):
    """Download objects from a bucket to the client's temp directory."""
    profile = _find_oci_profile(auth_profile)
    temp_directory = get_temp_directory(client, "embedding")
    downloaded = []
    for object_name in request:
        try:
            file_path = download_object(str(temp_directory), object_name, bucket_name, profile)
            downloaded.append(os.path.basename(file_path))
        except Exception as exc:
            LOGGER.warning("Failed to download %s: %s", object_name, exc)
    return downloaded
