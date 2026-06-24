"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Oracle Deep Data Security endpoints — manage data roles, end users, and
data grants on the client's selected database. Operates only on the user's database;
it never touches the internal aio_* CORE tables.
"""
# spell-checker:ignore deepsec oracledb

import logging
from typing import Annotated, Awaitable, Callable

import oracledb
from fastapi import APIRouter, Header, HTTPException

from server.app.api.v1.endpoints.databases import register_database
from server.app.api.v1.schemas.chat import MessageResponse
from server.app.api.v1.schemas.common import ClientId
from server.app.api.v1.schemas.deepsec import (
    ConnectAsRequest,
    ConnectAsResponse,
    DataGrant,
    DataGrantCreate,
    DataRole,
    DataRoleCreate,
    DataRoleGrant,
    DataRoleGrantCreate,
    DeepSecStatus,
    EndUser,
    EndUserCreate,
    SchemaObject,
)
from server.app.core.secrets import reveal
from server.app.core.settings import _settings_lock, resolve_client
from server.app.database.config import (
    _find_config_ci,
    clear_dds_for,
    get_client_db_config,
    get_client_pool,
    managed_marker,
)
from server.app.database.schemas import DatabaseConfig
from server.app.deepsec import database as deepsec_db
from server.app.deepsec.database import DeepSecError
from server.app.mcp.proxies.sqlcl import refresh_sqlcl_proxy

LOGGER = logging.getLogger("server.api.v1.deepsec")

auth = APIRouter(prefix="/deepsec")


def _translate(exc: Exception) -> HTTPException:
    """Map domain/database errors to HTTP responses with a useful detail."""
    if isinstance(exc, DeepSecError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, oracledb.DatabaseError):
        message = str(exc.args[0]).strip().splitlines()[0] if exc.args else str(exc)
        return HTTPException(status_code=400, detail=message)
    LOGGER.error("Deep Data Security endpoint error: %s", exc)
    return HTTPException(status_code=500, detail="Deep Data Security: an unexpected error occurred.")


async def _run(client: str, op: Callable[[oracledb.AsyncConnection], Awaitable]):
    """Acquire the client's pool, run *op* with a connection, and translate errors."""
    pool = get_client_pool(client)
    if pool is None:
        alias = resolve_client(client).database.alias
        raise HTTPException(status_code=503, detail=f"Database is not available: {alias}")
    try:
        async with pool.acquire() as conn:
            return await op(conn)
    except (DeepSecError, oracledb.DatabaseError) as exc:
        raise _translate(exc) from exc


# ---------------------------------------------------------------------------
# Status / objects
# ---------------------------------------------------------------------------


@auth.get("/status", response_model=DeepSecStatus)
async def deepsec_status(client: Annotated[ClientId, Header()] = "server") -> DeepSecStatus:
    """Report Deep Data Security availability and the user's capability matrix."""
    return DeepSecStatus.model_validate(await _run(client, deepsec_db.get_status))


@auth.get("/objects", response_model=list[SchemaObject])
async def deepsec_objects(client: Annotated[ClientId, Header()] = "server") -> list[SchemaObject]:
    """List the user's tables/views that a data grant can target."""
    return [SchemaObject.model_validate(o) for o in await _run(client, deepsec_db.list_objects)]


@auth.get("/objects/{object_name}/columns", response_model=list[str])
async def deepsec_object_columns(
    object_name: str, client: Annotated[ClientId, Header()] = "server"
) -> list[str]:
    """List columns for one of the user's tables/views."""
    return await _run(client, lambda conn: deepsec_db.list_object_columns(conn, object_name))


# ---------------------------------------------------------------------------
# Data roles
# ---------------------------------------------------------------------------


@auth.get("/data-roles", response_model=list[DataRole])
async def list_data_roles(client: Annotated[ClientId, Header()] = "server") -> list[DataRole]:
    return [DataRole.model_validate(r) for r in await _run(client, deepsec_db.list_data_roles)]


@auth.post("/data-roles", response_model=MessageResponse)
async def create_data_role(
    body: DataRoleCreate, client: Annotated[ClientId, Header()] = "server"
) -> MessageResponse:
    await _run(client, lambda conn: deepsec_db.create_data_role(conn, body.name, body.mapped_to))
    return MessageResponse(message=f"Data role created: {body.name}")


