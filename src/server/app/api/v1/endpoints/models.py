"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for retrieving model configurations.
"""
# spell-checker:ignore litellm ollama rerank

from typing import Optional

import litellm
from fastapi import APIRouter, HTTPException, Query

from server.app.core.settings import _settings_lock, settings
from server.app.database.settings import persist_settings
from server.app.models.connectivity import check_single_model
from server.app.models.litellm_utils import find_model
from server.app.models.schemas import ModelConfig, ModelSensitive, ModelUpdate, SupportedProviderIds

litellm.suppress_debug_info = True
auth = APIRouter(prefix="/models")

SENSITIVE_FIELDS = set(ModelSensitive.model_fields.keys())

_PERSIST_FAIL = "Failed to persist settings"


def _find_model(provider: str | None, model_id: str | None) -> ModelConfig | None:
    """Lookup by composite key (provider, id), case-insensitive."""
    if provider is None or model_id is None:
        return None
    return find_model(provider, model_id, enabled_only=False, case_insensitive=True)


@auth.get("", response_model=list[ModelConfig], response_model_exclude_unset=True)
async def list_models(include_sensitive: bool = Query(default=False)):
    """Return all model configurations."""
    exclude = None if include_sensitive else SENSITIVE_FIELDS
    return [cfg.model_dump(exclude=exclude) for cfg in settings.model_configs]


# --- Supported models (must be before /{provider}/{model_id:path}) ---


def _process_model_entry(model: str, type_to_modes: dict, allowed_modes: set, provider: str) -> dict | None:
    """Process a single model entry from litellm and return model dictionary."""
    try:
        details = litellm.get_model_info(model)
        if details.get("mode") not in allowed_modes:
            return None
        provider_info = litellm.get_llm_provider(model)
        api_base = provider_info[3] if len(provider_info) > 3 and provider_info[3] else None
        if api_base is None and provider == "openai":
            api_base = "https://api.openai.com/v1"
        elif api_base is None and provider == "anthropic":
            api_base = "https://api.anthropic.com/v1/"
        model_entry = {k: v for k, v in details.items() if v is not None}
        if api_base:
            model_entry["api_base"] = api_base
        model_mode = details.get("mode")
        for type_name, modes in type_to_modes.items():
            if model_mode in modes:
                model_entry["type"] = type_name
                break
        return model_entry
    except Exception:
        return {"key": model}


def _get_supported(
    model_provider: str | None = None,
    model_type: str | None = None,
) -> list[SupportedProviderIds]:
    """Return supported providers and models from LiteLLM."""
    type_to_modes = {"ll": {"chat", "completion", "responses"}, "embed": {"embedding"}, "rerank": {"rerank"}}
    all_modes = {"chat", "completion", "embedding", "responses", "rerank"}
    allowed_modes = type_to_modes.get(model_type, all_modes) if model_type else all_modes
    skip_providers = {"ollama", "ollama_chat", "github_copilot", "chatgpt"}
    result: list[SupportedProviderIds] = []
    providers: list[str] = [getattr(p, "value", p) for p in litellm.provider_list]
    for provider in sorted(providers):
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


@auth.get("/{provider}/{model_id:path}", response_model=ModelConfig, response_model_exclude_unset=True)
async def get_model(provider: str, model_id: str, include_sensitive: bool = Query(default=False)):
    """Return a single model configuration by provider and id (case-insensitive)."""
    cfg = _find_model(provider, model_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Model config not found: {provider}/{model_id}")
    exclude = None if include_sensitive else SENSITIVE_FIELDS
    return cfg.model_dump(exclude=exclude)


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
        updates = body.model_dump(exclude_unset=True)
        # Check if provider/id change would create a duplicate composite key
        if "provider" in updates or "id" in updates:
            new_provider = updates.get("provider", cfg.provider)
            new_id = updates.get("id", cfg.id)
            existing = _find_model(new_provider, new_id)
            if existing is not None and existing is not cfg:
                raise HTTPException(status_code=409, detail=f"Model config already exists: {new_provider}/{new_id}")
        originals = {field: getattr(cfg, field) for field in updates}
        saved_usable = cfg.usable
        saved_enabled = cfg.enabled
        for field, value in updates.items():
            setattr(cfg, field, value)
        await check_single_model(cfg)
        if not await persist_settings():
            for field, value in originals.items():
                setattr(cfg, field, value)
            cfg.usable = saved_usable
            cfg.enabled = saved_enabled
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
