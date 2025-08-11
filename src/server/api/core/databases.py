"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# spell-checker:ignore clob genai nclob privs selectai
from typing import Optional, Union
import json

import oracledb

from server.api.core import bootstrap

from common.schema import Database, DatabaseAuth, DatabaseNameType, DatabaseVectorStorage, SelectAIProfileType
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.core.database")


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
# Functions
#####################################################
def connect(config: Database) -> oracledb.Connection:
    """Establish a connection to an Oracle Database"""
    logger.info("Connecting to Database: %s", config.dsn)
    include_fields = set(DatabaseAuth.model_fields.keys())
    db_config = config.model_dump(include=include_fields)
    logger.debug("Database Config: %s", db_config)
    # If a wallet password is provided but no wallet location is set
    # default the wallet location to the config directory
    if db_config.get("wallet_password") and not db_config.get("wallet_location"):
        db_config["wallet_location"] = db_config["config_dir"]
    # Check if connection settings are configured
    if any(not db_config[key] for key in ("user", "password", "dsn")):
        raise DbException(status_code=400, detail="missing connection details")

    # Attempt to Connect
    try:
        logger.debug("Attempting Database Connection...")
        conn = oracledb.connect(**db_config)
    except oracledb.DatabaseError as ex:
        if "ORA-01017" in str(ex):
            raise DbException(status_code=401, detail="invalid credentials") from ex
        if "DPY-6005" in str(ex):
            raise DbException(status_code=503, detail="unable to connect") from ex
        else:
            raise DbException(status_code=500, detail=str(ex)) from ex
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
            if cursor.description:  # Check if the query returns rows
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
            return rows
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


def get_vs(conn: oracledb.Connection) -> DatabaseVectorStorage:
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


def selectai_enabled(conn: oracledb.Connection) -> bool:
    """Determine if SelectAI can be used"""
    logger.debug("Checking %s for SelectAI", conn)
    is_enabled = False
    sql = """
          SELECT COUNT(*)
            FROM ALL_TAB_PRIVS
           WHERE TYPE = 'PACKAGE'
             AND PRIVILEGE = 'EXECUTE'
             AND GRANTEE = USER
             AND TABLE_NAME IN ('DBMS_CLOUD','DBMS_CLOUD_AI','DBMS_CLOUD_PIPELINE')
          """
    result = execute_sql(conn, sql)
    if result[0][0] == 3:
        is_enabled = True
    logger.debug("SelectAI enabled (results: %s): %s", result[0][0], is_enabled)

    return is_enabled


def get_selectai_profiles(conn: oracledb.Connection) -> SelectAIProfileType:
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


def get_databases(
    name: Optional[DatabaseNameType] = None, validate: bool = True
) -> Union[list[Database], Database, None]:
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
                db_conn = connect(db)
                db.vector_stores = get_vs(db_conn)
                db.selectai = selectai_enabled(db_conn)
                if db.selectai:
                    db.selectai_profiles = get_selectai_profiles(db_conn)
            except DbException as ex:
                logger.debug("Skipping Database %s - exception: %s", db.name, str(ex))
                db.connected = False
        if name:
            return db  # Return the matched, connected DB immediately

    if name:
        # If we got here with a `name` then we didn't find it
        raise ValueError(f"{name} not found")

    return database_objects
