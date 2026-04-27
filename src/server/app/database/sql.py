"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared async SQL execution utility for Oracle database operations.
"""
# spell-checker:ignore setinputsizes

import logging
import re
from typing import Optional

import oracledb

LOGGER = logging.getLogger(__name__)

# Matches the output of ``generate_vs_metadata`` (``re.sub(r"\W", "_", ...).upper()``)
# so legacy stores with non-ASCII aliases (e.g. ``CAFÉ_OPENAI_...``) stay operable.
# Paired with ``fullmatch``: ``$`` would match before a final ``\n``, so ``match()``
# would accept ``"VS\n"`` and leak the newline into DDL interpolation.
_VS_TABLE_NAME_PATTERN = re.compile(r"\w+")


def validate_oracle_identifier(name: str) -> str:
    """Sanitise *name* for use inside a double-quoted Oracle identifier.

    - Rejects empty / None names.
    - Escapes embedded double-quotes (``"`` → ``""``) to prevent breakout.
    - Returns the sanitized name; callers MUST use the return value.
    """
    if not name:
        raise ValueError(f"Invalid Oracle identifier: {name!r}")
    return name.replace('"', '""')


def validate_vs_table_name(name: str) -> str:
    """Validator for vector-store table names — defense in depth for DDL paths.

    Restricts to Python's Unicode ``\\w+``, the same grammar
    ``generate_vs_metadata`` produces. SQL metacharacters (quotes, whitespace,
    ``;``, ``--``, parentheses) are outside ``\\w`` and therefore rejected
    before reaching the DDL/DML layer that wraps the name in ``"..."``.
    """
    if not name or not _VS_TABLE_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid vector store table name: {name!r}")
    return name


async def execute_sql(
    conn: oracledb.AsyncConnection,
    sql: str,
    binds: Optional[dict] = None,
    input_sizes: Optional[dict] = None,
) -> Optional[list]:
    """Execute a SQL statement and return results for SELECT queries.

    - SELECT: returns list of rows with LOB columns auto-read
    - DML/DDL: returns None
    - Swallows ORA-00955 (object already exists) and ORA-00942 (table/view does not exist)
    """
    LOGGER.debug("execute_sql: %s | binds=%s", sql.strip()[:120], binds)

    async with conn.cursor() as cursor:
        try:
            if input_sizes:
                cursor.setinputsizes(**input_sizes)
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
                cols = []
                for val in row:
                    cols.append(await val.read() if isinstance(val, oracledb.AsyncLOB) else val)
                result.append(tuple(cols))
            return result

        return None