@auth.delete("/data-roles/{name}", response_model=MessageResponse)
async def drop_data_role(name: str, client: Annotated[ClientId, Header()] = "server") -> MessageResponse:
    await _run(client, lambda conn: deepsec_db.drop_data_role(conn, name))
    return MessageResponse(message=f"Data role dropped: {name}")


# ---------------------------------------------------------------------------
# End users
# ---------------------------------------------------------------------------


@auth.get("/end-users", response_model=list[EndUser])
async def list_end_users(client: Annotated[ClientId, Header()] = "server") -> list[EndUser]:
    return [EndUser.model_validate(u) for u in await _run(client, deepsec_db.list_end_users)]


@auth.post("/end-users", response_model=MessageResponse)
async def create_end_user(
    body: EndUserCreate, client: Annotated[ClientId, Header()] = "server"
) -> MessageResponse:
    # End users are provisioned with the same password as the connected database user.
    db_config = get_client_db_config(client)
    password = reveal(db_config.password) if db_config else None
    if not password:
        raise HTTPException(status_code=400, detail="Database user password is not available")
    await _run(client, lambda conn: deepsec_db.create_end_user(conn, body.name, password, body.schema_name))
    return MessageResponse(message=f"End user created: {body.name}")


@auth.delete("/end-users/{name}", response_model=MessageResponse)
async def drop_end_user(name: str, client: Annotated[ClientId, Header()] = "server") -> MessageResponse:
    await _run(client, lambda conn: deepsec_db.drop_end_user(conn, name))
    # Tear down the connect-as connection for this end user ON THE CURRENT BASE only —
    # end users are per-database accounts, so a same-named user on another base is a distinct
    # account and its managed connection must survive.
    base_alias = resolve_client(client).database.alias
    async with _settings_lock:
        removed = await clear_dds_for(alias=_managed_alias(base_alias, name))
    if removed:
        await refresh_sqlcl_proxy()
    return MessageResponse(message=f"End user dropped: {name}")


# ---------------------------------------------------------------------------
# Connect-as (chat tools connect as a DDS end user; runtime/session-scoped)
# ---------------------------------------------------------------------------


def _managed_alias(base_alias: str, end_user: str) -> str:
    """Deterministic, canonical-cased alias for a DDS-managed connect-as connection."""
    return f"{base_alias}::{end_user}".upper()


@auth.post("/connect-as", response_model=ConnectAsResponse)
async def dds_connect_as(
    body: ConnectAsRequest, client: Annotated[ClientId, Header()] = "server"
) -> ConnectAsResponse:
    """Register a runtime-only managed connection authenticating as a DDS end user.

    The connection copies the owner's password/dsn/wallet (DDS end users share the owner's
    password) and gets a pool + SQLcl store so chat-time read tools can use it when the
    sidebar toggle is on. Nothing is persisted. Registration is strict: a failed end-user
    login registers nothing and returns 400.
    """
    base = get_client_db_config(client)
    if base is None:
        alias = resolve_client(client).database.alias
        raise HTTPException(status_code=503, detail=f"Database is not available: {alias}")
    managed = _managed_alias(base.alias, body.end_user)
    error: str | None = None
    result: ConnectAsResponse | None = None
    # Refresh SQLcl whenever the store changed — i.e. stale state was removed and/or a new
    # connection was registered. Critically this includes the stale-removed-then-failed path,
    # so the store never keeps advertising a removed alias. The refresh runs outside the lock.
    need_refresh = False
    async with _settings_lock:
        existing = _find_config_ci(managed)
        if existing is not None and existing.usable and existing.pool:
            result = ConnectAsResponse(alias=existing.alias, base_alias=base.alias, end_user=body.end_user)
        else:
            if existing is not None:
                # Stale/unusable — tear it down AND clear any DDS setting referencing it, so the
                # "managed connection exists iff a live setting references it" invariant holds even
                # if re-registration below fails. (On success the client re-sets its selection.)
                await clear_dds_for(alias=managed)
                need_refresh = True  # the store still has this alias until we rebuild
            cfg = DatabaseConfig(
                alias=managed,
                username=body.end_user,
                password=base.password,
                dsn=base.dsn,
                wallet_location=base.wallet_location,
                config_dir=base.config_dir,
                wallet_password=base.wallet_password,
                tcp_connect_timeout=base.tcp_connect_timeout,
            )
            error = await register_database(
                cfg, require_usable=True, persist=False, managed_by=managed_marker(base.alias)
            )
            if not error:
                need_refresh = True
                result = ConnectAsResponse(alias=cfg.alias, base_alias=base.alias, end_user=body.end_user)
    if need_refresh:
        await refresh_sqlcl_proxy()
    if error:
        raise HTTPException(status_code=400, detail=error)
    return result  # type: ignore[return-value]  # set whenever error is None


