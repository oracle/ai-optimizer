"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Embed utilities — SQL query execution helpers.
"""
# spell-checker: ignore arraysize

import asyncio
import csv
import logging
import os
import re
import uuid

import oracledb

from server.app.database.config import create_sync_connection
from server.app.database.schemas import DatabaseConfig

LOGGER = logging.getLogger(__name__)

_STRIP_RE = re.compile(
    (
        r"--[^\n]*"  # line comments
        r"|/\*.*?\*/"  # block comments
        r"|'(?:[^']|'')*'"  # single-quoted string literals (Oracle '' escaping)
        r'|"(?:[^"]|"")*"'  # double-quoted identifiers
    ),
    re.DOTALL,
)
_TOKEN_RE = re.compile(r"[A-Z_]\w*|[()]", re.IGNORECASE)


def _is_select_only(query: str) -> bool:
    """Return True only when *query* is a read-only SELECT (or WITH … SELECT)."""
    stripped = _STRIP_RE.sub(" ", query)
    tokens = [t.upper() for t in _TOKEN_RE.findall(stripped)]
    if not tokens:
        return False

    # Skip leading parentheses, e.g. (SELECT …) UNION ALL SELECT …
    first_kw = 0
    while first_kw < len(tokens) and tokens[first_kw] == "(":
        first_kw += 1
    if first_kw >= len(tokens):
        return False

    if tokens[first_kw] == "SELECT":
        return True
    if tokens[first_kw] != "WITH":
        return False

    # Walk the token stream, tracking parenthesis depth,
    # looking for the main-statement keyword after all CTEs.
    depth = 0
    for token in tokens[1:]:
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif depth == 0 and token in (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "MERGE",
        ):
            return token == "SELECT"
    return False


def _run_sql_query_sync(
    db_config: DatabaseConfig,
    query: str,
    base_path: str,
) -> str:
    """Execute a SQL query and save results as a CSV file (sync).

    Returns the full file path of the generated CSV, or empty string on error.
    """
    batch_size = 100
    random_filename = str(uuid.uuid4())
    filename_with_extension = f"{random_filename}.csv"
    full_file_path = os.path.join(base_path, filename_with_extension)

    if not _is_select_only(query):
        raise ValueError("Only SELECT queries are permitted for SQL store")

    try:
        with create_sync_connection(db_config) as connection, connection.cursor() as cursor:
            cursor.arraysize = batch_size
            cursor.execute(query)

            desc = cursor.description
            if not desc:
                return ""
            column_names = [d[0] for d in desc]

            with open(full_file_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(column_names)

                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    writer.writerows(rows)

        return full_file_path

    except oracledb.Error as e:
        LOGGER.error("SQL source connection error: %s", e)
        return ""


async def run_sql_query(
    db_config: DatabaseConfig,
    query: str,
    base_path: str,
) -> str:
    """Execute a SQL query and save results as a CSV file (async wrapper).

    Uses :func:`create_sync_connection` in a thread executor.
    """
    return await asyncio.to_thread(
        _run_sql_query_sync,
        db_config,
        query,
        base_path,
    )
