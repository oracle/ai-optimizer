"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Oracle Deep Data Security database operations.

Builds and runs the Deep Data Security DDL (data roles, end users, data grants) and reads the
catalog views that back the management UI. Object names are strictly validated and
quoted before they reach a DDL string, since DDL cannot use bind variables. Grant
predicates are free-form SQL by design (Deep Data Security policy text); they are length-capped
and run with the caller's own database privileges.

Surface verified against Oracle AI Database 26ai (23.26.2). See
src/server/tests/database/test_deepsec_integration.py.
"""
# spell-checker:ignore deepsec enquote oracledb sqlrf

import logging
import re
from typing import Optional

import oracledb

from server.app.database.sql import execute_sql

LOGGER = logging.getLogger("server.deepsec.database")

# Privileges the Deep Data Security screen relies on, keyed by the capability they unlock.
# Verified: data-grant create/drop needs BOTH CREATE DATA GRANT and ADMINISTER ANY
# DATA GRANT (neither alone is sufficient).
PRIV_CREATE_DATA_ROLE = "CREATE DATA ROLE"
PRIV_DROP_DATA_ROLE = "DROP DATA ROLE"
PRIV_CREATE_END_USER = "CREATE END USER"
PRIV_DROP_END_USER = "DROP END USER"
PRIV_CREATE_DATA_GRANT = "CREATE DATA GRANT"
PRIV_ADMINISTER_ANY_DATA_GRANT = "ADMINISTER ANY DATA GRANT"
PRIV_GRANT_ANY_DATA_ROLE = "GRANT ANY DATA ROLE"

# Supported data-grant privileges (DELETE is row-level only and takes no column list).
_ALL_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE")

# Oracle identifier: a letter followed by letters/digits/_/$/# up to 128 chars.
# Strict on purpose — these values are interpolated into DDL, so anything outside
# this grammar is rejected before a statement is built.
_IDENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,127}")

# Per the CREATE DATA GRANT reference, predicates are capped at 4000 characters.
_MAX_PREDICATE_LEN = 4000


class DeepSecError(ValueError):
    """Raised when a Deep Data Security request fails validation before reaching the database."""


def _is_valid_identifier(name: str) -> bool:
    """True if *name* fits the grammar this module can safely quote into DDL."""
    return isinstance(name, str) and _IDENT_RE.fullmatch(name) is not None


def _ident(name: str, upper: bool = True) -> str:
    """Validate an Oracle identifier and return it double-quoted.

    Quoting makes the value injection-proof. ``upper=True`` (the default) folds
    user-typed principal names to Oracle's default unquoted casing. ``upper=False``
    preserves the given casing — required for catalog-sourced object/column names,
    which are case-sensitive and listed verbatim (e.g. a ``"Sales"`` table).
    """
    if not _is_valid_identifier(name):
        raise DeepSecError(f"Invalid identifier: {name!r}")
    return '"' + (name.upper() if upper else name) + '"'


def _quoted_literal(value: str) -> str:
    """Return a single-quoted SQL string literal with embedded quotes doubled."""
    return "'" + value.replace("'", "''") + "'"


def _quoted_password(value: str) -> str:
    """Return a password as a double-quoted (case-sensitive) identifier."""
    if not value or any(c in value for c in "\x00\n\r"):
        raise DeepSecError("Invalid password")
    return '"' + value.replace('"', '""') + '"'


def _normalize_privileges(privileges: list[str]) -> list[str]:
    out = []
    for p in privileges or []:
        u = p.strip().upper()
        if u not in _ALL_PRIVILEGES:
            raise DeepSecError(f"Unsupported privilege: {p!r}")
        if u not in out:
            out.append(u)
    if not out:
        raise DeepSecError("At least one privilege is required")
    return out


# ---------------------------------------------------------------------------
# Status / capability detection
# ---------------------------------------------------------------------------


async def get_status(conn: oracledb.AsyncConnection) -> dict:
    """Return a Deep Data Security capability matrix for the connected user.

    ``available`` reflects whether the database build includes Deep Data Security at all;
    the per-capability flags reflect what *this* user is privileged to do.
    """
    version_rows = await execute_sql(
        conn, "SELECT version_full FROM product_component_version WHERE ROWNUM = 1"
    )
    version = version_rows[0][0] if version_rows else None

    # Feature presence in the build: the privilege exists in the privilege map.
    feature_rows = await execute_sql(
        conn, "SELECT 1 FROM system_privilege_map WHERE name = :n", {"n": PRIV_CREATE_DATA_GRANT}
    )
    available = bool(feature_rows)

    held: set[str] = set()
    if available:
        priv_rows = await execute_sql(conn, "SELECT privilege FROM session_privs")
        held = {r[0] for r in (priv_rows or [])}

    capabilities = {
        "create_data_role": PRIV_CREATE_DATA_ROLE in held,
        "drop_data_role": PRIV_DROP_DATA_ROLE in held,
        "create_end_user": PRIV_CREATE_END_USER in held,
        "drop_end_user": PRIV_DROP_END_USER in held,
        "manage_data_grants": PRIV_CREATE_DATA_GRANT in held and PRIV_ADMINISTER_ANY_DATA_GRANT in held,
        # GRANT/REVOKE DATA ROLE (role <-> end-user membership) both require GRANT ANY DATA ROLE.
        "grant_data_roles": PRIV_GRANT_ANY_DATA_ROLE in held,
        # Listing roles/end users requires read access to the DBA_* views; a COUNT
        # returns a row when accessible and None (ORA-00942 swallowed) when not.
        "list_data_roles": available and await _can_read(conn, "dba_data_roles"),
        "list_end_users": available and await _can_read(conn, "dba_end_users"),
        "list_data_grants": available,  # USER_DATA_GRANTS needs no extra grant
        "list_data_role_grants": available and await _can_read(conn, "dba_data_role_grants"),
    }
    return {
        "available": available,
        "version": version,
        "capabilities": capabilities,
    }


async def _can_read(conn: oracledb.AsyncConnection, view: str) -> bool:
    """Return True if *view* is readable (a COUNT yields a row; ORA-00942 → None)."""
    rows = await execute_sql(conn, f"SELECT COUNT(*) FROM {view} WHERE ROWNUM = 1")
    return rows is not None


# ---------------------------------------------------------------------------
# Schema objects (grant targets)
# ---------------------------------------------------------------------------


async def list_objects(conn: oracledb.AsyncConnection) -> list[dict]:
    """List the connected user's tables and views that data grants can target."""
    rows = await execute_sql(
        conn,
        "SELECT object_name, object_type FROM user_objects "
        "WHERE object_type IN ('TABLE', 'VIEW') ORDER BY object_name",
    )
    # Drop names the validator cannot safely quote (e.g. embedded spaces), so the
    # UI never offers an object that would fail column lookup / grant creation.
    return [{"name": r[0], "type": r[1]} for r in (rows or []) if _is_valid_identifier(r[0])]


