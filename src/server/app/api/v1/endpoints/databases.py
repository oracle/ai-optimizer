"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Endpoints for retrieving database configurations.
"""

import asyncio
import logging
from typing import Awaitable, Callable

import oracledb
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from server.app.api.v1.endpoints._helpers import _build_updates, _log_sensitive_read
from server.app.core.error_detail import response_error_detail
from server.app.core.secrets import REVEAL_KEY
from server.app.core.settings import _settings_lock, settings
from server.app.database.config import (
    MANAGED_CONNECTION_FIELDS,
    _find_config_ci,
    clear_dds_for,
    close_pool,
    get_core_pool,
)
from server.app.database.registry import (
    drop_vector_store,
    init_core_database,
    refresh_db_vector_stores,
    test_connection,
)
from server.app.database.schemas import DatabaseConfig, DatabaseSensitive, DatabaseUpdate
from server.app.database.settings import persist_settings
from server.app.embed.jobs import count_active_embed_jobs, count_active_embed_jobs_for_alias
from server.app.mcp.proxies.sqlcl import refresh_sqlcl_proxy

LOGGER = logging.getLogger(__name__)

auth = APIRouter(prefix="/databases")

SENSITIVE_FIELDS = set(DatabaseSensitive.model_fields.keys())
# Fields where a blank submission means "preserve existing"; narrower than
# ``SENSITIVE_FIELDS`` because non-credential response-masked fields (none
# in this schema today) should not be preserved-on-blank.
SECRET_UPDATE_FIELDS = frozenset({"password", "wallet_password"})

_PERSIST_FAIL = "Failed to persist settings"


def _sqlcl_relevant(cfg: DatabaseConfig) -> bool:
    """Whether *cfg* has the credentials SQLcl needs to store a connection."""
    return bool(cfg.username and cfg.password and cfg.dsn)


async def _refuse_if_active_embed_jobs(
    *,
    counter: Callable[[], Awaitable[int]],
    log_context: str,
    refuse_detail: Callable[[int], str],
) -> None:
    """Shared shape for both rotation guards: count, fail-open on a
    flaky check, raise 409 if any job is still live.

    Fail-open posture is intentional — the rotation may itself be
    the fix for a broken CORE, so failing closed would make a busted
    pool unrepairable through this endpoint. ``TimeoutError`` is the
    built-in raised by ``oracledb`` async pools on acquire / SELECT
    deadlines and doesn't inherit from ``oracledb.Error``, so the
    catch tuple lists both shapes.
    """
    try:
        active = await counter()
    except (oracledb.Error, TimeoutError) as ex:
        LOGGER.warning(
            "Could not count active embed jobs before %s; proceeding: %s",
            log_context,
            ex,
        )
        return
    if active > 0:
        raise HTTPException(status_code=409, detail=refuse_detail(active))


async def _refuse_core_rotation_if_active_embed_jobs(cfg: DatabaseConfig) -> None:
    """Refuse a CORE rotation while embed jobs are still in flight.

    The pipeline pins the current CORE pool to each active job;
    rotating closes that pool and strands the pin. Block until all
    unexpired rows drain.
    """
    if cfg.pool is None:
        return
    pool = cfg.pool
    await _refuse_if_active_embed_jobs(
        counter=lambda: count_active_embed_jobs(pool),
        log_context="CORE rotation",
        refuse_detail=lambda n: (
            f"Cannot update CORE while {n} embed job(s) "
            f"are still queued / running. Wait for them to "
            f"finish or cancel them, then retry."
        ),
    )


async def _refuse_alias_change_if_targeted_by_active_embed_jobs(
    alias: str, action: str
) -> None:
    """Refuse PUT / DELETE on *alias* while embed jobs target it.

    Pipeline holds the alias's pool through the post-``populate_vs``
    discovery step; rotating or removing closes that pool mid-flight.
    *action* is the verb (``"update"``/``"remove"``) interpolated
    into the 409 detail.
    """
    core_pool = get_core_pool()
    if core_pool is None:
        return
    await _refuse_if_active_embed_jobs(
        counter=lambda: count_active_embed_jobs_for_alias(core_pool, alias),
        log_context=f"{action} of database '{alias}'",
        refuse_detail=lambda n: (
            f"Cannot {action} database '{alias}' while "
            f"{n} embed job(s) targeting it are still "
            f"queued / running. Wait for them to finish or "
            f"cancel them, then retry."
        ),
    )


async def _maybe_refresh_sqlcl(cfg: DatabaseConfig, originals: dict | None = None) -> None:
    """Rebuild the SQLcl proxy when the change affects its connection store.

    Skips the multi-second refresh when neither the current nor previous config
    had the credentials SQLcl would have written to its store.
    """
    if _sqlcl_relevant(cfg):
        await refresh_sqlcl_proxy()
        return
    if originals is None:
        return
    # Reconstruct the pre-update view so we notice "had creds → cleared them".
    prev_username = originals.get("username", cfg.username)
    prev_password = originals.get("password", cfg.password)
    prev_dsn = originals.get("dsn", cfg.dsn)
    if prev_username and prev_password and prev_dsn:
        await refresh_sqlcl_proxy()


def _check_username_dsn_conflict(username: str | None, dsn: str | None, exclude: DatabaseConfig | None = None) -> None:
    """Raise 409 if another config already uses this username/dsn pair."""
    if not username or not dsn:
        return
    for cfg in settings.database_configs:
        if cfg is exclude:
            continue
        if cfg.username and cfg.dsn:
            if cfg.username.lower() == username.lower() and cfg.dsn.lower() == dsn.lower():
                raise HTTPException(
                    status_code=409,
                    detail=f"A database config with this username/dsn already exists: {cfg.alias}",
                )


@auth.get("", response_model=list[DatabaseConfig], response_model_exclude_unset=True)
async def list_databases():
    """Return all database configurations.  Sensitive fields are always
    omitted from list responses.

    Reconciles ``vector_stores`` for every entry against the live
    catalog so the list stays consistent with ``GET /v1/databases/{alias}``
    and ``GET /v1/settings``.
    """
    # DDS-managed connections are runtime-only and never user-facing.
    visible = [cfg for cfg in settings.database_configs if not cfg.managed_by]
    await asyncio.gather(*(refresh_db_vector_stores(cfg) for cfg in visible))
    return [cfg.model_dump(exclude=SENSITIVE_FIELDS) for cfg in visible]


@auth.get("/{alias}", response_model=DatabaseConfig, response_model_exclude_unset=True)
async def get_database(
    alias: str,
    request: Request,
    include_sensitive: bool = Query(default=False),
):
    """Return a single database configuration by alias (case-insensitive).

    Reconciles the cached ``vector_stores`` list against the live DB so
    out-of-band ``DROP TABLE`` (or any direct catalog change) is reflected
    in the response.
    """
    # exclude_managed: DDS-managed connections are runtime-only and never user-facing — treat as
    # not found even when the (otherwise hidden) alias is known, so they can't be fetched/revealed.
    cfg = _find_config_ci(alias, exclude_managed=True)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Database config not found: {alias}")
    await refresh_db_vector_stores(cfg)
    if include_sensitive:
        _log_sensitive_read(LOGGER, "databases", cfg.alias, request)
        # Keep this path explicit so the configured serializer context is preserved.
        return JSONResponse(content=cfg.model_dump(mode="json", context={REVEAL_KEY: True}))
    return cfg.model_dump(exclude=SENSITIVE_FIELDS)


async def register_database(
    cfg: DatabaseConfig,
    *,
    require_usable: bool = False,
    persist: bool = True,
    managed_by: str | None = None,
) -> str | None:
    """Test a database config, register it, and (optionally) persist it.

    Caller must hold ``_settings_lock`` and, on success, call ``_maybe_refresh_sqlcl(cfg)``
    after releasing the lock (the SQLcl rebuild is slow and must not run under the lock).

    Returns the connection error-detail string (or ``None`` on a clean connect).

    - ``require_usable=False`` (manual path): the config is registered/persisted even when
      the connection test fails, returning the error string for the 201 body.
    - ``require_usable=True`` (DDS path): **atomic, test-before-append.** On a failed test
      nothing is registered and the error string is returned; on success the config is
      appended. Pair with ``persist=False`` for runtime-only managed connections.
    """
    if managed_by is not None:
        cfg.managed_by = managed_by

    # Test before append: test_connection / init_core_database populate cfg.pool / cfg.usable
    # on the object itself and do not need it registered first.
    error = None
    try:
        if cfg.alias == "CORE":
            await init_core_database(cfg)
        else:
            await test_connection(cfg)
    except Exception as exc:
        error = response_error_detail(exc, "Database connection failed.")

    if require_usable and error:
        # Atomic failure — nothing was appended; leave settings.database_configs untouched.
        await close_pool(cfg.pool)
        cfg.pool = None
        return error

    settings.database_configs.append(cfg)
    if persist and not await persist_settings():
        settings.database_configs.remove(cfg)
        await close_pool(cfg.pool)
        raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
    return error


@auth.post("", status_code=201, response_model_exclude_unset=True)
async def create_database(body: DatabaseConfig):
    """Add a new database configuration."""
    # managed_by marks runtime-only DDS connections and is server-owned: it is set only by
    # /deepsec/connect-as (via register_database). Reject it on this public path so a client
    # can't create an ordinary database that masquerades as managed (hidden + non-persisted).
    if body.managed_by is not None:
        raise HTTPException(status_code=422, detail="managed_by is server-owned and cannot be set")
    async with _settings_lock:
        # Normalise CORE alias to exact casing so downstream lookups match
        if body.alias.upper() == "CORE":
            body.alias = "CORE"
        core_exists = any(cfg.alias.upper() == "CORE" for cfg in settings.database_configs)
        if not core_exists and body.alias != "CORE":
            raise HTTPException(status_code=422, detail="The first database must use the alias 'CORE'")
        for cfg in settings.database_configs:
            if cfg.alias.lower() == body.alias.lower():
                raise HTTPException(status_code=409, detail=f"Database config already exists: {body.alias}")
        _check_username_dsn_conflict(body.username, body.dsn)
        error = await register_database(body)
        result = body.model_dump(exclude=SENSITIVE_FIELDS)
        if error:
            result["error"] = error
    await _maybe_refresh_sqlcl(body)
    return JSONResponse(content=result, status_code=201)


@auth.put("/{alias}", response_model_exclude_unset=True)
async def update_database(alias: str, body: DatabaseUpdate):
    """Update an existing database configuration by alias (case-insensitive).

    After applying field changes the connection is re-tested.  The outcome
    depends on whether the *current* config was working:

    1. Was working + new fails  → **reject** (422), old config maintained.
    2. Was working + new works  → accept, switch to new config.
    3. Not working + new works  → accept.
    4. Not working + new fails  → accept (200 with ``error`` field).
    """
    async with _settings_lock:
        # exclude_managed: runtime-only DDS connections are hidden — not editable via this endpoint.
        cfg = _find_config_ci(alias, exclude_managed=True)
        if cfg is None:
            raise HTTPException(status_code=404, detail=f"Database config not found: {alias}")

        if cfg.alias.upper() == "CORE":
            await _refuse_core_rotation_if_active_embed_jobs(cfg)
        else:
            await _refuse_alias_change_if_targeted_by_active_embed_jobs(cfg.alias, "update")

        updates = _build_updates(body, SECRET_UPDATE_FIELDS)
        new_username = (updates.get("username") if "username" in updates else cfg.username) or ""
        new_dsn = (updates.get("dsn") if "dsn" in updates else cfg.dsn) or ""
        _check_username_dsn_conflict(new_username.lower(), new_dsn.lower(), exclude=cfg)

        originals = {field: getattr(cfg, field) for field in updates}
        saved = (cfg.pool, cfg.usable, cfg.vector_stores[:])

        for field, value in updates.items():
            setattr(cfg, field, value)
        cfg.usable = False

        error = None
        try:
            if cfg.alias == "CORE":
                await init_core_database(cfg)
            else:
                await test_connection(cfg)
        except Exception as exc:
            error = response_error_detail(exc, "Database connection failed.")

        def _restore():
            for field, value in originals.items():
                setattr(cfg, field, value)
            cfg.pool, cfg.usable, cfg.vector_stores = saved

        # Was working + new fails → reject, restore old state entirely
        if error and saved[1]:
            _restore()
            raise HTTPException(status_code=422, detail=error)

        # Accept — persist first, then close old pool
        if not await persist_settings():
            await close_pool(cfg.pool)
            _restore()
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
        # Persistence succeeded — now safe to close old pool
        await close_pool(saved[0])
        # Only a change to a connection field the managed connection copied invalidates an active
        # DDS connect-as derived from this base; tear it down then (clear-and-disable, the user
        # re-designates). An unrelated edit (e.g. username) must not silently disable the override.
        if any(
            field in originals and originals[field] != getattr(cfg, field) for field in MANAGED_CONNECTION_FIELDS
        ):
            await clear_dds_for(base_alias=cfg.alias)

        result = cfg.model_dump(exclude=SENSITIVE_FIELDS)
        if error:
            result["error"] = error
    await _maybe_refresh_sqlcl(cfg, originals=originals)
    return result


@auth.delete("/{alias}", status_code=204)
async def remove_database(alias: str):
    """Remove a database configuration by alias (case-insensitive)."""
    async with _settings_lock:
        if alias.upper() == "CORE":
            raise HTTPException(status_code=403, detail="Cannot remove the CORE database")
        # exclude_managed: runtime-only DDS connections are torn down via /deepsec/connect-as
        # (which also clears the client setting), not this endpoint.
        cfg = _find_config_ci(alias, exclude_managed=True)
        if cfg is None:
            raise HTTPException(status_code=404, detail=f"Database config not found: {alias}")

        await _refuse_alias_change_if_targeted_by_active_embed_jobs(cfg.alias, "remove")

        idx = settings.database_configs.index(cfg)
        settings.database_configs.remove(cfg)
        if not await persist_settings():
            settings.database_configs.insert(idx, cfg)
            raise HTTPException(status_code=503, detail=_PERSIST_FAIL)
        await close_pool(cfg.pool)
        # Tear down any DDS connect-as connection derived from this base.
        await clear_dds_for(base_alias=cfg.alias)
    await refresh_sqlcl_proxy()


@auth.delete("/{alias}/vector-stores/{table_name}", status_code=204)
async def delete_vector_store(alias: str, table_name: str):
    """Drop a vector store table and remove it from the database configuration."""
    async with _settings_lock:
        # exclude_managed: runtime-only DDS connections are hidden — not addressable here.
        db_config = _find_config_ci(alias, exclude_managed=True)
        if db_config is None:
            raise HTTPException(status_code=404, detail=f"Database config not found: {alias}")

        vs_entry = next((vs for vs in db_config.vector_stores if vs.vector_store == table_name), None)
        if vs_entry is None:
            raise HTTPException(status_code=404, detail=f"Vector store not found: {table_name}")

        if db_config.pool is None:
            raise HTTPException(status_code=409, detail=f"Database is not usable: {alias}")

        async with db_config.pool.acquire() as conn:
            await drop_vector_store(conn, table_name)

        # Table is already dropped — list removal just reflects reality.
        db_config.vector_stores.remove(vs_entry)
        if not await persist_settings():
            LOGGER.warning("delete_vector_store: failed to persist after dropping %s", table_name)
        return None
