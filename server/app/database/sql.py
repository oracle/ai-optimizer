"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared async SQL execution utility for Oracle database operations.
"""

import logging
from typing import Optional

import oracledb

LOGGER = logging.getLogger(__name__)


async def execute_sql(
    conn: oracledb.AsyncConnection,
    sql: str,
    binds: Optional[dict] = None,
) -> Optional[list]:
    """Execute a SQL statement and return results for SELECT queries.

    - SELECT: returns list of rows with LOB columns auto-read
    - DML/DDL: returns None
    - Swallows ORA-00955 (object already exists) and ORA-00942 (table/view does not exist)
    - Captures dbms_output for non-SELECT statements
    """
    LOGGER.debug("execute_sql: %s | binds=%s", sql.strip()[:120], binds)

    async with conn.cursor() as cursor:
        try:
            if binds:
                await cursor.execute(sql, binds)
            else:
                await cursor.execute(sql)
        except oracledb.DatabaseError as exc:
            if not exc.args:
                raise
            error = exc.args[0]
            code = getattr(error, "code", None)
            if code in (955, 942):
                LOGGER.info("Ignoring ORA-%05d: %s", code, error.message.strip())
                return None
            raise

        if cursor.description:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                new_row = []
                for val in row:
                    if isinstance(val, oracledb.LOB):
                        new_row.append(await val.read())
                    else:
                        new_row.append(val)
                result.append(tuple(new_row))
            return result

        return None
