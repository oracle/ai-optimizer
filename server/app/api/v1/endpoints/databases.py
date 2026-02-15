"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

CRUD endpoints for database configuration management.
"""

import dataclasses
import logging

from fastapi import APIRouter, HTTPException

import oracledb

from server.app.api.v1.schemas.databases import (
    DatabaseCreate,
    DatabaseResponse,
    DatabaseUpdate,
)
from server.app.database import (
    close_pool,
    get_all_registered_databases,
    get_registered_database,
    initialize_schema,
    register_database,
    remove_registered_database,
)
from server.app.database.config import DatabaseSettings

LOGGER = logging.getLogger(__name__)

auth = APIRouter(prefix="/db")


def _to_response(settings: DatabaseSettings) -> DatabaseResponse:
    """Map internal DatabaseSettings to the public response model."""

    return DatabaseResponse(
        alias=settings.alias,
        username=settings.username,
        dsn=settings.dsn,
        wallet_location=settings.wallet_location,
        has_credentials=settings.has_credentials(),
        usable=settings.usable,
    )


@auth.get("", response_model=list[DatabaseResponse])
async def list_databases():
    """List all registered database configurations."""

    return [_to_response(db) for db in get_all_registered_databases()]


@auth.post("", response_model=DatabaseResponse, status_code=201)
async def create_database(body: DatabaseCreate):
    """Create a new database alias configuration."""

    if body.alias == "DEFAULT":
        raise HTTPException(status_code=409, detail="Cannot create the DEFAULT alias")

    if get_registered_database(body.alias) is not None:
        raise HTTPException(status_code=409, detail=f"Alias '{body.alias}' already exists")

    new_settings = DatabaseSettings(
        alias=body.alias,
        username=body.username,
        password=body.password,
        dsn=body.dsn,
        wallet_password=body.wallet_password,
        wallet_location=body.wallet_location,
    )

    pool = None
    try:
        pool = await initialize_schema(new_settings)
    except (oracledb.Error, ValueError):
        pass

    saved = get_registered_database(body.alias)
    if saved is not None and not saved.usable:
        await close_pool(pool)
        raise HTTPException(
            status_code=422,
            detail=f"Configuration saved but connectivity test failed for alias '{body.alias}'",
        )

    # Close the validation pool — runtime pool management is separate
    await close_pool(pool)
    if pool is not None:
        # Clear pool reference since we closed it
        if saved is not None:
            register_database(saved.with_pool(None))
            saved = get_registered_database(body.alias)

    return _to_response(saved)


@auth.get("/{alias}", response_model=DatabaseResponse)
async def get_database(alias: str):
    """Get configuration for a single database alias."""

    db = get_registered_database(alias)
    if db is None:
        raise HTTPException(status_code=404, detail=f"Alias '{alias}' not found")
    return _to_response(db)


@auth.put("/{alias}", response_model=DatabaseResponse)
async def update_database(alias: str, body: DatabaseUpdate):
    """Update an existing database alias configuration."""

    existing = get_registered_database(alias)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Alias '{alias}' not found")

    was_usable = existing.usable
    updates = body.model_dump(exclude_unset=True)
    new_settings = dataclasses.replace(existing, **updates, usable=False, pool=None)

    pool = None
    try:
        pool = await initialize_schema(new_settings)
    except (oracledb.Error, ValueError):
        pass

    saved = get_registered_database(alias)

    if saved is not None and not saved.usable:
        # Close pool from failed attempt
        await close_pool(pool)

        if was_usable:
            # Reject: restore old settings
            register_database(existing)
            raise HTTPException(
                status_code=422,
                detail=f"Connectivity test failed; existing usable configuration preserved for alias '{alias}'",
            )

        # Was already unusable — save new settings with usable=False
        raise HTTPException(
            status_code=422,
            detail=f"Configuration updated but connectivity test failed for alias '{alias}'",
        )

    # Close the old pool that was replaced by the successful update
    await close_pool(existing.pool)

    # Success — close validation pool and clear reference
    await close_pool(pool)
    if pool is not None and saved is not None:
        register_database(saved.with_pool(None))
        saved = get_registered_database(alias)

    return _to_response(saved)


@auth.delete("/{alias}", status_code=204)
async def delete_database(alias: str):
    """Remove a database alias configuration."""

    if alias == "DEFAULT":
        raise HTTPException(status_code=403, detail="Cannot delete the DEFAULT alias")

    db = get_registered_database(alias)
    if not remove_registered_database(alias):
        raise HTTPException(status_code=404, detail=f"Alias '{alias}' not found")
    if db is not None:
        await close_pool(db.pool)
