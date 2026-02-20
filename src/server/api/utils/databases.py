"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore clob nclob vectorstores oraclevs genai privs

import logging
from typing import Optional, Union
import json
import oracledb
from langchain_community.vectorstores import oraclevs as LangchainVS

import server.api.utils.settings as utils_settings
from server.bootstrap.bootstrap import DATABASE_OBJECTS

from common.schema import (
    Database,
    DatabaseNameType,
    VectorStoreTableType,
    ClientIdType,
    DatabaseAuth,
    DatabaseVectorStorage,
)


LOGGER = logging.getLogger("api.utils.database")


#####################################################
# Exceptions
#####################################################
class DbException(Exception):
    """Custom Database Exceptions to be passed to HTTPException"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class ExistsDatabaseError(ValueError):
    """Raised when the database already exist."""


class UnknownDatabaseError(ValueError):
    """Raised when the database doesn't exist."""


#####################################################
# CRUD Functions
#####################################################
def create(database: Database) -> Database:
    """Create a new Database definition"""

    try:
        _ = get(name=database.name)
        raise ExistsDatabaseError(f"Database: {database.name} already exists")
    except UnknownDatabaseError:
        pass

    if any(not getattr(database, key) for key in ("user", "password", "dsn")):
        raise ValueError("'user', 'password', and 'dsn' are required")

    DATABASE_OBJECTS.append(database)
    return get(name=database.name)


def get(name: Optional[DatabaseNameType] = None) -> Union[list[Database], None]:
    """
    Return all Database objects if `name` is not provided,
    or the single Database if `name` is provided.
    If a `name` is provided and not found, raise exception
    """
    database_objects = DATABASE_OBJECTS

    LOGGER.debug("%i databases are defined", len(database_objects))
    database_filtered = [db for db in database_objects if (name is None or db.name == name)]
    LOGGER.debug("%i databases after filtering", len(database_filtered))

    if name and not database_filtered:
        raise UnknownDatabaseError(f"{name} not found")

    return database_filtered


def delete(name: DatabaseNameType) -> None:
    """Remove database from database objects"""
    DATABASE_OBJECTS[:] = [d for d in DATABASE_OBJECTS if d.name != name]


#####################################################
# Protected Functions
#####################################################
def _test(config: Database) -> None:
    """Test connection and re-establish if no longer open"""
    config.connected = False
    try:
        config.connection.ping()
        LOGGER.info("%s database connection is active.", config.name)
        config.connected = True
    except oracledb.DatabaseError:
        LOGGER.info("Refreshing %s database connection.", config.name)
        _ = connect(config)
    except DbException:
        raise
    except PermissionError as ex:
        raise DbException(status_code=401, detail=f"Database: {str(ex)}") from ex
    except ConnectionError as ex:
        raise DbException(status_code=503, detail=f"Database: {str(ex)}") from ex
    except ValueError as ex:
        raise DbException(status_code=400, detail=f"Database: {str(ex)}") from ex
    except Exception as ex:
        raise DbException(status_code=500, detail=str(ex)) from ex


def _get_vs(conn: oracledb.Connection) -> DatabaseVectorStorage:
    """Retrieve Vector Storage Tables"""
    LOGGER.info("Looking for Vector Storage Tables")
    vector_stores = []
    sql = """SELECT ut.table_name,
                    REPLACE(utc.comments, 'GENAI: ', '') AS comments
                FROM all_tab_comments utc, all_tables ut
                WHERE utc.table_name = ut.table_name
                AND utc.comments LIKE 'GENAI:%'"""
    results = execute_sql(conn, sql)
    for table_name, comments in results:
        comments_dict = json.loads(comments)
        vector_stores.append(DatabaseVectorStorage(vector_store=table_name, **comments_dict))
    LOGGER.debug("Found Vector Stores: %s", vector_stores)

    return vector_stores