async def list_object_columns(conn: oracledb.AsyncConnection, object_name: str) -> list[str]:
    """List column names for one of the user's tables/views."""
    # Validate, then compare against the exact (case-preserved) catalog value.
    bare = _ident(object_name, upper=False).strip('"')
    rows = await execute_sql(
        conn,
        "SELECT column_name FROM user_tab_columns WHERE table_name = :n ORDER BY column_id",
        {"n": bare},
    )
    return [r[0] for r in (rows or [])]


def _require_readable(rows: Optional[list], view: str) -> list:
    """Return *rows*, or raise if the catalog view was unreadable.

    ``execute_sql`` returns None when ORA-00942 is swallowed (the view is missing
    or the user lacks SELECT on it); an accessible-but-empty view returns []. The
    DBA_* views used for listing require an explicit SELECT grant, so surface the
    permission problem rather than reporting an empty list.
    """
    if rows is None:
        raise DeepSecError(f"Cannot read {view}: SELECT on {view} is required.")
    return rows


async def _exec_ddl(conn: oracledb.AsyncConnection, sql: str) -> None:
    """Execute a Deep Sec DDL statement, surfacing all database errors.

    Unlike ``execute_sql``, this does NOT swallow ORA-00955 (object already
    exists) or ORA-00942 (missing/inaccessible object); a rejected CREATE/DROP
    must never be reported to the caller as success.
    """
    LOGGER.debug("deepsec ddl: %s", sql)
    async with conn.cursor() as cursor:
        await cursor.execute(sql)


