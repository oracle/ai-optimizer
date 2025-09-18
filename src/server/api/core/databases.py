"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# spell-checker:ignore clob genai nclob privs selectai
from typing import Optional, Union
from server.api.core import bootstrap

from common.schema import Database, DatabaseNameType
from common import logging_config

logger = logging_config.logging.getLogger("api.core.database")


#####################################################
# Functions
#####################################################
def get_database(name: Optional[DatabaseNameType] = None) -> Union[list[Database], None]:
    """
    Return all Database objects if `name` is not provided,
    or the single Database if `name` is provided.
    If a `name` is provided and not found, raise exception
    """
    database_objects = bootstrap.DATABASE_OBJECTS

    logger.debug("%i databases are defined", len(database_objects))
    database_filtered = [db for db in database_objects if (name is None or db.name == name)]
    logger.debug("%i databases after filtering", len(database_filtered))

    if name and not database_filtered:
        raise ValueError(f"{name} not found")

    return database_filtered


def create_database(database: Database) -> Database:
    """Create a new Model definition"""
    database_objects = bootstrap.DATABASE_OBJECTS

    _ = get_database(name=database.name)

    if any(not getattr(database_objects, key) for key in ("user", "password", "dsn")):
        raise ValueError("'user', 'password', and 'dsn' are required")

    database_objects.append(database)
    return get_database(name=database.name)


def delete_database(name: DatabaseNameType) -> None:
    """Remove database from database objects"""
    database_objects = bootstrap.DATABASE_OBJECTS
    bootstrap.DATABASE_OBJECTS = [d for d in database_objects if d.name != name]
