"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai

from fastapi import APIRouter, HTTPException

import server.api.utils.databases as utils_databases

from common import schema
from common import logging_config

logger = logging_config.logging.getLogger("endpoints.v1.databases")

# Validate the DEFAULT Databases
try:
    _ = utils_databases.get_databases(db_name="DEFAULT", validate=True)
except Exception:
    pass

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
        database_objects = utils_databases.get_databases(validate=False)
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
        # Validate when looking at a single database
        db = utils_databases.get_databases(db_name=name, validate=True)
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
        db = utils_databases.get_databases(db_name=name, validate=False)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=f"Database: {str(ex)}.") from ex

    db.connected = False
    try:
        payload.config_dir = db.config_dir
        payload.wallet_location = db.wallet_location
        logger.debug("Testing Payload: %s", payload)
        db_conn = utils_databases.connect(payload)
    except (ValueError, PermissionError, ConnectionError, LookupError) as ex:
        status_code = 500
        if isinstance(ex, ValueError):
            status_code = 400
        elif isinstance(ex, PermissionError):
            status_code = 401
        elif isinstance(ex, LookupError):
            status_code = 404
        elif isinstance(ex, ConnectionError):
            status_code = 503
        else:
            raise
        raise HTTPException(status_code=status_code, detail=f"Database: {db.name} {ex}.") from ex
    for key, value in payload.model_dump().items():
        setattr(db, key, value)

    # Manage Connections; Unset and disconnect other databases
    db.connected = True
    db.set_connection(db_conn)
    database_objects = utils_databases.get_databases()
    for other_db in database_objects:
        if other_db.name != name and other_db.connection:
            other_db.set_connection(utils_databases.disconnect(db.connection))
            other_db.connected = False

    return db
