"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the execute_sql utility.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock

import oracledb
import pytest

from server.app.database.sql import (
    DEFAULT_MAX_ROWS,
    ResultSetTooLargeError,
    execute_sql,
    validate_oracle_identifier,
)


def _fetchmany_from(rows):
    """Build an AsyncMock fetchmany side-effect that drains *rows* in chunks."""
    pending = list(rows)

    async def _fm(size):
        chunk = pending[:size]
        del pending[:size]
        return chunk

    return _fm

# ---------------------------------------------------------------------------
# Unit tests (no database required)
# ---------------------------------------------------------------------------

def _make_ora_error(code: int, message: str = "error"):
    """Create an oracledb.DatabaseError with a given ORA code."""
    err = MagicMock()
    err.code = code
    err.message = message
    exc = oracledb.DatabaseError(err)
    return exc


def _mock_conn(cursor):
    """Return a mock connection whose cursor() context manager yields *cursor*."""
    conn = MagicMock()
    conn.cursor.return_value.__aenter__ = AsyncMock(return_value=cursor)
    conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)
    return conn


@pytest.mark.unit
async def test_execute_sql_select():
    """SELECT returns list of tuples when cursor.description is set."""
    cursor = AsyncMock()
    cursor.description = [("COL1",)]
    cursor.fetchmany = AsyncMock(side_effect=_fetchmany_from([(1,), (2,)]))
    conn = _mock_conn(cursor)

    result = await execute_sql(conn, "SELECT 1 FROM DUAL")

    assert result == [(1,), (2,)]
    cursor.execute.assert_awaited_once_with("SELECT 1 FROM DUAL")


@pytest.mark.unit
async def test_execute_sql_select_with_lob():
    """AsyncLOB values are read automatically."""
    lob = MagicMock(spec=oracledb.AsyncLOB)
    lob.read = AsyncMock(return_value="lob_content")

    cursor = AsyncMock()
    cursor.description = [("COL1",)]
    cursor.fetchmany = AsyncMock(side_effect=_fetchmany_from([(lob,)]))
    conn = _mock_conn(cursor)

    result = await execute_sql(conn, "SELECT clob_col FROM t")

    assert result == [("lob_content",)]
    lob.read.assert_awaited_once()


@pytest.mark.unit
async def test_execute_sql_uses_fetchmany_not_fetchall():
    """SELECT path streams via fetchmany; fetchall is never awaited."""
    cursor = AsyncMock()
    cursor.description = [("COL1",)]
    cursor.fetchmany = AsyncMock(side_effect=_fetchmany_from([(1,)]))
    cursor.fetchall = AsyncMock()
    conn = _mock_conn(cursor)

    await execute_sql(conn, "SELECT 1 FROM DUAL")

    cursor.fetchmany.assert_awaited()
    cursor.fetchall.assert_not_awaited()


@pytest.mark.unit
async def test_execute_sql_returns_rows_under_cap():
    """Result sets within max_rows are returned in full."""
    cursor = AsyncMock()
    cursor.description = [("ID",)]
    cursor.fetchmany = AsyncMock(side_effect=_fetchmany_from([(i,) for i in range(50)]))
    conn = _mock_conn(cursor)

    result = await execute_sql(conn, "SELECT id FROM t", max_rows=100)

    assert result == [(i,) for i in range(50)]


@pytest.mark.unit
async def test_execute_sql_raises_when_result_exceeds_cap():
    """Result sets larger than max_rows raise the specific overflow type."""
    cursor = AsyncMock()
    cursor.description = [("ID",)]
    cursor.fetchmany = AsyncMock(side_effect=_fetchmany_from([(i,) for i in range(200)]))
    conn = _mock_conn(cursor)

    with pytest.raises(ResultSetTooLargeError, match="exceeds max_rows"):
        await execute_sql(conn, "SELECT id FROM big_table", max_rows=10)


@pytest.mark.unit
def test_result_set_too_large_is_runtime_error():
    """ResultSetTooLargeError is a RuntimeError subclass for backwards compatibility."""
    assert issubclass(ResultSetTooLargeError, RuntimeError)


@pytest.mark.unit
async def test_execute_sql_custom_max_rows_at_boundary():
    """Result of exactly max_rows succeeds (no off-by-one overflow)."""
    cursor = AsyncMock()
    cursor.description = [("ID",)]
    cursor.fetchmany = AsyncMock(side_effect=_fetchmany_from([(i,) for i in range(5)]))
    conn = _mock_conn(cursor)

    result = await execute_sql(conn, "SELECT id FROM t", max_rows=5)

    assert result == [(i,) for i in range(5)]


@pytest.mark.unit
def test_execute_sql_default_max_rows_constant():
    """Default cap is exposed as a module constant for callers/tests."""
    assert isinstance(DEFAULT_MAX_ROWS, int)
    assert DEFAULT_MAX_ROWS >= 10_000


@pytest.mark.unit
async def test_execute_sql_dml():
    """DML (no cursor.description) returns None."""
    cursor = AsyncMock()
    cursor.description = None
    conn = _mock_conn(cursor)

    result = await execute_sql(conn, "INSERT INTO t VALUES (1)")

    assert result is None


