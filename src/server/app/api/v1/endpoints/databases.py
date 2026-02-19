"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for retrieving database configurations.
"""

from fastapi import APIRouter, HTTPException, Query

from server.app.core.databases import DatabaseConfig, DatabaseSensitive
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