# ---------------------------------------------------------------------------
# Data roles
# ---------------------------------------------------------------------------


async def list_data_roles(conn: oracledb.AsyncConnection) -> list[dict]:
    rows = _require_readable(
        await execute_sql(
            conn, "SELECT data_role, mapped_to, enabled_by_default FROM dba_data_roles ORDER BY data_role"
        ),
        "DBA_DATA_ROLES",
    )
    return [{"name": r[0], "mapped_to": r[1], "enabled_by_default": bool(r[2])} for r in rows]


async def create_data_role(conn: oracledb.AsyncConnection, name: str, mapped_to: Optional[str] = None) -> None:
    sql = f"CREATE DATA ROLE {_ident(name)}"
    if mapped_to:
        sql += f" MAPPED TO {_quoted_literal(mapped_to)}"
    await _exec_ddl(conn, sql)
    await conn.commit()


async def drop_data_role(conn: oracledb.AsyncConnection, name: str) -> None:
    await _exec_ddl(conn, f"DROP DATA ROLE {_ident(name)}")
    await conn.commit()


# ---------------------------------------------------------------------------
# End users
# ---------------------------------------------------------------------------


async def list_end_users(conn: oracledb.AsyncConnection) -> list[dict]:
    rows = _require_readable(
        await execute_sql(
            conn,
            "SELECT username, account_status, schema, created_date FROM dba_end_users ORDER BY username",
        ),
        "DBA_END_USERS",
    )
    return [
        {"name": r[0], "account_status": r[1], "schema_name": r[2], "created": str(r[3]) if r[3] else None}
        for r in rows
    ]


async def create_end_user(
    conn: oracledb.AsyncConnection, name: str, password: str, schema: Optional[str] = None
) -> None:
    sql = f"CREATE END USER {_ident(name)} IDENTIFIED BY {_quoted_password(password)}"
    if schema:
        # SCHEMA associates an existing schema for name resolution (end users own no schema).
        sql += f" SCHEMA {_ident(schema)}"
    await _exec_ddl(conn, sql)
    await conn.commit()


async def drop_end_user(conn: oracledb.AsyncConnection, name: str) -> None:
    await _exec_ddl(conn, f"DROP END USER {_ident(name)}")
    await conn.commit()


# ---------------------------------------------------------------------------
# Data role grants (data role -> end user membership)
# ---------------------------------------------------------------------------
# Only locally-managed data roles can be granted to end users; externally-mapped
# roles are enabled via IAM token claims and cannot be granted here.


async def list_data_role_grants(conn: oracledb.AsyncConnection) -> list[dict]:
    """List data-role grants made to local end users (role <-> end-user membership)."""
    rows = _require_readable(
        await execute_sql(
            conn,
            "SELECT data_role, grantee, start_time, end_time FROM dba_data_role_grants "
            "WHERE role_type = 'DATA ROLE' AND grantee_type = 'END USER' "
            "ORDER BY grantee, data_role",
        ),
        "DBA_DATA_ROLE_GRANTS",
    )
    return [
        {
            "data_role": r[0],
            "grantee": r[1],
            "start_time": str(r[2]) if r[2] else None,
            "end_time": str(r[3]) if r[3] else None,
        }
        for r in rows
    ]