#####################################################
# Functions
#####################################################
def connect(config: Database) -> oracledb.Connection:
    """Establish a connection to an Oracle Database"""
    include_fields = set(DatabaseAuth.model_fields.keys())
    db_authn = config.model_dump(include=include_fields)
    if any(not db_authn[key] for key in ("user", "password", "dsn")):
        raise DbException(status_code=400, detail=f"Database: {config.name} missing connection details.")

    LOGGER.info("Connecting to Database: %s", config.dsn)
    # If a wallet password is provided but no wallet location is set
    # default the wallet location to the config directory
    if db_authn.get("wallet_password") and not db_authn.get("wallet_location"):
        db_authn["wallet_location"] = db_authn["config_dir"]

    # Attempt to Connect
    LOGGER.debug("Database AuthN: %s", db_authn)
    try:
        LOGGER.debug("Attempting Database Connection...")
        conn = oracledb.connect(**db_authn)
    except oracledb.DatabaseError as ex:
        error = ex.args[0] if ex.args else None
        code = getattr(error, "full_code", None)
        mapping = {
            "ORA-28009": PermissionError,
            "ORA-01017": PermissionError,
            "DPY-6005": ConnectionError,
            "DPY-4000": LookupError,
            "DPY-4026": LookupError,
        }
        if code in mapping:
            # Custom message for ORA-28009
            if code == "ORA-28009":
                username = db_authn.get("user", "unknown")
                raise mapping[code](f"Connecting as {username} is not permitted") from ex
            raise mapping[code](f"- {error.message}") from ex
        # If not recognized, re-raise untouched
        raise
    except OSError as ex:
        raise ConnectionError(f"Error connecting to database: {ex}") from ex

    LOGGER.debug("Connected to Databases: %s", config.dsn)

    return conn


def disconnect(conn: oracledb.Connection) -> None:
    """Disconnect from an Oracle Database"""
    LOGGER.debug("Disconnecting Databases Connection: %s", conn)
    return conn.close()


def execute_sql(conn: oracledb.Connection, run_sql: str, binds: dict = None) -> list:
    """Execute SQL against Oracle Database"""
    LOGGER.debug("SQL: %s with binds %s", run_sql, binds)
    try:
        # Use context manager to ensure the cursor is closed properly
        with conn.cursor() as cursor:
            rows = None
            cursor.callproc("dbms_output.enable")
            status_var = cursor.var(int)
            text_var = cursor.var(str)
            cursor.execute(run_sql, binds)
            if cursor.description:  # Check if the query produces rows
                rows = cursor.fetchall()
                lob_columns = [
                    idx
                    for idx, fetch_info in enumerate(cursor.description)
                    if fetch_info.type_code in (oracledb.DB_TYPE_CLOB, oracledb.DB_TYPE_BLOB, oracledb.DB_TYPE_NCLOB)
                ]
                if lob_columns:
                    # Convert rows to list of dictionaries with LOB handling
                    rows = [
                        {
                            cursor.description[idx].name: (value.read() if idx in lob_columns else value)
                            for idx, value in enumerate(row)
                        }
                        for row in rows
                    ]
            else:
                cursor.callproc("dbms_output.get_line", (text_var, status_var))
                if status_var.getvalue() == 0:
                    LOGGER.info("Returning DBMS_OUTPUT.")
                    rows = text_var.getvalue()
    except oracledb.DatabaseError as ex:
        if ex.args:
            error_obj = ex.args[0]
            if hasattr(error_obj, "code") and error_obj.code == 955:
                LOGGER.info("Table exists")
            if hasattr(error_obj, "code") and error_obj.code == 942:
                LOGGER.info("Table does not exist")
            else:
                LOGGER.exception("Database error: %s", ex)
                LOGGER.info("Failed SQL: %s", run_sql)
                raise
        else:
            LOGGER.exception("Database error: %s", ex)
            raise
    except oracledb.InterfaceError as ex:
        LOGGER.exception("Interface error: %s", ex)
        raise

    return rows


def drop_vs(conn: oracledb.Connection, vs: VectorStoreTableType) -> None:
    """Drop Vector Storage"""
    LOGGER.info("Dropping Vector Store: %s", vs)
    LangchainVS.drop_table_purge(conn, vs)


def get_databases(
    db_name: Optional[DatabaseNameType] = None, validate: bool = False
) -> Union[list[Database], Database, None]:
    """Return list of Database Objects"""
    databases = get(db_name)
    if validate:
        for db in databases:
            try:
                db_conn = connect(config=db)
            except (DbException, PermissionError, ConnectionError, LookupError):
                continue
            db.vector_stores = _get_vs(db_conn)
            db.connected = True
            db.set_connection(db_conn)
    if db_name:
        return databases[0]

    return databases


def get_client_database(client: ClientIdType, validate: bool = False) -> Database:
    """Return a Database Object based on client settings"""
    client_settings = utils_settings.get_client(client)

    # Get database name from client settings, defaulting to "DEFAULT"
    db_name = "DEFAULT"
    if hasattr(client_settings, "database") and client_settings.database:
        db_name = getattr(client_settings.database, "alias", "DEFAULT")

    # Return Single the Database Object
    return get_databases(db_name=db_name, validate=validate)