@pytest.mark.unit
async def test_execute_sql_with_binds():
    """Binds dict is passed to cursor.execute."""
    cursor = AsyncMock()
    cursor.description = None
    conn = _mock_conn(cursor)
    binds = {"id": 1}

    await execute_sql(conn, "DELETE FROM t WHERE id = :id", binds=binds)

    cursor.execute.assert_awaited_once_with("DELETE FROM t WHERE id = :id", binds)


@pytest.mark.unit
async def test_execute_sql_with_input_sizes():
    """setinputsizes is called when input_sizes is provided."""
    cursor = AsyncMock()
    cursor.description = None
    cursor.setinputsizes = MagicMock()
    conn = _mock_conn(cursor)
    sizes = {"payload": oracledb.DB_TYPE_JSON}

    await execute_sql(conn, "INSERT INTO t (payload) VALUES (:payload)", input_sizes=sizes)

    cursor.setinputsizes.assert_called_once_with(payload=oracledb.DB_TYPE_JSON)


@pytest.mark.unit
async def test_execute_sql_ignores_ora_955():
    """ORA-00955 (object already exists) is silently ignored."""
    cursor = AsyncMock()
    cursor.execute = AsyncMock(side_effect=_make_ora_error(955, "name is already used"))
    conn = _mock_conn(cursor)

    result = await execute_sql(conn, "CREATE TABLE t (id NUMBER)")

    assert result is None


@pytest.mark.unit
async def test_execute_sql_ignores_ora_942():
    """ORA-00942 (table or view does not exist) is silently ignored."""
    cursor = AsyncMock()
    cursor.execute = AsyncMock(side_effect=_make_ora_error(942, "table or view does not exist"))
    conn = _mock_conn(cursor)

    result = await execute_sql(conn, 'DROP TABLE "MISSING" PURGE')

    assert result is None


@pytest.mark.unit
async def test_execute_sql_reraises_other_errors():
    """Non-955/942 DatabaseErrors are re-raised."""
    cursor = AsyncMock()
    cursor.execute = AsyncMock(side_effect=_make_ora_error(1, "unique constraint violated"))
    conn = _mock_conn(cursor)

    with pytest.raises(oracledb.DatabaseError):
        await execute_sql(conn, "INSERT INTO t VALUES (1)")


@pytest.mark.unit
async def test_execute_sql_reraises_when_no_args():
    """DatabaseError with empty args is re-raised."""
    cursor = AsyncMock()
    exc = oracledb.DatabaseError()
    cursor.execute = AsyncMock(side_effect=exc)
    conn = _mock_conn(cursor)

    with pytest.raises(oracledb.DatabaseError):
        await execute_sql(conn, "SELECT 1 FROM DUAL")


# ---------------------------------------------------------------------------
# validate_oracle_identifier
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateOracleIdentifier:
    """Test Oracle identifier validation."""

    @pytest.mark.parametrize(
        "name",
        [
            "MY_TABLE",
            "table123",
            "A",
            "VS_TMP",
            "OCI_EMBED_V3_500_50_COSINE_HNSW",
            "SYS$SESSION",
            "TEMP#1",
            "has space",
            "CUSTOMER-DATA",
            "dot.name",
            "semi;colon",
            "slash/path",
        ],
    )
    def test_valid_identifiers(self, name):
        """Non-empty names without double-quotes are returned unchanged."""
        assert validate_oracle_identifier(name) == name

    def test_quote_escaping(self):
        """Embedded double-quotes are escaped to prevent identifier breakout."""
        assert validate_oracle_identifier('table"name') == 'table""name'
        assert validate_oracle_identifier('a"b"c') == 'a""b""c'

    @pytest.mark.parametrize(
        "name",
        [
            "",
        ],
    )
    def test_invalid_identifiers(self, name):
        """Empty string is rejected."""
        with pytest.raises(ValueError, match="Invalid Oracle identifier"):
            validate_oracle_identifier(name)

    def test_none_raises(self):
        """None input raises (via falsy check)."""
        with pytest.raises((ValueError, TypeError)):
            validate_oracle_identifier(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Integration tests (require Oracle container)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_execute_sql_select_real(async_oracle_connection):
    """SELECT 1 FROM DUAL returns [(1,)] against a real database."""
    result = await execute_sql(async_oracle_connection, "SELECT 1 FROM DUAL")
    assert result == [(1,)]


@pytest.mark.db
async def test_execute_sql_ddl_create_drop(async_oracle_connection):
    """CREATE TABLE + DROP TABLE round-trip succeeds."""
    conn = async_oracle_connection
    table = "TEST_SQL_DDL_ROUNDTRIP"

    await execute_sql(conn, f"CREATE TABLE {table} (id NUMBER)")
    await conn.commit()

    # SELECT from the newly created table
    result = await execute_sql(conn, f"SELECT COUNT(*) FROM {table}")
    assert result == [(0,)]

    await execute_sql(conn, f"DROP TABLE {table} PURGE")
    await conn.commit()
