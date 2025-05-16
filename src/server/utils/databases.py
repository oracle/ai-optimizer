"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai, PRIVS, PYQSYS, RMAN, RQSYS, SYSAUX

from typing import Union
import oracledb

from common.schema import Database, DatabaseAuth, DatabaseSelectAIObjects
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.utils.database")


class DbException(Exception):
    """Custom Database Exceptions to be passed to HTTPException"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def connect(config: Database) -> oracledb.Connection:
    """Establish a connection to an Oracle Database"""
    logger.info("Connecting to Database: %s", config.dsn)
    include_fields = set(DatabaseAuth.model_fields.keys())
    db_config = config.model_dump(include=include_fields)
    logger.debug("Database Config: %s", db_config)
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


def test(config: Database) -> None:
    """Test connection and re-establish if no longer open"""
    try:
        config.connection.ping()
        logger.info("%s database connection is active.", config.name)
    except oracledb.DatabaseError:
        db_conn = connect(config)
        logger.info("Refreshing %s database connection.", config.name)
        config.set_connection(db_conn)
    except AttributeError as ex:
        raise DbException(status_code=400, detail="missing connection details") from ex


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


def selectai_enabled(conn: oracledb.Connection) -> bool:
    """Determine if SelectAI can be used"""
    logger.debug("Checking %s for SelectAI", conn)
    enabled = "False"
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
        enabled = True
    logger.debug("SelectAI enabled (results: %s): %s", result[0][0], enabled)

    return enabled


def get_selectai_objects(conn: oracledb.Connection) -> DatabaseSelectAIObjects:
    """Retrieve SelectAI Tables"""
    logger.info("Looking for SelectAI Tables")
    selectai_objects = []
    sql = """
            SELECT  a.owner, a.table_name,
                    CASE WHEN b.owner IS NOT NULL THEN 'Y' ELSE 'N' END AS enabled
            FROM ALL_TABLES a
            LEFT JOIN (
                SELECT UPPER(jt.owner) AS owner, UPPER(jt.name) AS table_name
                FROM USER_CLOUD_AI_PROFILE_ATTRIBUTES t,
                    JSON_TABLE(t.attribute_value, '$[*]'
                        COLUMNS (
                            owner VARCHAR2(30) PATH '$.owner',
                            name  VARCHAR2(30) PATH '$.name'
                        )
                    ) jt
                WHERE profile_name = 'OPTIMIZER_PROFILE'
            ) b ON a.owner = b.owner AND a.table_name = b.table_name
            WHERE a.tablespace_name NOT IN ('SYSTEM','SYSAUX')
              AND a.owner NOT IN ('SYS','PYQSYS','OML$METADATA','RQSYS',
                'RMAN$CATALOG','ADMIN','ODI_REPO_USER','C##CLOUD$SERVICE')
          """
    results = execute_sql(conn, sql)
    for owner, table_name, enabled in results:
        selectai_objects.append(DatabaseSelectAIObjects(owner=owner, name=table_name, enabled=enabled))
    logger.debug("Found SelectAI Tables: %s", selectai_objects)

    return selectai_objects


def set_selectai_profile(conn: oracledb.Connection, attribute_name: str, attribute_value: Union[str, list]) -> None:
    """Update SelectAI Profile"""
    logger.info("Updating SelectAI Profile attribute: %s = %s", attribute_name, attribute_value)
    # Attribute Names: provider, credential_name, object_list, provider_endpoint, model
    # Attribute Names: temperature, max_tokens
    binds = {"attribute_name": attribute_name, "attribute_value": attribute_value}
    sql = """
            BEGIN
                DBMS_CLOUD_AI.SET_ATTRIBUTE(
                    profile_name => 'OPTIMIZER_PROFILE',
                    attribute_name => :attribute_name,
                    attribute_value => :attribute_value
                );
            END;
          """
    _ = execute_sql(conn, sql, binds)
