"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for retrieving database configurations.
"""

from fastapi import APIRouter, HTTPException, Query

from server.app.database import init_core_database
from server.app.database.config import close_pool
from server.app.database.schemas import DatabaseConfig, DatabaseSensitive, DatabaseUpdate
from server.app.database.settings import persist_settings
from server.app.core.settings import settings

auth = APIRouter(prefix='/databases')

SENSITIVE_FIELDS = set(DatabaseSensitive.model_fields.keys())


@auth.get('', response_model=list[DatabaseConfig], response_model_exclude_unset=True)
async def list_databases(include_sensitive: bool = Query(default=False)):
    """Return all database configurations."""
    exclude = None if include_sensitive else SENSITIVE_FIELDS
    return [cfg.model_dump(exclude=exclude) for cfg in settings.database_configs]


@auth.get('/{alias}', response_model=DatabaseConfig, response_model_exclude_unset=True)
async def get_database(alias: str, include_sensitive: bool = Query(default=False)):
    """Return a single database configuration by alias (case-insensitive)."""
    for cfg in settings.database_configs:
        if cfg.alias.lower() == alias.lower():
            exclude = None if include_sensitive else SENSITIVE_FIELDS
            return cfg.model_dump(exclude=exclude)
    raise HTTPException(status_code=404, detail=f'Database config not found: {alias}')


@auth.post('', response_model=DatabaseConfig, status_code=201, response_model_exclude_unset=True)
async def create_database(body: DatabaseConfig):
    """Add a new database configuration."""
    for cfg in settings.database_configs:
        if cfg.alias.lower() == body.alias.lower():
            raise HTTPException(status_code=409, detail=f'Database config already exists: {body.alias}')
    settings.database_configs.append(body)
    await persist_settings()
    return body.model_dump(exclude=SENSITIVE_FIELDS)


@auth.put('/{alias}', response_model=DatabaseConfig, response_model_exclude_unset=True)
async def update_database(alias: str, body: DatabaseUpdate):
    """Update an existing database configuration by alias (case-insensitive)."""
    for cfg in settings.database_configs:
        if cfg.alias.lower() == alias.lower():
            updates = body.model_dump(exclude_unset=True)
            for field, value in updates.items():
                setattr(cfg, field, value)
            # Re-initialise the CORE database when its config changes
            if cfg.alias == 'CORE':
                await close_pool(cfg.pool)
                cfg.usable = False
                await init_core_database(cfg)
            await persist_settings()
            return cfg.model_dump(exclude=SENSITIVE_FIELDS)
    raise HTTPException(status_code=404, detail=f'Database config not found: {alias}')


@auth.delete('/{alias}', status_code=204)
async def delete_database(alias: str):
    """Remove a database configuration by alias (case-insensitive)."""
    if alias.upper() == 'CORE':
        raise HTTPException(status_code=403, detail='Cannot delete the CORE database')
    for i, cfg in enumerate(settings.database_configs):
        if cfg.alias.lower() == alias.lower():
            await close_pool(cfg.pool)
            settings.database_configs.pop(i)
            await persist_settings()
            return None
    raise HTTPException(status_code=404, detail=f'Database config not found: {alias}')
