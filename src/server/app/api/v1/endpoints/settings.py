"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoint for retrieving server settings.
"""
# spell-checker: ignore litellm

import json
import logging
from typing import Callable

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute

from server.app.api.v1.schemas.settings import (
    ImportSectionResult,
    SettingsImport,
    SettingsImportResult,
    SettingsResponse,
)
from server.app.core.etc import ensure_core_alias, migrate_legacy_settings, upsert_list_field
from server.app.core.schemas import ClientSettings, ClientSettingsUpdate, LLModelSettings
from server.app.core.settings import (
    _PROTECTED_CLIENTS,
    _apply_default_ll_model,
    _client_store,
    _ensure_capacity,
    _settings_lock,
    resolve_client,
    settings,
)
from server.app.database.schemas import DatabaseSensitive, DatabaseUpdate
from server.app.database.settings import delete_row, load_settings, persist_client_settings, persist_settings
from server.app.mcp.prompts.registry import load_factory_prompts, reconcile_prompt_customizations, register_mcp_prompts
from server.app.models.connectivity import check_model_reachability
from server.app.models.litellm_utils import find_model
from server.app.models.ollama import load_ollama_models
from server.app.models.registry import apply_env_overrides, reset_factory_models
from server.app.models.schemas import ModelSensitive
from server.app.oci.schemas import OciSensitive

LOGGER = logging.getLogger(__name__)
_DB_CONN_FIELDS = set(DatabaseUpdate.model_fields)


class LegacyMigratingImportRoute(APIRoute):
    """Migrate legacy settings payloads before FastAPI validates them.

    Intercepts the raw request body for POST /settings/import, runs
    ``migrate_legacy_settings`` on the parsed JSON, and replaces the request
    body stream with the migrated bytes. The downstream handler still receives
    a typed ``SettingsImport`` so the OpenAPI schema (and generated clients)
    remain intact.
    """

    def get_route_handler(self) -> Callable:
        original_handler = super().get_route_handler()

        async def custom_handler(request: Request) -> Response:
            body_bytes = await request.body()
            if body_bytes:
                try:
                    parsed = json.loads(body_bytes)
                except json.JSONDecodeError:
                    # Let FastAPI's default handling surface the decode error.
                    return await original_handler(request)
                migrated = migrate_legacy_settings(parsed)
                if migrated is not parsed:
                    new_body = json.dumps(migrated).encode("utf-8")

                    async def receive() -> dict:
                        return {"type": "http.request", "body": new_body, "more_body": False}

                    request = Request(request.scope, receive)
            return await original_handler(request)

        return custom_handler


auth = APIRouter(prefix="/settings")
_import_router = APIRouter(route_class=LegacyMigratingImportRoute)


def _restore_prompts(saved: dict[str, str]) -> None:
    """Restore prompt texts from a snapshot and re-register MCP prompts."""
    for pc in settings.prompt_configs:
        pc.text = saved.get(pc.name, pc.text)
    register_mcp_prompts()


_PERSIST_FAIL = "Failed to persist settings"

SENSITIVE_FIELDS = {
    "database_configs": {"__all__": set(DatabaseSensitive.model_fields.keys())},
    "model_configs": {"__all__": set(ModelSensitive.model_fields.keys())},
    "oci_configs": {"__all__": set(OciSensitive.model_fields.keys())},
}


@auth.get("", response_model=SettingsResponse, response_model_exclude_unset=True)
async def get_client_settings(
    client: str = Query(default="CONFIGURED"),
    include_sensitive: bool = Query(default=False, include_in_schema=False),
):
    """Return application settings combined with client settings."""
    exclude = None if include_sensitive else SENSITIVE_FIELDS
    data = settings.model_dump(exclude=exclude)
    data["client_settings"] = resolve_client(client).model_dump()
    return data


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
    user_customized = current.max_tokens != old_default_max

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
async def update_client_settings(body: ClientSettingsUpdate, client: str = Query(default="CONFIGURED")):
    """Update client settings in memory."""
    async with _settings_lock:
        cs = resolve_client(client)
        if body.ll_model is not None:
            _reconcile_ll_model_tokens(cs.ll_model, body.ll_model)
        for field in body.model_fields_set:
            if field == "ll_model" and body.ll_model is not None:
                # Merge individual ll_model fields instead of replacing the whole object
                for ll_field in body.ll_model.model_fields_set:
                    setattr(cs.ll_model, ll_field, getattr(body.ll_model, ll_field))
            elif field == "vector_search" and body.vector_search is not None:
                # Merge individual vector_search fields instead of replacing the whole object
                for vs_field in body.vector_search.model_fields_set:
                    setattr(cs.vector_search, vs_field, getattr(body.vector_search, vs_field))
            else:
                # Note: nested objects (database, testbed, etc.) are replaced
                # wholesale — not field-merged like ll_model / vector_search.
                # This is intentional: those objects are always sent in full.
                setattr(cs, field, getattr(body, field))
        return cs


@auth.post("", response_model=SettingsResponse, status_code=201, response_model_exclude_unset=True)
async def create_client_settings(client: str = Query(default="CONFIGURED")):
    """Create a new client session from persisted CONFIGURED defaults."""
    async with _settings_lock:
        if client in _client_store:
            raise HTTPException(status_code=409, detail=f"Client '{client}' already exists")

        persisted = await load_settings("CONFIGURED")
        data = (persisted or settings).model_dump(exclude=SENSITIVE_FIELDS)

        cs = ClientSettings(client=client)
        _apply_default_ll_model(cs)
        _ensure_capacity()
        _client_store[client] = cs
        data["client_settings"] = cs.model_dump()
        return data


@auth.post("/server/copy", response_model=ClientSettings)
async def copy_to_server(client: str = Query(default="CONFIGURED")):
    """Copy a source client's client_settings to the SERVER client."""
    async with _settings_lock:
        source_cs = resolve_client(client)
        server_cs = source_cs.model_copy(deep=True)
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


