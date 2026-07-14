"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoint for retrieving server settings.
"""
# spell-checker: ignore litellm

import asyncio
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from runtime_config_fields import RUNTIME_ONLY_FIELDS
from server.app.api.v1.schemas.common import ClientId
from server.app.api.v1.schemas.settings import (
    ImportSectionResult,
    SettingsImport,
    SettingsImportResult,
    SettingsResponse,
)
from server.app.core.constants import PERSIST_FAIL_DETAIL as _PERSIST_FAIL
from server.app.core.etc import ensure_core_alias, upsert_list_field
from server.app.core.schemas import (
    ClientSettings,
    ClientSettingsUpdate,
    DeepDataSecuritySettings,
    LLModelSettings,
)
from server.app.core.secrets import REVEAL_KEY
from server.app.core.settings import (
    _PROTECTED_CLIENTS,
    _apply_default_ll_model,
    _client_store,
    _ensure_capacity,
    _settings_lock,
    resolve_client,
    settings,
)
from server.app.database.registry import refresh_db_vector_stores
from server.app.database.schemas import DatabaseSensitive, DatabaseUpdate
from server.app.database.settings import (
    delete_row,
    hide_managed_db_configs,
    load_settings,
    persist_client_settings,
    persist_settings,
)
from server.app.mcp.prompts.registry import load_factory_prompts, reconcile_prompt_customizations, register_mcp_prompts
from server.app.models.connectivity import check_model_reachability
from server.app.models.litellm_utils import find_model
from server.app.models.ollama import load_ollama_models
from server.app.models.refresh import trigger_reachability_recheck
from server.app.models.registry import apply_env_overrides, reset_factory_models
from server.app.models.schemas import ModelSensitive
from server.app.oci.schemas import (
    GENAI_OVERLAY_FIELDS,
    PRINCIPAL_OCI_AUTH_TYPES,
    OciProfileConfig,
    OciSensitive,
)

LOGGER = logging.getLogger(__name__)
_DB_CONN_FIELDS = set(DatabaseUpdate.model_fields)
# Nested client-settings objects that are field-merged on PUT (a partial payload patches
# individual sub-fields). All other nested objects are replaced wholesale.
_FIELD_MERGE_FIELDS = ("ll_model", "vector_search", "deep_data_security")


auth = APIRouter(prefix="/settings")


def _apply_oci_import(
    incoming: Optional[list[OciProfileConfig]], result: SettingsImportResult
) -> Optional[dict[str, set[str]]]:
    """Upsert OCI configs from an import body, returning the GenAI-touched map.

    Profiles whose existing counterpart uses principal-based auth (instance/
    workload/resource) are skipped — that auth is provided by the deployment
    infrastructure and the OCI form disables editing for those profiles, so
    flipping ``usable=False`` would leave the user with no way to re-validate.
    """
    if incoming is None:
        return None
    principal_profiles = {
        cfg.auth_profile.casefold()
        for cfg in settings.oci_configs
        if cfg.authentication in PRINCIPAL_OCI_AUTH_TYPES
    }
    importable = [oci for oci in incoming if oci.auth_profile.casefold() not in principal_profiles]
    skipped_profiles = [oci.auth_profile for oci in incoming if oci.auth_profile.casefold() in principal_profiles]
    if skipped_profiles:
        LOGGER.info("Skipping import for principal-auth OCI profiles: %s", sorted(skipped_profiles))
    touched = _imported_oci_genai_touched(importable)
    created, updated = upsert_list_field("oci_configs", importable)
    for item in created + updated:
        item.usable = False
    result.oci_configs = ImportSectionResult(
        created=len(created), updated=len(updated), skipped=len(skipped_profiles)
    )
    return touched


def _imported_oci_genai_touched(
    incoming: Optional[list[OciProfileConfig]],
) -> Optional[dict[str, set[str]]]:
    """Return per-profile GenAI overlay fields the import body explicitly set.

    ``persist_settings`` uses this to recognise an imported value matching
    baseline as a deliberate revert rather than carrying the prior overlay
    forward.
    """
    if not incoming:
        return None
    touched: dict[str, set[str]] = {}
    for item in incoming:
        fields = set(GENAI_OVERLAY_FIELDS & item.model_fields_set)
        if fields:
            touched[item.auth_profile] = fields
    return touched or None


def _restore_prompts(saved: dict[str, str]) -> None:
    """Restore prompt texts from a snapshot and re-register MCP prompts."""
    for pc in settings.prompt_configs:
        pc.text = saved.get(pc.name, pc.text)
    register_mcp_prompts()


SENSITIVE_FIELDS = {
    "database_configs": {"__all__": set(DatabaseSensitive.model_fields.keys())},
    "model_configs": {"__all__": set(ModelSensitive.model_fields.keys())},
    "oci_configs": {"__all__": set(OciSensitive.model_fields.keys())},
}


@auth.get("", response_model=SettingsResponse, response_model_exclude_unset=True)
async def get_client_settings(
    client: Annotated[ClientId, Query()] = "CONFIGURED",
):
    """Return application settings combined with client settings.

    Each usable database has its ``vector_stores`` list re-discovered
    against the live catalog so out-of-band ``DROP TABLE`` is reflected
    in the GUI on the next refresh. Refreshes run concurrently and each
    carries its own short deadline (see ``refresh_db_vector_stores``)
    so a slow database can't stack delays or hang the response.
    """
    # Re-probe existing model endpoints in the background (throttled) so a model that was
    # unreachable at startup recovers without blocking this response or a manual refresh.
    # It re-probes only — never discovers — so it can't resurrect a deleted model.
    trigger_reachability_recheck()
    # DDS-managed connections are runtime-only and never user-facing — don't refresh
    # (which would query through the governed end user) or surface them.
    visible = [cfg for cfg in settings.database_configs if not cfg.managed_by]
    await asyncio.gather(*(refresh_db_vector_stores(cfg) for cfg in visible))
    data = settings.model_dump(exclude=SENSITIVE_FIELDS)
    hide_managed_db_configs(data)
    data["client_settings"] = resolve_client(client).model_dump()
    return data


@auth.post("/export", response_model=None)
async def export_settings(
    request: Request,
    confirm: Annotated[str, Header(alias="X-Confirm-Export")] = "",
    client: Annotated[ClientId, Query()] = "CONFIGURED",
):
    """Return an explicit settings export."""
    if confirm.lower() != "true":
        raise HTTPException(status_code=400, detail="Export requires header X-Confirm-Export: true")
    LOGGER.warning(
        "configuration export requested (client=%s, remote=%s)",
        client,
        request.client.host if request.client else "unknown",
    )
    # Reachability is runtime-determined per host — never export it (RUNTIME_ONLY_FIELDS).
    # An import re-derives it on the target (a source's status/usable may differ here).
    # ``pool`` is already Field(exclude=True).
    data = settings.model_dump(
        mode="json",
        context={REVEAL_KEY: True},
        exclude={section: {"__all__": set(fields)} for section, fields in RUNTIME_ONLY_FIELDS.items()},
    )
    # DDS-managed connections are runtime-only — never exported (this payload reveals
    # credentials, and managed configs carry a copy of the owner's password).
    hide_managed_db_configs(data)
    # deep_data_security is runtime/session-scoped — never exported.
    data["client_settings"] = resolve_client(client).model_dump(
        mode="json", context={REVEAL_KEY: True}, exclude={"deep_data_security"}
    )
    return JSONResponse(content=data)


def _reconcile_ll_model_tokens(current: LLModelSettings, incoming: LLModelSettings) -> None:
    """Adjust max_input_tokens and max_tokens when the model identity changes."""
    old_key = (current.provider, current.id)
    new_key = (incoming.provider or current.provider, incoming.id or current.id)
    if old_key == new_key:
        return  # model didn't change

    new_cfg = find_model(new_key[0], new_key[1], enabled_only=False) if new_key[0] and new_key[1] else None
    if new_cfg is None:
        return  # unknown model — leave as-is

    # 1. Always update max_input_tokens from new model config
    incoming.max_input_tokens = new_cfg.max_input_tokens

    # 2. Determine if user customized max_tokens
    old_cfg = find_model(old_key[0], old_key[1], enabled_only=False) if old_key[0] and old_key[1] else None
    old_default_max = old_cfg.max_tokens if old_cfg else None
    # A client with no selected model only has the schema fallback (4096), not a
    # user override. Adopt the selected model's configured default on first use.
    has_previous_model = bool(current.provider and current.id)
    user_customized = has_previous_model and current.max_tokens != old_default_max

    if user_customized:
        # Keep user's max_tokens but cap at new model's max_input_tokens
        if new_cfg.max_input_tokens and current.max_tokens and current.max_tokens > new_cfg.max_input_tokens:
            incoming.max_tokens = new_cfg.max_input_tokens
        elif "max_tokens" not in incoming.model_fields_set:
            incoming.max_tokens = current.max_tokens
    else:
        # Adopt new model's default max_tokens
        incoming.max_tokens = new_cfg.max_tokens


@auth.put("", response_model=ClientSettings)
async def update_client_settings(body: ClientSettingsUpdate, client: Annotated[ClientId, Query()] = "CONFIGURED"):
    """Update client settings in memory."""
    async with _settings_lock:
        cs = resolve_client(client)
        if body.ll_model is not None:
            _reconcile_ll_model_tokens(cs.ll_model, body.ll_model)
        for field in body.model_fields_set:
            incoming = getattr(body, field)
            # Field-merge ll_model / vector_search / deep_data_security so a partial payload
            # (e.g. a lone {enabled: ...} DDS toggle) patches sub-fields without wiping their
            # siblings. Everything else is always sent in full and replaced wholesale.
            if field in _FIELD_MERGE_FIELDS and incoming is not None:
                target = getattr(cs, field)
                for sub_field in incoming.model_fields_set:
                    setattr(target, sub_field, getattr(incoming, sub_field))
            else:
                setattr(cs, field, getattr(body, field))
        return cs


@auth.post("", response_model=SettingsResponse, status_code=201, response_model_exclude_unset=True)
async def create_client_settings(client: Annotated[ClientId, Query()] = "CONFIGURED"):
    """Create a new client session from persisted CONFIGURED defaults."""
    async with _settings_lock:
        if client in _client_store:
            raise HTTPException(status_code=409, detail=f"Client '{client}' already exists")

        persisted = await load_settings("CONFIGURED")
        data = (persisted or settings).model_dump(exclude=SENSITIVE_FIELDS)
        # DDS-managed connections are runtime-only and never user-facing. The persisted row is
        # already filtered (persist_settings strips them), but the in-memory `settings` fallback
        # is not — exclude them here so a new client session can't see/select a managed alias.
        hide_managed_db_configs(data)

        cs = ClientSettings(client=client)
        _apply_default_ll_model(cs)
        _ensure_capacity()
        _client_store[client] = cs
        data["client_settings"] = cs.model_dump()
        return data


@auth.post("/server/copy", response_model=ClientSettings)
async def copy_to_server(client: Annotated[ClientId, Query()] = "CONFIGURED"):
    """Copy a source client's client_settings to the SERVER client."""
    async with _settings_lock:
        source_cs = resolve_client(client)
        # deep_data_security is runtime/session-scoped — drop any active override so a
        # source client's "connect as" alias never leaks into server/default tool routing.
        server_cs = source_cs.model_copy(deep=True, update={"deep_data_security": DeepDataSecuritySettings()})
        server_cs.client = "server"
        old_server_cs = _client_store.get("server")
        _client_store["server"] = server_cs
        if not await persist_client_settings("server", server_cs):
            if old_server_cs is not None:
                _client_store["server"] = old_server_cs
            else:
                del _client_store["server"]
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
        return server_cs


