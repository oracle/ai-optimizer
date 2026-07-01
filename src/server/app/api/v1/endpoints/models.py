"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for retrieving model configurations.
"""
# spell-checker:ignore litellm ollama rerank

import json
import logging
from typing import Optional

import litellm
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from server.app.api.v1.endpoints._helpers import _build_updates, _log_sensitive_read
from server.app.core.constants import PERSIST_FAIL_DETAIL as _PERSIST_FAIL
from server.app.core.secrets import REVEAL_KEY
from server.app.core.settings import _settings_lock, settings
from server.app.database.settings import persist_settings
from server.app.models.connectivity import check_single_model
from server.app.models.litellm_utils import find_model
from server.app.models.ollama import pull_ollama_model
from server.app.models.schemas import ModelConfig, ModelSensitive, ModelUpdate, SupportedProviderIds

LOGGER = logging.getLogger(__name__)
litellm.suppress_debug_info = True
auth = APIRouter(prefix="/models")

SENSITIVE_FIELDS = set(ModelSensitive.model_fields.keys())
# Fields where a blank submission means "preserve existing".
SECRET_UPDATE_FIELDS = frozenset({"api_key"})


def _find_model(provider: str | None, model_id: str | None) -> ModelConfig | None:
    """Lookup by composite key (provider, id), case-insensitive."""
    if provider is None or model_id is None:
        return None
    return find_model(provider, model_id, enabled_only=False, case_insensitive=True)


@auth.get("", response_model=list[ModelConfig], response_model_exclude_unset=True)
async def list_models():
    """Return all model configurations.  Sensitive fields are always omitted
    from list responses.
    """
    return [cfg.model_dump(exclude=SENSITIVE_FIELDS) for cfg in settings.model_configs]


# --- Supported models (must be before /{provider}/{model_id:path}) ---


def _process_model_entry(model: str, type_to_modes: dict, allowed_modes: set, provider: str) -> dict | None:
    """Build a model entry from LiteLLM's static cost map.

    Reads ``litellm.model_cost`` (an in-memory dict bundled with the package)
    rather than calling ``litellm.get_model_info``/``get_llm_provider``.  Those
    helpers resolve the provider at call time and, for some providers (local
    servers such as ``lemonade``, or auth-backed ones), perform live network or
    auth I/O.  Iterating every supported model through them blocked this endpoint
    for minutes — past the client read timeout.  The static map carries the same
    fields the UI consumes (``mode``, ``max_input_tokens``, ``max_tokens``) with
    no I/O.  Names in ``models_by_provider`` are the keys of ``model_cost`` and
    ``get_model_info``'s ``key`` was just the model name, so the output shape is
    preserved.
    """
    details = litellm.model_cost.get(model)
    if details is None:
        # No static metadata: keep the model selectable (mirrors the prior
        # get_model_info failure fallback) with just its identifier.
        return {"key": model}
    if details.get("mode") not in allowed_modes:
        return None
    model_entry = {k: v for k, v in details.items() if v is not None}
    model_entry["key"] = model
    # api_base is no longer resolved via get_llm_provider (that was the I/O
    # path); only the two providers with a well-known public base are filled.
    api_base = None
    if provider == "openai":
        api_base = "https://api.openai.com/v1"
    elif provider == "anthropic":
        api_base = "https://api.anthropic.com/v1/"
    if api_base:
        model_entry["api_base"] = api_base
    model_mode = details.get("mode")
    for type_name, modes in type_to_modes.items():
        if model_mode in modes:
            model_entry["type"] = type_name
            break
    return model_entry


def _get_supported(
    model_provider: str | None = None,
    model_type: str | None = None,
) -> list[SupportedProviderIds]:
    """Return supported providers and models from LiteLLM."""
    type_to_modes = {"ll": {"chat", "completion", "responses"}, "embed": {"embedding"}, "rerank": {"rerank"}}
    all_modes = {"chat", "completion", "embedding", "responses", "rerank"}
    allowed_modes = type_to_modes.get(model_type, all_modes) if model_type else all_modes
    skip_providers = {"ollama", "ollama_chat", "github_copilot", "chatgpt"}
    # ``ollama_chat`` is an internal LiteLLM alias, not a user-facing provider: configs are
    # stored as ``ollama`` and the runtime normalizes ``ollama`` -> ``ollama_chat`` for LLM
    # calls (embeddings stay ``ollama``). Don't offer it as a separate, selectable provider.
    hidden_providers = {"ollama_chat"}
    result: list[SupportedProviderIds] = []
    providers: list[str] = [getattr(p, "value", p) for p in litellm.provider_list]
    for provider in sorted(providers):
        if provider in hidden_providers:
            continue
        if model_provider and provider != model_provider:
            continue
        ids = []
        if provider not in skip_providers:
            for model in litellm.models_by_provider.get(provider, []):
                entry = _process_model_entry(model, type_to_modes, allowed_modes, provider)
                if entry is not None:
                    ids.append(entry)
        result.append(SupportedProviderIds(provider=provider, ids=ids))
    return result


@auth.get("/supported", response_model=list[SupportedProviderIds])
async def models_supported(
    model_provider: Optional[str] = Query(None),
    model_type: Optional[str] = Query(None),
) -> list[SupportedProviderIds]:
    """List supported providers and models from LiteLLM."""
    return _get_supported(model_provider=model_provider, model_type=model_type)


# --- Pull endpoint (must be before /{provider}/{model_id:path}) ---


@auth.post("/pull/{provider}/{model_id:path}")
async def pull_model(provider: str, model_id: str):
    """Pull an Ollama model and stream progress as NDJSON."""
    if provider.casefold() != "ollama":
        raise HTTPException(status_code=400, detail="Pull is only supported for Ollama models")

    cfg = _find_model(provider, model_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Model config not found: {provider}/{model_id}")
    if not cfg.api_base:
        raise HTTPException(status_code=400, detail=f"Model {provider}/{model_id} has no API base URL configured")
    api_base: str = cfg.api_base

    async def _stream():
        error_occurred = False
        async for event in pull_ollama_model(api_base, model_id):
            if "error" in event:
                error_occurred = True
            yield json.dumps(event) + "\n"
        if not error_occurred:
            await check_single_model(cfg)
            if not await persist_settings():
                yield json.dumps({"error": _PERSIST_FAIL}) + "\n"
            else:
                yield json.dumps({"status": "success"}) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@auth.get("/{provider}/{model_id:path}", response_model=ModelConfig, response_model_exclude_unset=True)
async def get_model(
    provider: str,
    model_id: str,
    request: Request,
    include_sensitive: bool = Query(default=False),
):
    """Return a single model configuration by provider and id (case-insensitive)."""
    cfg = _find_model(provider, model_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Model config not found: {provider}/{model_id}")
    if include_sensitive:
        _log_sensitive_read(LOGGER, "models", f"{cfg.provider}/{cfg.id}", request)
        return JSONResponse(content=cfg.model_dump(mode="json", context={REVEAL_KEY: True}))
    return cfg.model_dump(exclude=SENSITIVE_FIELDS)


@auth.post("", response_model=ModelConfig, status_code=201, response_model_exclude_unset=True)
async def create_model(body: ModelConfig):
    """Add a new model configuration."""
    async with _settings_lock:
        if _find_model(body.provider, body.id) is not None:
            raise HTTPException(status_code=409, detail=f"Model config already exists: {body.provider}/{body.id}")
        settings.model_configs.append(body)
        await check_single_model(body)
        if not await persist_settings():
            settings.model_configs.remove(body)
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
        return body.model_dump(exclude=SENSITIVE_FIELDS)


@auth.put("/{provider}/{model_id:path}", response_model=ModelConfig, response_model_exclude_unset=True)
async def update_model(provider: str, model_id: str, body: ModelUpdate):
    """Update an existing model configuration by provider and id (case-insensitive)."""
    async with _settings_lock:
        cfg = _find_model(provider, model_id)
        if cfg is None:
            raise HTTPException(status_code=404, detail=f"Model config not found: {provider}/{model_id}")
        updates = _build_updates(body, SECRET_UPDATE_FIELDS)
        # Check if provider/id change would create a duplicate composite key
        if "provider" in updates or "id" in updates:
            new_provider = updates.get("provider", cfg.provider)
            new_id = updates.get("id", cfg.id)
            existing = _find_model(new_provider, new_id)
            if existing is not None and existing is not cfg:
                raise HTTPException(status_code=409, detail=f"Model config already exists: {new_provider}/{new_id}")
        originals = {field: getattr(cfg, field) for field in updates}
        saved_status = cfg.status
        saved_enabled = cfg.enabled
        # check_single_model may mutate api_base (e.g. defaulting an Ollama server URL);
        # capture it so a persist failure leaves no probe-side change in memory.
        saved_api_base = cfg.api_base
        for field, value in updates.items():
            setattr(cfg, field, value)
        await check_single_model(cfg)
        if not await persist_settings():
            for field, value in originals.items():
                setattr(cfg, field, value)
            cfg.status = saved_status
            cfg.enabled = saved_enabled
            cfg.api_base = saved_api_base
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
        return cfg.model_dump(exclude=SENSITIVE_FIELDS)


@auth.delete("/{provider}/{model_id:path}", status_code=204)
async def delete_model(provider: str, model_id: str):
    """Remove a model configuration by provider and id (case-insensitive)."""
    async with _settings_lock:
        cfg = _find_model(provider, model_id)
        if cfg is None:
            raise HTTPException(status_code=404, detail=f"Model config not found: {provider}/{model_id}")
        idx = settings.model_configs.index(cfg)
        settings.model_configs.remove(cfg)
        if not await persist_settings():
            settings.model_configs.insert(idx, cfg)
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
        return None
