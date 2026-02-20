"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for retrieving model configurations.
"""

from fastapi import APIRouter, HTTPException, Query

from server.app.models.schemas import ModelConfig, ModelSensitive, ModelUpdate
from server.app.database.settings import persist_settings
from server.app.core.settings import settings

auth = APIRouter(prefix='/models')

SENSITIVE_FIELDS = set(ModelSensitive.model_fields.keys())


def _find_model(provider: str, model_id: str) -> ModelConfig | None:
    """Lookup by composite key (provider, id), case-insensitive."""
    for cfg in settings.model_configs:
        if cfg.provider.lower() == provider.lower() and cfg.id.lower() == model_id.lower():
            return cfg
    return None


@auth.get('', response_model=list[ModelConfig], response_model_exclude_unset=True)
async def list_models(include_sensitive: bool = Query(default=False)):
    """Return all model configurations."""
    exclude = None if include_sensitive else SENSITIVE_FIELDS
    return [cfg.model_dump(exclude=exclude) for cfg in settings.model_configs]


@auth.get('/{provider}/{model_id:path}', response_model=ModelConfig, response_model_exclude_unset=True)
async def get_model(provider: str, model_id: str, include_sensitive: bool = Query(default=False)):
    """Return a single model configuration by provider and id (case-insensitive)."""
    cfg = _find_model(provider, model_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f'Model config not found: {provider}/{model_id}')
    exclude = None if include_sensitive else SENSITIVE_FIELDS
    return cfg.model_dump(exclude=exclude)


@auth.post('', response_model=ModelConfig, status_code=201, response_model_exclude_unset=True)
async def create_model(body: ModelConfig):
    """Add a new model configuration."""
    if _find_model(body.provider, body.id) is not None:
        raise HTTPException(status_code=409, detail=f'Model config already exists: {body.provider}/{body.id}')
    settings.model_configs.append(body)
    await persist_settings()
    return body.model_dump(exclude=SENSITIVE_FIELDS)


@auth.put('/{provider}/{model_id:path}', response_model=ModelConfig, response_model_exclude_unset=True)
async def update_model(provider: str, model_id: str, body: ModelUpdate):
    """Update an existing model configuration by provider and id (case-insensitive)."""
    cfg = _find_model(provider, model_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f'Model config not found: {provider}/{model_id}')
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(cfg, field, value)
    await persist_settings()
    return cfg.model_dump(exclude=SENSITIVE_FIELDS)


@auth.delete('/{provider}/{model_id:path}', status_code=204)
async def delete_model(provider: str, model_id: str):
    """Remove a model configuration by provider and id (case-insensitive)."""
    for i, cfg in enumerate(settings.model_configs):
        if cfg.provider.lower() == provider.lower() and cfg.id.lower() == model_id.lower():
            settings.model_configs.pop(i)
            await persist_settings()
            return None
    raise HTTPException(status_code=404, detail=f'Model config not found: {provider}/{model_id}')