@auth.post("/import", response_model=SettingsImportResult)
async def import_settings(body: SettingsImport, client: Annotated[ClientId, Query()] = "CONFIGURED"):
    """Import a partial or full configuration with incoming-wins semantics.

    Payloads exported from older versions (e.g. v2.0.3's ``database_configs``
    entries keyed by ``name``/``user``) are normalised by
    ``SettingsImport``'s ``migrate_legacy_settings`` before-validator.
    """
    async with _settings_lock:
        snapshot = {
            "db": [cfg.model_copy() for cfg in settings.database_configs],
            "models": [cfg.model_copy() for cfg in settings.model_configs],
            "oci": [cfg.model_copy() for cfg in settings.oci_configs],
            "prompts": {pc.name: pc.text for pc in settings.prompt_configs},
            "store": {k: v.model_copy(deep=True) for k, v in _client_store.items()},
            "client_settings": settings.client_settings.model_copy(deep=True),
            "log_level": settings.log_level,
        }
        result = SettingsImportResult()

        # --- Database configs ---
        if body.database_configs is not None:
            # managed_by is server-owned (runtime-only DDS connections) and never exported, so a
            # legit round-trip never carries it; normalise any client-supplied value to None so an
            # import can never *create* a config masquerading as managed.
            for db in body.database_configs:
                db.managed_by = None
            core_exists = any(c.alias.upper() == "CORE" for c in settings.database_configs)
            # Skip any incoming alias that collides with an existing hidden DDS-managed connection:
            # the normalised managed_by=None is now in model_fields_set, so upserting onto the
            # managed config would clear its server-owned marker and expose a runtime-only connect-as
            # connection as a normal/persisted/exportable database config.
            managed_aliases = {cfg.alias.lower() for cfg in settings.database_configs if cfg.managed_by}
            importable = [
                db
                for db in body.database_configs
                if db.alias.lower() not in managed_aliases and not (core_exists and db.alias.upper() == "CORE")
            ]
            skipped = len(body.database_configs) - len(importable)
            pre_import_db = {cfg.alias: cfg for cfg in snapshot["db"]}
            created, updated = upsert_list_field("database_configs", importable)
            for item in created + updated:
                prior = pre_import_db.get(item.alias)
                if not prior or any(getattr(item, f) != getattr(prior, f) for f in _DB_CONN_FIELDS):
                    item.usable, item.pool = False, None
                else:
                    item.usable, item.pool = prior.usable, prior.pool
            if not core_exists:
                ensure_core_alias(settings.database_configs, settings.client_settings, _client_store)
            result.database_configs = ImportSectionResult(
                created=len(created),
                updated=len(updated),
                skipped=skipped,
            )

        # --- Model configs ---
        if body.model_configs is not None:
            created, updated = upsert_list_field("model_configs", body.model_configs)
            # Reachability is target-local runtime state, never trusted from the payload: reset the
            # runtime-only fields to their neutral defaults so disabled imports don't carry a stale
            # status (the recheck below only re-derives status for enabled models).
            for item in created + updated:
                for field in RUNTIME_ONLY_FIELDS["model_configs"]:
                    setattr(item, field, type(item).model_fields[field].get_default())
            result.model_configs = ImportSectionResult(created=len(created), updated=len(updated))

        # --- OCI configs ---
        oci_touched = _apply_oci_import(body.oci_configs, result)

        # --- Prompt configs ---
        if body.prompt_configs is not None:
            before = {pc.name: pc.text for pc in settings.prompt_configs}
            reconcile_prompt_customizations(body.prompt_configs)
            register_mcp_prompts()
            result.prompt_configs = ImportSectionResult(
                updated=(n := sum(1 for pc in settings.prompt_configs if before.get(pc.name) != pc.text)),
                skipped=len(body.prompt_configs) - n,
            )

        # --- Client settings ---
        if body.client_settings is not None:
            if client not in _client_store:
                _ensure_capacity()
            _client_store[client] = body.client_settings.model_copy(deep=True, update={"client": client})
            result.client_settings = True

        # --- Importable scalars ---
        if body.log_level is not None:
            settings.log_level = body.log_level
            result.scalars = {"log_level": body.log_level}

        # Reachability is runtime state, never trusted from the payload — re-determine it on
        # this host so imported models reflect real availability (mirrors the database section
        # resetting usable/pool above), rather than carrying the source's stale status.
        if body.model_configs is not None or body.oci_configs is not None:
            await check_model_reachability()

        # --- Persist once — rollback everything on failure ---
        if not await persist_settings(oci_user_touched=oci_touched):
            (settings.database_configs, settings.model_configs, settings.oci_configs, settings.log_level) = (
                snapshot["db"],
                snapshot["models"],
                snapshot["oci"],
                snapshot["log_level"],
            )
            settings.client_settings = snapshot["client_settings"]
            _restore_prompts(snapshot["prompts"])
            _client_store.clear()
            _client_store.update(snapshot["store"])
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)

        return result