@_import_router.post("/import", response_model=SettingsImportResult)
async def import_settings(body: SettingsImport, client: str = Query(default="CONFIGURED")):
    """Import a partial or full configuration with incoming-wins semantics.

    The raw body is migrated through ``migrate_legacy_settings`` by
    :class:`LegacyMigratingImportRoute` before Pydantic validation, so payloads
    exported from older versions (e.g. v2.0.3's ``database_configs`` entries
    keyed by ``name``/``user``) are accepted.
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
            core_exists = any(c.alias.upper() == "CORE" for c in settings.database_configs)
            if core_exists:
                importable = [db for db in body.database_configs if db.alias.upper() != "CORE"]
            else:
                importable = list(body.database_configs)
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
            result.model_configs = ImportSectionResult(created=len(created), updated=len(updated))

        # --- OCI configs ---
        if body.oci_configs is not None:
            created, updated = upsert_list_field("oci_configs", body.oci_configs)
            for item in created + updated:
                item.usable = False
            result.oci_configs = ImportSectionResult(created=len(created), updated=len(updated))

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

        # --- Persist once — rollback everything on failure ---
        if not await persist_settings():
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
        data["client_settings"] = settings.client_settings.model_dump()
        return data


@auth.delete("", status_code=204)
async def delete_client_settings(client: str = Query(...)):
    """Delete a client session from the in-memory store and the database."""
    async with _settings_lock:
        if client in _PROTECTED_CLIENTS:
            raise HTTPException(status_code=403, detail=f"Cannot delete the {client} client")
        if client not in _client_store:
            raise HTTPException(status_code=404, detail=f"Client '{client}' not found")

        _client_store.pop(client)
        await delete_row(client)
        return Response(status_code=204)


# Mount the import endpoint with the legacy-migration route class so that
# v2.0.3-shaped payloads are normalised before Pydantic validation, while
# keeping the typed `SettingsImport` body in the OpenAPI schema.
auth.include_router(_import_router)
