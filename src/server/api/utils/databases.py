"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai clob nclob vectorstores oraclevs

import oracledb
from langchain_community.vectorstores import oraclevs as LangchainVS

import server.api.core.databases as core_databases
import server.api.core.settings as core_settings

import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.utils.database")


def test(config: schema.Database) -> None:
    """Test connection and re-establish if no longer open"""
    try:
        config.connection.ping()
        logger.info("%s database connection is active.", config.name)
    except oracledb.DatabaseError:
        db_conn = core_databases.connect(config)
        logger.info("Refreshing %s database connection.", config.name)
        config.set_connection(db_conn)
    except AttributeError as ex:
        raise core_databases.DbException(status_code=400, detail="missing connection details") from ex


def drop_vs(conn: oracledb.Connection, vs: schema.VectorStoreTableType) -> None:
    """Drop Vector Storage"""
    logger.info("Dropping Vector Store: %s", vs)
    LangchainVS.drop_table_purge(conn, vs)


def get_client_db(client: schema.ClientIdType) -> schema.Database:
    """Return a Database Object based on client settings"""
    client_settings = core_settings.get_client_settings(client)

    # Get database name from client settings, defaulting to "DEFAULT"
    db_name = "DEFAULT"
    if (hasattr(client_settings, "vector_search") and client_settings.vector_search) or (
        hasattr(client_settings, "selectai") and client_settings.selectai
    ):
        db_name = getattr(client_settings.vector_search, "database", "DEFAULT")

    # Return the Database Object
    db = core_databases.get_databases(db_name)
    # Ping the Database
    test(db)

    return db