@auth.delete("/connect-as", response_model=MessageResponse)
async def dds_clear_connect_as(client: Annotated[ClientId, Header()] = "server") -> MessageResponse:
    """Tear down this client's connect-as managed connection and clear its DDS setting.

    Scoped to the client's exact managed alias — clearing one end user's connection must not
    remove a same-named end user's connection on a different base (``clear_dds_for`` matches
    its criteria with OR semantics, so only ``alias`` is passed here).
    """
    dds = resolve_client(client).deep_data_security
    async with _settings_lock:
        removed = await clear_dds_for(alias=dds.alias)
    if removed:
        await refresh_sqlcl_proxy()
    return MessageResponse(message="Deep Data Security connect-as cleared")


# ---------------------------------------------------------------------------
# Data role grants (data role -> end user membership)
# ---------------------------------------------------------------------------


@auth.get("/data-role-grants", response_model=list[DataRoleGrant])
async def list_data_role_grants(client: Annotated[ClientId, Header()] = "server") -> list[DataRoleGrant]:
    return [DataRoleGrant.model_validate(g) for g in await _run(client, deepsec_db.list_data_role_grants)]


@auth.post("/data-role-grants", response_model=MessageResponse)
async def grant_data_role(
    body: DataRoleGrantCreate, client: Annotated[ClientId, Header()] = "server"
) -> MessageResponse:
    if not body.roles:
        raise HTTPException(status_code=400, detail="At least one data role is required")
    await _run(client, lambda conn: deepsec_db.grant_data_role(conn, body.roles, body.grantee))
    return MessageResponse(message=f"Data roles granted to {body.grantee}: {', '.join(body.roles)}")


@auth.delete("/data-role-grants/{grantee}/{role}", response_model=MessageResponse)
async def revoke_data_role(
    grantee: str, role: str, client: Annotated[ClientId, Header()] = "server"
) -> MessageResponse:
    await _run(client, lambda conn: deepsec_db.revoke_data_role(conn, role, grantee))
    return MessageResponse(message=f"Data role {role} revoked from {grantee}")


# ---------------------------------------------------------------------------
# Data grants
# ---------------------------------------------------------------------------


@auth.get("/data-grants", response_model=list[DataGrant])
async def list_data_grants(client: Annotated[ClientId, Header()] = "server") -> list[DataGrant]:
    return [DataGrant.model_validate(g) for g in await _run(client, deepsec_db.list_data_grants)]


@auth.post("/data-grants", response_model=MessageResponse)
async def create_data_grant(
    body: DataGrantCreate, client: Annotated[ClientId, Header()] = "server"
) -> MessageResponse:
    await _run(
        client,
        lambda conn: deepsec_db.create_data_grant(
            conn,
            name=body.name,
            privileges=body.privileges,
            object_name=body.object_name,
            grantee=body.grantee,
            columns=body.columns,
            all_columns_except=body.all_columns_except,
            predicate=body.predicate,
            or_replace=body.or_replace,
        ),
    )
    return MessageResponse(message=f"Data grant created: {body.name}")


@auth.delete("/data-grants/{name}", response_model=MessageResponse)
async def drop_data_grant(name: str, client: Annotated[ClientId, Header()] = "server") -> MessageResponse:
    await _run(client, lambda conn: deepsec_db.drop_data_grant(conn, name))
    return MessageResponse(message=f"Data grant dropped: {name}")
