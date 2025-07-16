"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai

from fastapi import APIRouter, HTTPException

from server.api.core import bootstrap
from server.api.core import databases, embedding, selectai

import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("endpoints.v1.databases")

auth = APIRouter()


@auth.get("/", description="Get all database configurations", response_model=list[schema.Database])
async def databases_list() -> list[schema.Database]:
    """List all databases"""
    logger.debug("Received databases_list")
    database_objects = bootstrap.DATABASE_OBJECTS

    for db in database_objects:
        try:
            db_conn = databases.connect(db)
        except databases.DbException as ex:
            logger.debug("Skipping Database %s - exception: %s", db.name, str(ex))
            continue
        db.vector_stores = embedding.get_vs(db_conn)
        db.selectai = selectai.enabled(db_conn)
        if db.selectai:
            db.selectai_profiles = selectai.get_profiles(db_conn)
    return database_objects


@auth.get(
    "/{name}",
    description="Get single database configuration and vector storage",
    response_model=schema.Database,
)
async def databases_get(name: schema.DatabaseNameType) -> schema.Database:
    """Get single database"""
    logger.debug("Received databases_get - name: %s", name)
    database_objects = bootstrap.DATABASE_OBJECTS
    db = next((db for db in database_objects if db.name == name), None)
    if not db:
        raise HTTPException(status_code=404, detail=f"Database: {name} not found.")
    try:
        db_conn = databases.connect(db)
        db.vector_stores = embedding.get_vs(db_conn)
        db.selectai = selectai.enabled(db_conn)
        if db.selectai:
            db.selectai_profiles = selectai.get_profiles(db_conn)
    except databases.DbException as ex:
        raise HTTPException(status_code=406, detail=f"Database: {name} {str(ex)}.") from ex
    return db


@auth.patch(
    "/{name}",
    description="Update, Test, Set as default database configuration",
    response_model=schema.Database,
)
async def databases_update(name: schema.DatabaseNameType, payload: schema.DatabaseAuth) -> schema.Database:
    """Update schema.Database"""
    logger.debug("Received databases_update - name: %s; payload: %s", name, payload)
    database_objects = bootstrap.DATABASE_OBJECTS
    db = next((db for db in database_objects if db.name == name), None)
    if not db:
        raise HTTPException(status_code=404, detail=f"Database: {name} not found.")
    try:
        payload.config_dir = db.config_dir
        payload.wallet_location = db.wallet_location
        db_conn = databases.connect(payload)
    except databases.DbException as ex:
        db.connected = False
        raise HTTPException(status_code=ex.status_code, detail=f"Database: {name} {ex.detail}.") from ex
    db.user = payload.user
    db.password = payload.password
    db.dsn = payload.dsn
    db.wallet_password = payload.wallet_password
    db.connected = True
    db.set_connection(db_conn)
    # Unset and disconnect other databases
    for other_db in database_objects:
        if other_db.name != name and other_db.connection:
            other_db.set_connection(databases.disconnect(db.connection))
            other_db.connected = False
    return await databases_get(name)