@auth.post("/reset", response_model=SettingsResponse, response_model_exclude_unset=True)
async def reset_to_factory():
    """Reset models, prompts, and client settings to factory defaults.

    Infrastructure configs (database_configs, oci_configs) are preserved.
    """
    async with _settings_lock:
        # Snapshot
        saved_models = settings.model_configs[:]
        saved_prompts = {pc.name: pc.text for pc in settings.prompt_configs}
        saved_cs = settings.client_settings.model_copy(deep=True)
        saved_store = dict(_client_store)

        # 1. Rebuild model_configs from FACTORY_MODELS + env overrides + Ollama discovery
        reset_factory_models()
        apply_env_overrides()
        await load_ollama_models()

        # 2. Rebuild prompt_configs from FACTORY_PROMPTS
        load_factory_prompts()
        register_mcp_prompts()

        # 3. Re-probe model endpoints
        await check_model_reachability()

        # 4. Reset all protected clients (except FACTORY) to factory defaults
        factory_cs = ClientSettings()
        _apply_default_ll_model(factory_cs)

        client_entries = {}
        for key in _PROTECTED_CLIENTS - frozenset(("FACTORY",)):
            cs = factory_cs.model_copy(deep=True)
            cs.client = key
            if key == "CONFIGURED":
                settings.client_settings = cs
            else:
                _client_store[key] = cs
            client_entries[key] = cs

        # Persist app state (models, prompts, CONFIGURED client) first
        if not await persist_settings("CONFIGURED"):
            settings.model_configs = saved_models
            _restore_prompts(saved_prompts)
            settings.client_settings = saved_cs
            _client_store.clear()
            _client_store.update(saved_store)
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)

        # Persist non-CONFIGURED protected clients (best-effort after app state is safe)
        for key, cs in client_entries.items():
            if key != "CONFIGURED":
                if not await persist_client_settings(key, cs):
                    LOGGER.warning("reset_to_factory: failed to persist client=%s", key)

        # 5. Evict non-protected client sessions
        for key in [k for k in _client_store if k not in _PROTECTED_CLIENTS]:
            del _client_store[key]

        data = settings.model_dump(exclude=SENSITIVE_FIELDS)
        # DDS-managed connections are runtime-only and never user-facing.
        hide_managed_db_configs(data)
        data["client_settings"] = settings.client_settings.model_dump()
        return data


@auth.delete("", status_code=204)
async def delete_client_settings(client: Annotated[ClientId, Query()]):
    """Delete a client session from the in-memory store and the database."""
    async with _settings_lock:
        if client in _PROTECTED_CLIENTS:
            raise HTTPException(status_code=403, detail=f"Cannot delete the {client} client")
        if client not in _client_store:
            raise HTTPException(status_code=404, detail=f"Client '{client}' not found")

        _client_store.pop(client)
        await delete_row(client)
        return Response(status_code=204)
