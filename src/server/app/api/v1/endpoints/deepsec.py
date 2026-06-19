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

from server.app.api.v1.schemas.chat import MessageResponse
from server.app.api.v1.schemas.common import ClientId
from server.app.api.v1.schemas.deepsec import (
    DataGrant,
    DataGrantCreate,
    DataRole,
    DataRoleCreate,
    DeepSecStatus,
    EndUser,
    EndUserCreate,
    SchemaObject,
)
from server.app.core.secrets import reveal
from server.app.core.settings import resolve_client
from server.app.database.config import get_client_pool
from server.app.deepsec import database as deepsec_db
from server.app.deepsec.database import DeepSecError

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
    password = reveal(body.password)
    if not password:
        raise HTTPException(status_code=400, detail="Password is required")
    await _run(client, lambda conn: deepsec_db.create_end_user(conn, body.name, password))
    return MessageResponse(message=f"End user created: {body.name}")


@auth.delete("/end-users/{name}", response_model=MessageResponse)
async def drop_end_user(name: str, client: Annotated[ClientId, Header()] = "server") -> MessageResponse:
    await _run(client, lambda conn: deepsec_db.drop_end_user(conn, name))
    return MessageResponse(message=f"End user dropped: {name}")


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
