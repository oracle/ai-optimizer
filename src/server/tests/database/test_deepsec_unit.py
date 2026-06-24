"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for Deep Data Security DDL building and identifier validation (no database).
"""
# spell-checker: disable

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import oracledb
import pytest

from server.app.api.v1.schemas.deepsec import DataRoleGrant
from server.app.deepsec import database as deepsec_db
from server.app.deepsec.database import DeepSecError, build_create_data_grant_sql

pytestmark = pytest.mark.unit


def test_basic_select_grant():
    # Principal names (grant, grantee) are upper-cased; the object name keeps its
    # catalog casing.
    sql = build_create_data_grant_sql(name="g", privileges=["SELECT"], object_name="t", grantee="r")
    assert sql == 'CREATE DATA GRANT "G" AS SELECT ON "t" TO "R"'


def test_all_columns_except():
    sql = build_create_data_grant_sql(
        name="g", privileges=["SELECT"], object_name="emp", grantee="r",
        columns=["salary"], all_columns_except=True,
    )
    assert 'SELECT (ALL COLUMNS EXCEPT "salary")' in sql
    assert 'ON "emp"' in sql


def test_specific_columns():
    sql = build_create_data_grant_sql(
        name="g", privileges=["SELECT"], object_name="emp", grantee="r", columns=["id", "name"]
    )
    assert 'SELECT ("id", "name")' in sql


def test_row_predicate_appended():
    sql = build_create_data_grant_sql(
        name="g", privileges=["SELECT"], object_name="t", grantee="r", predicate="id = 1"
    )
    assert sql.endswith('WHERE id = 1 TO "R"')


def test_multiple_privileges_delete_has_no_columns():
    sql = build_create_data_grant_sql(
        name="g", privileges=["SELECT", "DELETE"], object_name="t", grantee="r", columns=["c"]
    )
    assert 'SELECT ("c")' in sql
    assert ", DELETE " in sql  # DELETE carries no column list


def test_or_replace():
    sql = build_create_data_grant_sql(
        name="g", privileges=["SELECT"], object_name="t", grantee="r", or_replace=True
    )
    assert sql.startswith("CREATE OR REPLACE DATA GRANT")


@pytest.mark.parametrize("bad", ["", "1abc", "a b", "drop;", 'a"b', "x' OR '1"])
def test_invalid_identifier_rejected(bad):
    with pytest.raises(DeepSecError):
        build_create_data_grant_sql(name=bad, privileges=["SELECT"], object_name="t", grantee="r")


def test_unsupported_privilege_rejected():
    with pytest.raises(DeepSecError):
        build_create_data_grant_sql(name="g", privileges=["TRUNCATE"], object_name="t", grantee="r")


def test_no_privileges_rejected():
    with pytest.raises(DeepSecError):
        build_create_data_grant_sql(name="g", privileges=[], object_name="t", grantee="r")


def test_all_columns_except_requires_columns():
    with pytest.raises(DeepSecError):
        build_create_data_grant_sql(
            name="g", privileges=["SELECT"], object_name="t", grantee="r", all_columns_except=True
        )


def test_predicate_length_capped():
    with pytest.raises(DeepSecError):
        build_create_data_grant_sql(
            name="g", privileges=["SELECT"], object_name="t", grantee="r", predicate="x" * 4001
        )


# ---------------------------------------------------------------------------
# Unreadable catalog views must surface a permission error, not an empty list
# (execute_sql swallows ORA-00942 and returns None; an accessible empty SELECT
# returns []).
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_data_roles_raises_when_view_unreadable():
    with (
        patch.object(deepsec_db, "execute_sql", AsyncMock(return_value=None)),
        pytest.raises(DeepSecError),
    ):
        await deepsec_db.list_data_roles(AsyncMock())


@pytest.mark.anyio
async def test_list_end_users_raises_when_view_unreadable():
    with (
        patch.object(deepsec_db, "execute_sql", AsyncMock(return_value=None)),
        pytest.raises(DeepSecError),
    ):
        await deepsec_db.list_end_users(AsyncMock())


@pytest.mark.anyio
async def test_list_data_roles_empty_is_not_an_error():
    """An accessible but empty view returns [] (None means unreadable)."""
    with patch.object(deepsec_db, "execute_sql", AsyncMock(return_value=[])):
        assert await deepsec_db.list_data_roles(AsyncMock()) == []


# ---------------------------------------------------------------------------
# Catalog object/column names are case-sensitive when quoted; the tool must
# preserve their casing rather than upper-case it.
# ---------------------------------------------------------------------------


def test_object_name_preserves_case():
    sql = build_create_data_grant_sql(name="g", privileges=["SELECT"], object_name="Sales", grantee="r")
    assert 'ON "Sales"' in sql
    assert '"SALES"' not in sql


def test_column_names_preserve_case():
    sql = build_create_data_grant_sql(
        name="g", privileges=["SELECT"], object_name="Sales", grantee="r", columns=["Id", "Name"]
    )
    assert 'SELECT ("Id", "Name")' in sql


@pytest.mark.anyio
async def test_list_objects_filters_names_outside_validator():
    rows = [("Sales", "TABLE"), ("Sales Report", "TABLE"), ("EMP", "TABLE")]
    with patch.object(deepsec_db, "execute_sql", AsyncMock(return_value=rows)):
        names = {o["name"] for o in await deepsec_db.list_objects(AsyncMock())}
    assert names == {"Sales", "EMP"}  # "Sales Report" (space) is un-actionable -> filtered


@pytest.mark.anyio
async def test_list_object_columns_preserves_case():
    captured = {}

    async def _fake(conn, sql, binds=None):
        captured["binds"] = binds
        return []

    with patch.object(deepsec_db, "execute_sql", side_effect=_fake):
        await deepsec_db.list_object_columns(AsyncMock(), "Sales")
    assert captured["binds"] == {"n": "Sales"}


# ---------------------------------------------------------------------------
# DDL must surface database errors. execute_sql swallows ORA-00955/00942, which
# would make a rejected CREATE look like success — Deep Sec DDL must not use it.
# ---------------------------------------------------------------------------


class _OraError:
    """Stand-in for oracledb's error object carrying a numeric .code."""

    def __init__(self, code: int):
        self.code = code
        self.message = f"ORA-{code:05d}: simulated"


