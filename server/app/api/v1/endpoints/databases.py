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
    ActiveDatabase,
    DatabaseCreate,
    DatabaseResponse,
    DatabaseUpdate,
)
from server.app.database import (
    close_pool,
    get_active_alias,
    get_all_registered_databases,
    get_registered_database,
    initialize_schema,
    register_database,
    remove_registered_database,
    set_active_alias,
)

__all__ = ["register_database"]
from server.app.database.config import DatabaseSettings, WalletConfig
from server.app.database.settings import registry_to_persisted, save_settings

LOGGER = logging.getLogger(__name__)

auth = APIRouter(prefix="/db")


async def _persist_settings() -> None:
    """Persist is_current registry state to aio_settings."""

    default_db = get_registered_database("DEFAULT")
    if default_db is None or not default_db.usable or default_db.pool is None:
        return
    try:
        is_current = registry_to_persisted(get_all_registered_databases(), get_active_alias())
        await save_settings(default_db.pool, is_current)
    except oracledb.Error:
        LOGGER.warning("Failed to persist database settings")


def _to_response(state) -> DatabaseResponse:
    """Map internal DatabaseState to the public response model."""

    return DatabaseResponse(
        alias=state.alias,
        username=state.settings.username,
        dsn=state.settings.dsn,
        wallet_location=state.settings.wallet.location,
        has_credentials=state.settings.has_credentials(),
        usable=state.usable,
    )


# --- Active database endpoints (before /{alias} to avoid path conflicts) ---


@auth.get("/active", response_model=ActiveDatabase)
async def get_active_database():
    """Return the is_current alias."""

    return ActiveDatabase(alias=get_active_alias())


@auth.put("/active", response_model=ActiveDatabase)
async def set_active_database(body: ActiveDatabase):
    """Switch the active database alias."""

    if get_registered_database(body.alias) is None:
        raise HTTPException(status_code=404, detail=f"Alias '{body.alias}' not found")
    set_active_alias(body.alias)
    await _persist_settings()
    return ActiveDatabase(alias=get_active_alias())


# --- CRUD endpoints ---


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
        wallet=WalletConfig(
            password=body.wallet_password,
            location=body.wallet_location,
        ),
        config_dir=body.config_dir,
        tcp_connect_timeout=body.tcp_connect_timeout or 10,
    )

    pool = None
    try:
        pool = await initialize_schema(new_settings)
    except (oracledb.Error, ValueError):
        pass

    state = get_registered_database(body.alias)
    if state is not None and not state.usable:
        await close_pool(pool)
        raise HTTPException(
            status_code=422,
            detail=f"Configuration saved but connectivity test failed for alias '{body.alias}'",
        )

    # Close the validation pool — runtime pool management is separate
    await close_pool(pool)
    if pool is not None and state is not None:
        state.pool = None

    await _persist_settings()
    return _to_response(state)


@auth.get("/{alias}", response_model=DatabaseResponse)
async def get_database(alias: str):
    """Get configuration for a single database alias."""

    db = get_registered_database(alias)
    if db is None:
        raise HTTPException(status_code=404, detail=f"Alias '{alias}' not found")
    return _to_response(db)


def _build_updated_settings(state, body: DatabaseUpdate) -> DatabaseSettings:
    """Merge request body into existing settings, returning a new DatabaseSettings."""

    updates = body.model_dump(exclude_unset=True)
    wallet_updates = {}
    if "wallet_password" in updates:
        wallet_updates["password"] = updates.pop("wallet_password")
    if "wallet_location" in updates:
        wallet_updates["location"] = updates.pop("wallet_location")
    if wallet_updates:
        updates["wallet"] = dataclasses.replace(state.settings.wallet, **wallet_updates)

    return dataclasses.replace(state.settings, **updates)


@auth.put("/{alias}", response_model=DatabaseResponse)
async def update_database(alias: str, body: DatabaseUpdate):
    """Update an existing database alias configuration."""

    state = get_registered_database(alias)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Alias '{alias}' not found")

    was_usable = state.usable
    old_pool = state.pool
    old_settings = state.settings

    new_settings = _build_updated_settings(state, body)

    # Reset state for re-validation
    state.usable = False
    state.pool = None

    pool = None
    try:
        pool = await initialize_schema(new_settings)
    except (oracledb.Error, ValueError):
        pass

    if not state.usable:
        # Close pool from failed attempt
        await close_pool(pool)

        if was_usable:
            # Reject: restore old settings
            state.settings = old_settings
            state.usable = was_usable
            state.pool = old_pool
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
    await close_pool(old_pool)

    # Non-DEFAULT aliases close the validation pool; their runtime pools
    # are established later.  DEFAULT keeps it for persistence.
    if alias == "DEFAULT":
        state.pool = pool
    else:
        await close_pool(pool)
        if pool is not None:
            state.pool = None

    await _persist_settings()
    return _to_response(state)


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

    # If the deleted alias was the active one, reset to DEFAULT
    if get_active_alias() == alias:
        set_active_alias("DEFAULT")

    await _persist_settings()
