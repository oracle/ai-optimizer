"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai, privs, pyqsys, rman, rqsys, sysaux

from typing import Union
import oracledb

import server.api.utils.databases as utils_databases

from common.schema import SelectAIProfileType, DatabaseSelectAIObjects
from common import logging_config

logger = logging_config.logging.getLogger("api.utils.selectai")


def set_profile(
    conn: oracledb.Connection,
    profile_name: SelectAIProfileType,
    attribute_name: str,
    attribute_value: Union[str, list],
) -> None:
    """Update SelectAI Profile"""
    logger.info("Updating SelectAI Profile (%s) attribute: %s = %s", profile_name, attribute_name, attribute_value)
    # Attribute Names: provider, credential_name, object_list, provider_endpoint, model
    # Attribute Names: temperature, max_tokens

    if isinstance(attribute_value, float) or isinstance(attribute_value, int):
        attribute_value = str(attribute_value)

    binds = {"profile_name": profile_name, "attribute_name": attribute_name, "attribute_value": attribute_value}
    sql = """
            BEGIN
                DBMS_CLOUD_AI.SET_ATTRIBUTE(
                    profile_name => :profile_name,
                    attribute_name => :attribute_name,
                    attribute_value => :attribute_value
                );
            END;
          """
    _ = utils_databases.execute_sql(conn, sql, binds)


def get_objects(conn: oracledb.Connection, profile_name: SelectAIProfileType) -> DatabaseSelectAIObjects:
    """Retrieve SelectAI Objects"""
    logger.info("Looking for SelectAI Objects for profile: %s", profile_name)
    selectai_objects = []
    binds = {"profile_name": profile_name}
    sql = """
            SELECT  a.owner, a.table_name,
                    CASE WHEN b.owner IS NOT NULL THEN 'Y' ELSE 'N' END AS object_enabled
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
                WHERE profile_name = :profile_name
            ) b ON a.owner = b.owner AND a.table_name = b.table_name
            WHERE a.tablespace_name NOT IN ('SYSTEM','SYSAUX')
              AND a.owner NOT IN ('SYS','PYQSYS','OML$METADATA','RQSYS',
                'RMAN$CATALOG','ADMIN','ODI_REPO_USER','C##CLOUD$SERVICE')
            ORDER BY owner, table_name
          """
    results = utils_databases.execute_sql(conn, sql, binds)
    for owner, table_name, object_enabled in results:
        selectai_objects.append(DatabaseSelectAIObjects(owner=owner, name=table_name, enabled=object_enabled))
    logger.debug("Found SelectAI Objects: %s", selectai_objects)

    return selectai_objects
