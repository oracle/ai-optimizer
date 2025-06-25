"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v 1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore

import json

from oracledb import Connection
import server.utils.databases as databases
from common.schema import ClientIdType
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.utils.testbed")


def create_settings_objects(db_conn: Connection) -> None:
    """Create table to store Settings"""
    settings_tbl = """
            CREATE TABLE IF NOT EXISTS oai_settings (
                name     VARCHAR2(255) NOT NULL,
                type     VARCHAR2(255) NOT NULL,
                created  TIMESTAMP(9) WITH LOCAL TIME ZONE,
                updated  TIMESTAMP(9) WITH LOCAL TIME ZONE,
                settings JSON,
                CONSTRAINT oai_settings_pk PRIMARY KEY (name, type)
            )
        """
    logger.info("Creating settings Table")
    _ = databases.execute_sql(db_conn, settings_tbl)


def upsert_settings(
    db_conn: Connection,
    name: ClientIdType,
    setting_type: str,
    json_data: json,
) -> None:
    """Upsert Q&A"""
    logger.info("Upsert Settings: %s - %s", name, setting_type)
    parsed_data = json.loads(json_data)
    if not isinstance(parsed_data, list):
        parsed_data = [parsed_data]
    json_data = json.dumps(parsed_data) if isinstance(parsed_data, list) else json_data
    binds = {"name": name, "setting_type": setting_type, "json_data": json_data}
    plsql = """
        DECLARE
            l_name     oai_settings.name%TYPE := :name;
            l_type     oai_settings.type%TYPE := :setting_type;
            l_qa_obj   JSON_OBJECT_T := :json_data;
        BEGIN
            UPDATE oai_settings SET
                updated  = CURRENT_TIMESTAMP,
                settings = l_qa_object
            WHERE name = l_name AND type = l_type;
        EXCEPTION WHEN NO_DATA_FOUND
            INSERT INTO oai_settings (name, type, created, settings)
            VALUES (l_name, l_type, CURRENT_TIMESTAMP, l_qa_object);
        END;
    """
    logger.debug("Upsert PLSQL: %s", plsql)
    return databases.execute_sql(db_conn, plsql, binds)
