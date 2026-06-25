"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for Oracle Deep Data Security DDL against the live 26ai container.

These exercise the real CREATE DATA ROLE / CREATE END USER / CREATE DATA GRANT
statements as the connection user. They auto-skip on database builds that do not
include Deep Data Security (the connection user will not hold CREATE DATA GRANT),
mirroring the live_oci auto-skip convention.

The connection user's Deep Data Security privileges are granted in conftest._write_startup_scripts.
"""
# spell-checker: disable

import contextlib

import oracledb
import pytest

from server.app.deepsec import database as deepsec_db

pytestmark = [pytest.mark.db, pytest.mark.integration]

PREFIX = "AIO_DS_IT"


async def _exec(conn, sql):
    """Execute a statement, returning rows for queries or None otherwise."""
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return await cur.fetchall() if cur.description else None


async def _safe(conn, sql):
    """Execute, ignoring database errors (used for best-effort cleanup)."""
    with contextlib.suppress(oracledb.DatabaseError):
        await _exec(conn, sql)


@pytest.fixture
async def deepsec_conn(async_oracle_connection):
    """Yield a connection only if Deep Data Security is available; else skip."""
    conn = async_oracle_connection
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) FROM session_privs WHERE privilege = 'CREATE DATA GRANT'")
        (count,) = await cur.fetchone()
    if not count:
        pytest.skip("Deep Data Security not available on this database build")
    return conn


async def test_data_grant_lifecycle(deepsec_conn):
    """Create column-masked and row-predicate data grants; read them back; drop them."""
    conn = deepsec_conn
    role = f"{PREFIX}_DR"
    tbl = f"{PREFIX}_T"
    g_mask = f"{PREFIX}_MASK"
    g_pred = f"{PREFIX}_PRED"

    for stmt in (
        f"DROP DATA GRANT {g_mask}",
        f"DROP DATA GRANT {g_pred}",
        f"DROP TABLE {tbl} PURGE",
        f"DROP DATA ROLE {role}",
    ):
        await _safe(conn, stmt)

    try:
        await _exec(conn, f"CREATE DATA ROLE {role}")
        await _exec(conn, f"CREATE TABLE {tbl} (id NUMBER, name VARCHAR2(50), salary NUMBER)")
        await _exec(conn, f"INSERT INTO {tbl} VALUES (1, 'alice', 100)")
        await conn.commit()

        # Column masking via ALL COLUMNS EXCEPT and a row-level predicate.
        await _exec(conn, f"CREATE DATA GRANT {g_mask} AS SELECT (ALL COLUMNS EXCEPT salary) ON {tbl} TO {role}")
        await _exec(conn, f"CREATE DATA GRANT {g_pred} AS SELECT ON {tbl} WHERE id = 1 TO {role}")

        rows = await _exec(
            conn,
            "SELECT grant_name, grantee, grantee_type, predicate, granted_with_all_columns_except "
            f"FROM user_data_grants WHERE grant_name LIKE '{PREFIX}%' ORDER BY grant_name",
        )
        by_name = {r[0]: r for r in (rows or [])}
        assert g_mask in by_name, f"{g_mask} not found in user_data_grants: {rows}"
        assert g_pred in by_name, f"{g_pred} not found in user_data_grants: {rows}"

        # The predicate grant records the predicate and grantee data role.
        pred_row = by_name[g_pred]
        assert pred_row[1] == role  # grantee
        assert "DATA ROLE" in (pred_row[2] or "")  # grantee_type
        assert "id" in (pred_row[3] or "").lower()  # predicate

        # Dropping an own data grant succeeds.
        await _exec(conn, f"DROP DATA GRANT {g_mask}")
        remaining = await _exec(
            conn, f"SELECT grant_name FROM user_data_grants WHERE grant_name LIKE '{PREFIX}%'"
        )
        names = {r[0] for r in (remaining or [])}
        assert g_mask not in names
        assert g_pred in names
    finally:
        for stmt in (
            f"DROP DATA GRANT {g_mask}",
            f"DROP DATA GRANT {g_pred}",
            f"DROP TABLE {tbl} PURGE",
            f"DROP DATA ROLE {role}",
        ):
            await _safe(conn, stmt)
        await conn.commit()


async def test_end_user_lifecycle(deepsec_conn):
    """Create a Deep Data Security end user; confirm it lists in DBA_END_USERS; drop it."""
    conn = deepsec_conn
    eu = f"{PREFIX}_EU"
    await _safe(conn, f"DROP END USER {eu}")
    try:
        await _exec(conn, f'CREATE END USER {eu} IDENTIFIED BY "OrA_41_3xPl0d3r"')
        # End users surface in DBA_END_USERS (not USER_END_USERS), readable via the
        # SELECT grant added in conftest._write_startup_scripts.
        rows = await _exec(conn, f"SELECT username FROM dba_end_users WHERE username = '{eu}'")
        assert rows and rows[0][0] == eu
    finally:
        await _safe(conn, f"DROP END USER {eu}")


async def test_end_user_logs_in_via_data_role_connect_role(deepsec_conn):
    """End-to-end connect-as: a local data role carries AIO_DDS_ROLE (CREATE SESSION), so an end
    user granted that data role can authenticate directly — exercised through the app's own
    create_data_role / create_end_user / grant_data_role helpers."""
    from server.tests.conftest import TEST_DB_CONFIG

    conn = deepsec_conn
    dr = f"{PREFIX}_LOGIN_DR"
    eu = f"{PREFIX}_LOGIN_EU"
    for s in (f"DROP END USER {eu}", f"DROP DATA ROLE {dr}"):
        await _safe(conn, s)
    try:
        await deepsec_db.create_data_role(conn, dr)  # also grants AIO_DDS_ROLE to the data role
        await deepsec_db.create_end_user(conn, eu, TEST_DB_CONFIG["db_password"])
        await deepsec_db.grant_data_role(conn, [dr], eu)  # data role -> end user

        eu_conn = await oracledb.connect_async(
            user=eu, password=TEST_DB_CONFIG["db_password"], dsn=TEST_DB_CONFIG["db_dsn"]
        )
        try:
            rows = await _exec(eu_conn, "SELECT 1 FROM DUAL")
            assert rows and rows[0][0] == 1
        finally:
            await eu_conn.close()
    finally:
        for s in (f"DROP END USER {eu}", f"DROP DATA ROLE {dr}"):
            await _safe(conn, s)


async def test_data_role_listing(deepsec_conn):
    """Create a data role; confirm it lists in DBA_DATA_ROLES; drop it."""
    conn = deepsec_conn
    role = f"{PREFIX}_DR2"
    await _safe(conn, f"DROP DATA ROLE {role}")
    try:
        await _exec(conn, f"CREATE DATA ROLE {role}")
        rows = await _exec(conn, f"SELECT data_role FROM dba_data_roles WHERE data_role = '{role}'")
        assert rows and rows[0][0] == role
    finally:
        await _safe(conn, f"DROP DATA ROLE {role}")


async def test_case_sensitive_object_is_actionable(deepsec_conn):
    """A quoted, mixed-case table is listed, its columns resolve, and a grant
    targets the exact object — none of which worked while names were upper-cased.
    """
    conn = deepsec_conn
    role = f"{PREFIX}_CS_DR"
    tbl = "AioDsCs"  # mixed-case (case-sensitive) identifier
    grant = f"{PREFIX}_CS_G"
    cleanup = (f"DROP DATA GRANT {grant}", f'DROP TABLE "{tbl}" PURGE', f"DROP DATA ROLE {role}")
    for stmt in cleanup:
        await _safe(conn, stmt)
    try:
        await _exec(conn, f"CREATE DATA ROLE {role}")
        await _exec(conn, f'CREATE TABLE "{tbl}" (id NUMBER, "MixedCol" VARCHAR2(20), secret VARCHAR2(20))')
        await conn.commit()

        assert tbl in {o["name"] for o in await deepsec_db.list_objects(conn)}

        cols = await deepsec_db.list_object_columns(conn, tbl)
        assert "MixedCol" in cols and "ID" in cols  # case preserved, columns resolve

        await deepsec_db.create_data_grant(
            conn, name=grant, privileges=["SELECT"], object_name=tbl, grantee=role,
            columns=["MixedCol"], all_columns_except=True,
        )
        mine = [g for g in await deepsec_db.list_data_grants(conn) if g["name"] == grant.upper()]
        assert mine and all(g["object_name"] == tbl for g in mine)
    finally:
        for stmt in cleanup:
            await _safe(conn, stmt)
        await conn.commit()


async def test_create_data_grant_duplicate_surfaces_error(deepsec_conn):
    """A rejected CREATE DATA GRANT (duplicate name) must raise, not report success."""
    conn = deepsec_conn
    role = f"{PREFIX}_DUP_DR"
    tbl = f"{PREFIX}_DUP_T"
    grant = f"{PREFIX}_DUP_G"
    cleanup = (f"DROP DATA GRANT {grant}", f"DROP TABLE {tbl} PURGE", f"DROP DATA ROLE {role}")
    for stmt in cleanup:
        await _safe(conn, stmt)
    try:
        await _exec(conn, f"CREATE DATA ROLE {role}")
        await _exec(conn, f"CREATE TABLE {tbl} (id NUMBER, secret VARCHAR2(20))")
        await conn.commit()
        await deepsec_db.create_data_grant(
            conn, name=grant, privileges=["SELECT"], object_name=tbl, grantee=role
        )
        # Same grant again -> ORA-00955; must propagate rather than be swallowed.
        with pytest.raises(oracledb.DatabaseError):
            await deepsec_db.create_data_grant(
                conn, name=grant, privileges=["SELECT"], object_name=tbl, grantee=role
            )
    finally:
        for stmt in cleanup:
            await _safe(conn, stmt)
        await conn.commit()


async def test_catalog_boolean_columns_preserve_false(deepsec_conn):
    """ENABLED_BY_DEFAULT and GRANTED_WITH_ALL_COLUMNS_EXCEPT are native BOOLEAN
    (python-oracledb maps them to bool), so False values survive serialization.
    Proves the listing helpers do not report a disabled role / specific-column
    grant as enabled / all-columns-except.
    """
    conn = deepsec_conn
    role_en = f"{PREFIX}_EN"
    role_dis = f"{PREFIX}_DIS"
    tbl = f"{PREFIX}_BT"
    g_only = f"{PREFIX}_ONLY"
    g_exc = f"{PREFIX}_EXC"
    cleanup = (
        f"DROP DATA GRANT {g_only}",
        f"DROP DATA GRANT {g_exc}",
        f"DROP TABLE {tbl} PURGE",
        f"DROP DATA ROLE {role_en}",
        f"DROP DATA ROLE {role_dis}",
    )
    for stmt in cleanup:
        await _safe(conn, stmt)
    try:
        await _exec(conn, f"CREATE DATA ROLE {role_en}")
        await _exec(conn, f"CREATE DATA ROLE {role_dis} DISABLED")

        # Raw catalog value is a native Python bool, not 'YES'/'NO' text.
        raw = await _exec(
            conn,
            "SELECT data_role, enabled_by_default FROM dba_data_roles "
            f"WHERE data_role IN ('{role_en}', '{role_dis}')",
        )
        raw_vals = {r[0]: r[1] for r in (raw or [])}
        assert isinstance(raw_vals[role_dis], bool), f"expected bool, got {type(raw_vals[role_dis])!r}"
        assert raw_vals[role_en] is True
        assert raw_vals[role_dis] is False

        roles = {r["name"]: r for r in await deepsec_db.list_data_roles(conn)}
        assert roles[role_en]["enabled_by_default"] is True
        assert roles[role_dis]["enabled_by_default"] is False

        await _exec(conn, f"CREATE TABLE {tbl} (id NUMBER, name VARCHAR2(30), salary NUMBER)")
        await _exec(conn, f"CREATE DATA GRANT {g_only} AS SELECT (id) ON {tbl} TO {role_en}")
        await _exec(conn, f"CREATE DATA GRANT {g_exc} AS SELECT (ALL COLUMNS EXCEPT salary) ON {tbl} TO {role_en}")

        grants = await deepsec_db.list_data_grants(conn)
        only = [g for g in grants if g["name"] == g_only]
        exc = [g for g in grants if g["name"] == g_exc]
        # Specific-column grant: catalog value is NULL -> None (NOT reported as
        # all-columns-except). ALL COLUMNS EXCEPT grant: native True.
        assert only and all(g["all_columns_except"] is None for g in only), only
        assert exc and all(g["all_columns_except"] is True for g in exc), exc
    finally:
        for stmt in cleanup:
            await _safe(conn, stmt)
        await conn.commit()
