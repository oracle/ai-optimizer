"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai clob nclob

from typing import Optional, Union

from server.api.core import bootstrap, settings
from server.api.util import databases, embed, selectai

import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.core.database")


def get_databases(
    name: Optional[schema.DatabaseNameType] = None,
    validate: bool = True
) -> Union[list[schema.Database], schema.Database, None]:
    """
    Return all Database objects if `name` is not provided,
    or the single Database if `name` is provided and successfully connected.
    If a `name` is provided and not found, raise exception
    """
    database_objects = bootstrap.DATABASE_OBJECTS

    for db in database_objects:      
        if name and db.name != name:
            continue
        if validate:
            try:
                db_conn = databases.connect(db)
                db.vector_stores = embed.get_vs(db_conn)
                db.selectai = selectai.enabled(db_conn)
                if db.selectai:
                    db.selectai_profiles = selectai.get_profiles(db_conn)
            except databases.DbException as ex:
                logger.debug("Skipping Database %s - exception: %s", db.name, str(ex))
                db.connected = False
        if name:
            return db  # Return the matched, connected DB immediately

    if name:
        # If we got here with a `name` then we didn't find it
        raise ValueError(f"{name} not found")

    return database_objects


def get_client_db(client: schema.ClientIdType) -> schema.Database:
    """Return a Database Object based on client settings"""
    client_settings = settings.get_client_settings(client)

    # Get database name from client settings, defaulting to "DEFAULT"
    db_name = "DEFAULT"
    if (hasattr(client_settings, "vector_search") and client_settings.vector_search) or (
        hasattr(client_settings, "selectai") and client_settings.selectai
    ):
        db_name = getattr(client_settings.vector_search, "database", "DEFAULT")

    # Return the Database Object
    db = get_databases(db_name)
    # Ping the Database
    databases.test(db)

    return db
