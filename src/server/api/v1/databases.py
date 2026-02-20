"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import logging
from fastapi import APIRouter, HTTPException
import oracledb

import server.api.utils.databases as utils_databases

from common import schema


LOGGER = logging.getLogger("endpoints.v1.databases")

# Validate the DEFAULT Databases
try:
    _ = utils_databases.get_databases(db_name="DEFAULT", validate=True)
except (ValueError, PermissionError, ConnectionError, LookupError, oracledb.DatabaseError):
    pass

auth = APIRouter()


@auth.get(
    "",
    description="Get all database configurations",
    response_model=list[schema.Database],
)
async def databases_list() -> list[schema.Database]:
    """List all databases"""
    LOGGER.debug("Received databases_list")
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
    LOGGER.debug("Received databases_get - name: %s", name)
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
    LOGGER.debug("Received databases_update - name: %s; payload: %s", name, payload)

    try:
        db = utils_databases.get_databases(db_name=name, validate=False)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=f"Database: {str(ex)}.") from ex

    db.connected = False
    try:
        # Create a test config with payload values to test connection
        # Only update the actual db object after successful connection
        test_config = db.model_copy(update=payload.model_dump(exclude_unset=True))
        LOGGER.debug("Testing Database: %s", test_config)
        db_conn = utils_databases.connect(test_config)
    except utils_databases.DbException as ex:
        raise HTTPException(status_code=ex.status_code, detail=ex.detail) from ex
    except (PermissionError, ConnectionError, LookupError) as ex:
        status_code = 500
        if isinstance(ex, PermissionError):
            status_code = 401
        elif isinstance(ex, LookupError):
            status_code = 404
        elif isinstance(ex, ConnectionError):
            status_code = 503
        raise HTTPException(status_code=status_code, detail=f"Database: {db.name} {ex}.") from ex

    # Connection successful - now update the actual db object
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(db, key, value)

    # Manage Connections; Unset and disconnect other databases
    db.connected = True
    db.set_connection(db_conn)
    database_objects = utils_databases.get_databases()
    for other_db in database_objects:
        if other_db.name != name and other_db.connection:
            other_db.set_connection(utils_databases.disconnect(other_db.connection))
            other_db.connected = False

    return db
