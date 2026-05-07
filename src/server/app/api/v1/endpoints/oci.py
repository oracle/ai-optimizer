"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for retrieving OCI profile configurations.
"""
# spell-checker: ignore genai

import asyncio
import logging
import os
from typing import Annotated

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from server.app.api.v1.endpoints._helpers import _build_updates, _log_sensitive_read
from server.app.api.v1.schemas.common import ClientId
from server.app.core.client_locks import _client_lock
from server.app.core.error_detail import response_error_detail
from server.app.core.file_utils import get_temp_directory
from server.app.core.secrets import REVEAL_KEY
from server.app.core.settings import _settings_lock, settings
from server.app.database.settings import persist_settings
from server.app.models.connectivity import check_single_model
from server.app.oci.bucket import (
    download_object,
    flatten_bucket_key,
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


async def _download_bucket_objects_to_dir(
    temp_directory,
    profile: OciProfileConfig,
    bucket_name: str,
    object_names: list[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Download *object_names* from *bucket_name* into *temp_directory*.

    Caller MUST already hold ``_client_lock`` for the relevant client —
    this helper has no lock semantics so it can be reused from
    ``oci_download_objects`` (which acquires the lock itself) and from
    the single-call ``/v1/embed/oci/store`` endpoint (which holds the
    lock across download + claim + submit).

    Returns ``(downloaded_basenames, failures)``. ``downloaded_basenames``
    is the list of local basenames that were written (one entry per
    successful key — colliding flattened keys produce duplicate
    basenames, since each input key was honored by a sequential
    last-writer-wins write). ``failures`` is a list of
    ``(object_name, error_message)`` tuples for keys that raised
    during download. Two-step callers can ignore the failures and
    return only the basenames; callers that need all-or-nothing
    semantics (single-call OCI embed) must check ``failures`` and
    abort before downstream consumers see a partial corpus.

    ``download_object`` is a synchronous OCI SDK call (streams the
    whole object before returning); offload via ``asyncio.to_thread``
    so the FastAPI event loop stays responsive and the embed-job
    heartbeat doesn't starve under long downloads.

    Group by ``flatten_bucket_key`` destination: two object keys like
    ``a/b.txt`` and ``a_b.txt`` both target the same local path, and
    concurrent ``open(..., "wb")`` would interleave or truncate
    writes, corrupting the file. Within a destination group we run
    sequentially (last writer wins, matching the pre-parallel loop's
    behavior); across groups we run concurrently for the common
    no-collision case.
    """
    groups: dict[str, list[str]] = {}
    for object_name in object_names:
        groups.setdefault(flatten_bucket_key(object_name), []).append(object_name)

    async def _download_destination(names: list[str]) -> list[tuple[str, str | BaseException]]:
        results: list[tuple[str, str | BaseException]] = []
        for name in names:
            try:
                path = await asyncio.to_thread(
                    download_object, str(temp_directory), name, bucket_name, profile,
                )
                results.append((name, path))
            except Exception as ex:  # noqa: BLE001 — caller decides what to do with the failure
                results.append((name, ex))
        return results

    group_results = await asyncio.gather(
        *(_download_destination(names) for names in groups.values()),
    )

    downloaded: list[str] = []
    failures: list[tuple[str, str]] = []
    for results in group_results:
        for object_name, result in results:
            if isinstance(result, BaseException):
                LOGGER.warning("Failed to download %s: %s", object_name, result)
                failures.append((object_name, f"{type(result).__name__}: {result}"))
            else:
                downloaded.append(os.path.basename(result))
    return downloaded, failures


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
    """Download objects from a bucket to the client's temp directory.

    Failures are logged but not surfaced in the response — the caller
    can diff the request list against the returned basenames to spot
    them. For all-or-nothing semantics use ``/v1/embed/oci/store``.
    """
    profile = _find_oci_profile(auth_profile)
    temp_directory = get_temp_directory(client, "embedding")

    # Serialize shared-dir writes against a concurrent /embed/ retry
    # restore — see ``_restore_claimed_files_to_shared_under_lock``.
    async with _client_lock(client):
        downloaded, _failures = await _download_bucket_objects_to_dir(
            temp_directory, profile, bucket_name, request,
        )
        return downloaded