def _conn_ddl_raises(code: int):
    """Async connection mock whose cursor.execute raises an ORA-<code> error."""
    cur = AsyncMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    cur.description = None
    cur.setinputsizes = MagicMock()
    cur.execute = AsyncMock(side_effect=oracledb.DatabaseError(_OraError(code)))
    conn = AsyncMock()
    conn.cursor = MagicMock(return_value=cur)
    conn.commit = AsyncMock()
    return conn


@pytest.mark.anyio
@pytest.mark.parametrize("code", [955, 942])
async def test_create_data_grant_surfaces_object_errors(code):
    """Duplicate name (955) / missing object (942) must raise, not commit silently."""
    conn = _conn_ddl_raises(code)
    with pytest.raises(oracledb.DatabaseError):
        await deepsec_db.create_data_grant(
            conn, name="g", privileges=["SELECT"], object_name="t", grantee="r"
        )
    conn.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_create_data_role_surfaces_duplicate():
    conn = _conn_ddl_raises(955)
    with pytest.raises(oracledb.DatabaseError):
        await deepsec_db.create_data_role(conn, "r")
    conn.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_create_end_user_surfaces_duplicate():
    conn = _conn_ddl_raises(955)
    with pytest.raises(oracledb.DatabaseError):
        await deepsec_db.create_end_user(conn, "u", "pw")
    conn.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_create_end_user_appends_schema_clause():
    conn, calls = _conn_ddl_capture()
    await deepsec_db.create_end_user(conn, "emma", "pw", "academy")
    assert calls == ['CREATE END USER "EMMA" IDENTIFIED BY "pw" SCHEMA "ACADEMY"']
    conn.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_create_end_user_omits_schema_clause_when_absent():
    conn, calls = _conn_ddl_capture()
    await deepsec_db.create_end_user(conn, "emma", "pw")
    assert "SCHEMA" not in calls[0]


# ---------------------------------------------------------------------------
# Data role grants (role -> end user membership)
# ---------------------------------------------------------------------------


def _conn_ddl_capture():
    """Async connection mock that records the DDL passed to cursor.execute."""
    calls: list[str] = []
    cur = AsyncMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    cur.execute = AsyncMock(side_effect=lambda sql, *a, **k: calls.append(sql))
    conn = AsyncMock()
    conn.cursor = MagicMock(return_value=cur)
    conn.commit = AsyncMock()
    return conn, calls


@pytest.mark.anyio
async def test_grant_data_role_builds_and_commits():
    conn, calls = _conn_ddl_capture()
    await deepsec_db.grant_data_role(conn, ["employee_role", "manager_role"], "emma")
    assert calls == ['GRANT DATA ROLE "EMPLOYEE_ROLE", "MANAGER_ROLE" TO "EMMA"']
    conn.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_grant_data_role_requires_at_least_one_role():
    conn, calls = _conn_ddl_capture()
    with pytest.raises(DeepSecError):
        await deepsec_db.grant_data_role(conn, [], "emma")
    assert calls == []
    conn.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_revoke_data_role_builds_and_commits():
    conn, calls = _conn_ddl_capture()
    await deepsec_db.revoke_data_role(conn, "employee_role", "emma")
    assert calls == ['REVOKE DATA ROLE "EMPLOYEE_ROLE" FROM "EMMA"']
    conn.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_list_data_role_grants_raises_when_view_unreadable():
    with (
        patch.object(deepsec_db, "execute_sql", AsyncMock(return_value=None)),
        pytest.raises(DeepSecError),
    ):
        await deepsec_db.list_data_role_grants(AsyncMock())


@pytest.mark.anyio
async def test_list_data_role_grants_maps_rows():
    rows = [("EMPLOYEE_ROLE", "EMMA", None, None)]
    with patch.object(deepsec_db, "execute_sql", AsyncMock(return_value=rows)):
        out = await deepsec_db.list_data_role_grants(AsyncMock())
    assert out == [{"data_role": "EMPLOYEE_ROLE", "grantee": "EMMA", "start_time": None, "end_time": None}]


@pytest.mark.anyio
async def test_list_data_role_grants_stringifies_timestamps():
    """Non-null START_TIME/END_TIME come back as driver datetimes; they must be
    stringified to satisfy the str | None response schema (DataRoleGrant)."""
    rows = [("EMPLOYEE_ROLE", "EMMA", datetime(2026, 6, 1, 9, 30), datetime(2026, 12, 31, 17, 0))]
    with patch.object(deepsec_db, "execute_sql", AsyncMock(return_value=rows)):
        out = await deepsec_db.list_data_role_grants(AsyncMock())
    assert out == [
        {
            "data_role": "EMPLOYEE_ROLE",
            "grantee": "EMMA",
            "start_time": "2026-06-01 09:30:00",
            "end_time": "2026-12-31 17:00:00",
        }
    ]
    DataRoleGrant.model_validate(out[0])  # would raise if a raw datetime leaked through
