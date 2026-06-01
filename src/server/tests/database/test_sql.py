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
    validate_vs_table_name,
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
# validate_vs_table_name (strict — defense in depth for COMMENT ON / DDL)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateVsTableName:
    """``\\w+`` validator for vector-store table names — matches the output of
    ``generate_vs_metadata`` (Unicode ``re.sub(r"\\W", "_", ...)``) so legacy
    non-ASCII auto-generated stores remain operable, while every SQL
    metacharacter (quotes, whitespace, ``;``, ``--``, parens) is still rejected.
    """

    @pytest.mark.parametrize(
        "name",
        [
            # Auto-generated names from the current generator
            "MY_TABLE",
            "VS_TMP",
            "OPENAI_TEXT_EMBEDDING_3_SMALL_1000_100_COSINE_HNSW",
            "MY_STORE_OCI_EMBED_V3_500_50_DOT_PRODUCT_HNSW_TMP",
            "A",
            "TBL_123",
            "_LEADING_UNDERSCORE",
            # Legacy auto-generated names that must remain droppable / editable.
            "CAFÉ_OPENAI_EMBED_HNSW",
            "ДОКА_OPENAI_EMBED_HNSW",
            "文档_OPENAI_EMBED_HNSW",
            # Lowercase / mixed-case forms come back from discover_vector_stores
            # if a table was created with a quoted lowercase identifier.
            "lowercase",
            "Mixed_Case",
        ],
    )
    def test_accepts_word_chars(self, name):
        """``\\w+`` names — including legacy non-ASCII — round-trip unchanged."""
        assert validate_vs_table_name(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            # SQL metacharacter payloads
            "X IS 'x'--",
            "VS' OR '1'='1",
            "VS;DROP TABLE T",
            'table"name',
            'A"B',
            'A""B',
            # Whitespace and punctuation outside \w
            "has space",
            "with-hyphen",
            "with.dot",
            "semi;colon",
            "slash/path",
            "SYS$SESSION",
            "TEMP#1",
            "name with\nnewline",
            "name\twith\ttab",
            "parens(here)",
            # Newline-bearing names must be rejected even when the visible
            # prefix is otherwise identifier-shaped.
            "VS\n",
            "VS\r",
            "VS\r\n",
            "\nVS",
            "VS\nDROP TABLE T",
        ],
    )
    def test_rejects_sql_metacharacters(self, name):
        """Quotes, whitespace, ``;``, ``--``, parens, ``$``/``#``, and any
        leading/trailing line breaks are all rejected."""
        with pytest.raises(ValueError, match="Invalid vector store table name"):
            validate_vs_table_name(name)

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Invalid vector store table name"):
            validate_vs_table_name("")

    def test_rejects_none(self):
        with pytest.raises((ValueError, TypeError)):
            validate_vs_table_name(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Integration tests (require Oracle container)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.db
async def test_execute_sql_select_real(async_oracle_connection):
    """SELECT 1 FROM DUAL returns [(1,)] against a real database."""
    result = await execute_sql(async_oracle_connection, "SELECT 1 FROM DUAL")
    assert result == [(1,)]


@pytest.mark.integration
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
