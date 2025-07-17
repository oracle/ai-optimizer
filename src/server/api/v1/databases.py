"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai

from fastapi import APIRouter, HTTPException

import server.api.utils.databases as util_databases
import server.api.core.databases as core_databases

import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("endpoints.v1.databases")

auth = APIRouter()


@auth.get(
    "",
    description="Get all database configurations",
    response_model=list[schema.Database],
)
async def databases_list() -> list[schema.Database]:
    """List all databases"""
    logger.debug("Received databases_list")
    try:
        database_objects = core_databases.get_databases()
    except ValueError as ex:
        # This is a problem, there should always be a "DEFAULT" database even if not configured
        raise HTTPException(status_code=404, detail=f"Database: {str(ex)}.") from ex

    return database_objects


@auth.get(
    "/{name}",
    description="Get single database configuration and vector storage",
    response_model=schema.Database,
)
async def databases_get(name: schema.DatabaseNameType) -> schema.Database:
    """Get single database"""
    logger.debug("Received databases_get - name: %s", name)
    try:
        db = core_databases.get_databases(name)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=f"Database: {str(ex)}.") from ex

    return db


@auth.patch(
    "/{name}",
    description="Update, Test, Set as default database configuration",
    response_model=schema.Database,
)
async def databases_update(
    name: schema.DatabaseNameType,
    payload: schema.DatabaseAuth,
) -> schema.Database:
    """Update Database"""
    logger.debug("Received databases_update - name: %s; payload: %s", name, payload)

    try:
        db = core_databases.get_databases(name)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=f"Database: {str(ex)}.") from ex

    try:
        payload.config_dir = db.config_dir
        payload.wallet_location = db.wallet_location
        logger.debug("Testing Payload: %s", payload)
        db_conn = util_databases.connect(payload)
    except util_databases.DbException as ex:
        db.connected = False
        raise HTTPException(status_code=ex.status_code, detail=f"Database: {name} {ex.detail}.") from ex
    db.user = payload.user
    db.password = payload.password
    db.dsn = payload.dsn
    db.wallet_password = payload.wallet_password
    db.connected = True
    db.set_connection(db_conn)

    # Unset and disconnect other databases
    database_objects = core_databases.get_databases(validate=False)
    for other_db in database_objects:
        if other_db.name != name and other_db.connection:
            other_db.set_connection(util_databases.disconnect(db.connection))
            other_db.connected = False

    return db
