"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai clob nclob vectorstores oraclevs

from typing import Optional, Union
import json
import oracledb
from langchain_community.vectorstores import oraclevs as LangchainVS

import server.api.core.databases as core_databases
import server.api.core.settings as core_settings

from common.schema import (
    Database,
    DatabaseNameType,
    VectorStoreTableType,
    ClientIdType,
    DatabaseAuth,
    DatabaseVectorStorage,
    SelectAIProfileType,
)
from common import logging_config

logger = logging_config.logging.getLogger("api.utils.database")


#####################################################
# Exceptions
#####################################################
class DbException(Exception):
    """Custom Database Exceptions to be passed to HTTPException"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


#####################################################
# Protected Functions
#####################################################
def _test(config: Database) -> None:
    """Test connection and re-establish if no longer open"""
    config.connected = False
    try:
        config.connection.ping()
        logger.info("%s database connection is active.", config.name)
        config.connected = True
    except oracledb.DatabaseError:
        logger.info("Refreshing %s database connection.", config.name)
        _ = connect(config)
    except ValueError as ex:
        raise DbException(status_code=400, detail=f"Database: {str(ex)}") from ex
    except PermissionError as ex:
        raise DbException(status_code=401, detail=f"Database: {str(ex)}") from ex
    except ConnectionError as ex:
        raise DbException(status_code=503, detail=f"Database: {str(ex)}") from ex
    except Exception as ex:
        raise DbException(status_code=500, detail=str(ex)) from ex


def _get_vs(conn: oracledb.Connection) -> DatabaseVectorStorage:
    """Retrieve Vector Storage Tables"""
    logger.info("Looking for Vector Storage Tables")
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
    logger.debug("Found Vector Stores: %s", vector_stores)

    return vector_stores


def _selectai_enabled(conn: oracledb.Connection) -> bool:
    """Determine if SelectAI can be used"""
    logger.debug("Checking %s for SelectAI", conn)
    is_enabled = False
    sql = """
          SELECT COUNT(*)
            FROM ALL_TAB_PRIVS
           WHERE TYPE = 'PACKAGE'
             AND PRIVILEGE = 'EXECUTE'
             AND GRANTEE = USER
             AND TABLE_NAME IN ('DBMS_CLOUD_AI','DBMS_CLOUD_PIPELINE')
          """
    result = execute_sql(conn, sql)
    if result[0][0] == 2:
        is_enabled = True
    logger.debug("SelectAI enabled (results: %s): %s", result[0][0], is_enabled)

    return is_enabled


def _get_selectai_profiles(conn: oracledb.Connection) -> SelectAIProfileType:
    """Retrieve SelectAI Profiles"""
    logger.info("Looking for SelectAI Profiles")
    selectai_profiles = []
    sql = """
            SELECT  profile_name
            FROM USER_CLOUD_AI_PROFILES
          """
    results = execute_sql(conn, sql)
    if results:
        selectai_profiles = [row[0] for row in results]
    logger.debug("Found SelectAI Profiles: %s", selectai_profiles)

    return selectai_profiles


#####################################################
# Functions
#####################################################
def connect(config: Database) -> oracledb.Connection:
    """Establish a connection to an Oracle Database"""
    include_fields = set(DatabaseAuth.model_fields.keys())
    db_authn = config.model_dump(include=include_fields)
    if any(not db_authn[key] for key in ("user", "password", "dsn")):
        raise ValueError("missing connection details")

    logger.info("Connecting to Database: %s", config.dsn)
    # If a wallet password is provided but no wallet location is set
    # default the wallet location to the config directory
    if db_authn.get("wallet_password") and not db_authn.get("wallet_location"):
        db_authn["wallet_location"] = db_authn["config_dir"]

    # Attempt to Connect
    logger.debug("Database AuthN: %s", db_authn)
    try:
        logger.debug("Attempting Database Connection...")
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

    logger.debug("Connected to Databases: %s", config.dsn)

    return conn


def disconnect(conn: oracledb.Connection) -> None:
    """Disconnect from an Oracle Database"""
    logger.debug("Disconnecting Databases Connection: %s", conn)
    return conn.close()


def execute_sql(conn: oracledb.Connection, run_sql: str, binds: dict = None) -> list:
    """Execute SQL against Oracle Database"""
    logger.debug("SQL: %s with binds %s", run_sql, binds)
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
                    logger.info("Returning DBMS_OUTPUT.")
                    rows = text_var.getvalue()
    except oracledb.DatabaseError as ex:
        if ex.args:
            error_obj = ex.args[0]
            if hasattr(error_obj, "code") and error_obj.code == 955:
                logger.info("Table exists")
            if hasattr(error_obj, "code") and error_obj.code == 942:
                logger.info("Table does not exist")
            else:
                logger.exception("Database error: %s", ex)
                logger.info("Failed SQL: %s", run_sql)
                raise
        else:
            logger.exception("Database error: %s", ex)
            raise
    except oracledb.InterfaceError as ex:
        logger.exception("Interface error: %s", ex)
        raise

    return rows


def drop_vs(conn: oracledb.Connection, vs: VectorStoreTableType) -> None:
    """Drop Vector Storage"""
    logger.info("Dropping Vector Store: %s", vs)
    LangchainVS.drop_table_purge(conn, vs)


def get_databases(
    db_name: Optional[DatabaseNameType] = None, validate: bool = False
) -> Union[list[Database], Database, None]:
    """Return list of Database Objects"""
    databases = core_databases.get_database(db_name)
    if validate:
        for db in databases:
            try:
                db_conn = connect(config=db)
            except (ValueError, PermissionError, ConnectionError, LookupError):
                continue
            db.vector_stores = _get_vs(db_conn)
            db.selectai = _selectai_enabled(db_conn)
            if db.selectai:
                db.selectai_profiles = _get_selectai_profiles(db_conn)
            db.connected = True
            db.set_connection(db_conn)
    if db_name:
        return databases[0]

    return databases


def get_client_database(client: ClientIdType, validate: bool = False) -> Database:
    """Return a Database Object based on client settings"""
    client_settings = core_settings.get_client_settings(client)

    # Get database name from client settings, defaulting to "DEFAULT"
    db_name = "DEFAULT"
    if (hasattr(client_settings, "vector_search") and client_settings.vector_search) or (
        hasattr(client_settings, "selectai") and client_settings.selectai
    ):
        db_name = getattr(client_settings.vector_search, "database", "DEFAULT")

    # Return Single the Database Object
    return get_databases(db_name=db_name, validate=validate)