async def grant_data_role(conn: oracledb.AsyncConnection, roles: list[str], grantee: str) -> None:
    """Grant one or more locally-managed data roles to an end user."""
    if not roles:
        raise DeepSecError("At least one data role is required")
    role_list = ", ".join(_ident(r) for r in roles)
    await _exec_ddl(conn, f"GRANT DATA ROLE {role_list} TO {_ident(grantee)}")
    await conn.commit()


async def revoke_data_role(conn: oracledb.AsyncConnection, role: str, grantee: str) -> None:
    """Revoke a data role from an end user."""
    await _exec_ddl(conn, f"REVOKE DATA ROLE {_ident(role)} FROM {_ident(grantee)}")
    await conn.commit()


# ---------------------------------------------------------------------------
# Data grants
# ---------------------------------------------------------------------------


async def list_data_grants(conn: oracledb.AsyncConnection) -> list[dict]:
    # Reads USER_DATA_GRANTS, which every user can read without an extra grant
    # (unlike the DBA_* views in list_data_roles/list_end_users), so there is no
    # permission gate here — an empty result simply means no grants exist.
    rows = await execute_sql(
        conn,
        "SELECT grant_name, privilege, column_name, granted_with_all_columns_except, "
        "object_owner, object_name, object_type, predicate, grantee, grantee_type, "
        "start_time, end_time FROM user_data_grants ORDER BY grant_name, column_name",
    )
    return [
        {
            "name": r[0],
            "privilege": r[1],
            "column_name": r[2],
            "all_columns_except": bool(r[3]) if r[3] is not None else None,
            "object_owner": r[4],
            "object_name": r[5],
            "object_type": r[6],
            "predicate": r[7],
            "grantee": r[8],
            "grantee_type": r[9],
            "start_time": str(r[10]) if r[10] else None,
            "end_time": str(r[11]) if r[11] else None,
        }
        for r in (rows or [])
    ]


def build_create_data_grant_sql(
    *,
    name: str,
    privileges: list[str],
    object_name: str,
    grantee: str,
    columns: Optional[list[str]] = None,
    all_columns_except: bool = False,
    predicate: Optional[str] = None,
    or_replace: bool = False,
) -> str:
    """Build a CREATE DATA GRANT statement from validated parts.

    Pure function (no I/O) so it is unit-testable without a database.
    """
    privs = _normalize_privileges(privileges)

    col_clause = ""
    if columns:
        # Column names are catalog-sourced and case-sensitive — preserve casing.
        cols = ", ".join(_ident(c, upper=False) for c in columns)
        col_clause = f" (ALL COLUMNS EXCEPT {cols})" if all_columns_except else f" ({cols})"
    elif all_columns_except:
        raise DeepSecError("ALL COLUMNS EXCEPT requires at least one column")

    parts = []
    for p in privs:
        if p == "DELETE":
            parts.append("DELETE")  # DELETE is row-level; no column list
        else:
            parts.append(f"{p}{col_clause}")

    sql = "CREATE OR REPLACE DATA GRANT " if or_replace else "CREATE DATA GRANT "
    sql += f"{_ident(name)} AS {', '.join(parts)} ON {_ident(object_name, upper=False)}"

    if predicate:
        predicate = predicate.strip()
        if len(predicate) > _MAX_PREDICATE_LEN:
            raise DeepSecError(f"Predicate exceeds {_MAX_PREDICATE_LEN} characters")
        if "\x00" in predicate:
            raise DeepSecError("Invalid predicate")
        sql += f" WHERE {predicate}"

    sql += f" TO {_ident(grantee)}"
    return sql


async def create_data_grant(conn: oracledb.AsyncConnection, **kwargs) -> None:
    sql = build_create_data_grant_sql(**kwargs)
    await _exec_ddl(conn, sql)
    await conn.commit()


async def drop_data_grant(conn: oracledb.AsyncConnection, name: str) -> None:
    await _exec_ddl(conn, f"DROP DATA GRANT {_ident(name)}")
    await conn.commit()
