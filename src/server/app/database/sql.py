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

# Hard ceiling on rows materialized by execute_sql so a pathological scan
# raises a clear error instead of silently allocating gigabytes.
DEFAULT_MAX_ROWS = 100_000

# Page size used when streaming rows. Capped against max_rows + 1 so a small
# caller-supplied cap detects overflow within the first fetch instead of
# triggering a second round-trip on the cap-exceeded path.
_FETCH_PAGE_SIZE = 1_000

# Matches the output of ``generate_vs_metadata`` (``re.sub(r"\W", "_", ...).upper()``)
# so legacy stores with non-ASCII aliases (e.g. ``CAFÉ_OPENAI_...``) stay operable.
# Paired with ``fullmatch``: ``$`` would match before a final ``\n``, so ``match()``
# would accept ``"VS\n"`` and leak the newline into DDL interpolation.
_VS_TABLE_NAME_PATTERN = re.compile(r"\w+")


class ResultSetTooLargeError(RuntimeError):
    """Raised when a SELECT returns more rows than the caller's max_rows cap.

    Distinct type so callers that legitimately swallow oracledb errors during
    discovery do not also mask correctness-critical overflows (e.g. metadata
    queries whose empty result would cause stale-chunk retention).
    """


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
    max_rows: int = DEFAULT_MAX_ROWS,
) -> Optional[list]:
    """Execute a SQL statement and return results for SELECT queries.

    - SELECT: returns list of rows with LOB columns auto-read
    - DML/DDL: returns None
    - Swallows ORA-00955 (object already exists) and ORA-00942 (table/view does not exist)

    Result sets larger than *max_rows* raise :class:`ResultSetTooLargeError`
    instead of being truncated, so callers cannot silently lose rows.
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
            page_size = max(1, min(_FETCH_PAGE_SIZE, max_rows + 1))
            result: list = []
            while True:
                batch = await cursor.fetchmany(page_size)
                if not batch:
                    return result
                for row in batch:
                    if len(result) >= max_rows:
                        raise ResultSetTooLargeError(
                            f"execute_sql result exceeds max_rows={max_rows}: {sql.strip()[:80]}"
                        )
                    cols = []
                    for val in row:
                        cols.append(await val.read() if isinstance(val, oracledb.AsyncLOB) else val)
                    result.append(tuple(cols))

        return None
