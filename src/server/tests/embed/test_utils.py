"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.embed.utils.
"""
# spell-checker: disable

import csv
from unittest.mock import MagicMock, patch

import oracledb
import pytest

from server.app.database.schemas import DatabaseConfig
from server.app.embed.utils import _run_sql_query_sync, run_sql_query

MODULE = "server.app.embed.utils"

pytestmark = [pytest.mark.unit]


def _make_db_config(**overrides) -> DatabaseConfig:
    defaults = {"alias": "TEST", "username": "test", "password": "test", "dsn": "test:1521/pdb"}
    return DatabaseConfig(**{**defaults, **overrides})


def _make_mock_connection(description, rows_batches):
    """Build a mock connection with cursor returning given description and row batches.

    Args:
        description: cursor.description value (list of tuples or None).
        rows_batches: list of lists; each is returned by successive fetchmany calls.
    """
    mock_cursor = MagicMock()
    mock_cursor.description = description
    mock_cursor.fetchmany = MagicMock(side_effect=rows_batches)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# _run_sql_query_sync
# ---------------------------------------------------------------------------


class TestSqlQueryValidation:
    """Test SELECT-only query restriction."""

    @pytest.mark.parametrize(
        "query",
        [
            "INSERT INTO t VALUES (1)",
            "DELETE FROM t WHERE id = 1",
            "DROP TABLE t PURGE",
            "UPDATE t SET x = 1",
            "CREATE TABLE t (id INT)",
            "  DROP TABLE t",
            "TRUNCATE TABLE t",
            "/* comment */ DROP TABLE t",
            "-- comment\nINSERT INTO t VALUES (1)",
            "WITH cte AS (SELECT 1 FROM dual) DELETE FROM t",
            "WITH cte AS (SELECT 1 FROM dual) INSERT INTO t SELECT * FROM cte",
            "WITH cte AS (SELECT 1 FROM dual) UPDATE t SET x = 1",
            "WITH cte AS (SELECT 1 FROM dual) MERGE INTO t USING cte ON (1=1) WHEN MATCHED THEN UPDATE SET x=1",
            "(DELETE FROM t)",
        ],
    )
    def test_non_select_queries_rejected(self, tmp_path, query):
        """Non-SELECT/WITH queries raise ValueError."""
        with pytest.raises(ValueError, match="Only SELECT queries are permitted"):
            _run_sql_query_sync(_make_db_config(), query, str(tmp_path))

    @pytest.mark.parametrize(
        "query",
        [
            "SELECT * FROM t",
            "  SELECT 1 FROM DUAL",
            "WITH cte AS (SELECT 1) SELECT * FROM cte",
            "select lower_case FROM t",
            "with recursive_cte AS (SELECT 1) SELECT * FROM recursive_cte",
            "/*+ parallel(4) */ SELECT * FROM t",
            "/* comment */ SELECT 1 FROM DUAL",
            "-- leading comment\nSELECT * FROM t",
            "/*+ hint */ WITH cte AS (SELECT 1) SELECT * FROM cte",
            "SELECT*FROM employees",
            "SELECT(1)FROM dual",
            "SELECT 'INSERT INTO t' FROM dual",
            "SELECT 'DELETE' FROM t WHERE col = 'UPDATE'",
            "WITH cte AS (SELECT 1) SELECT 'INSERT INTO t' FROM cte",
            "SELECT 'It''s a DELETE' FROM dual",
            "WITH cte AS (SELECT 'x''y' FROM t) SELECT 'z' FROM cte",
            "(SELECT 1 FROM dual) UNION ALL SELECT 2 FROM dual",
            "((SELECT 1 FROM dual))",
        ],
    )
    def test_select_and_with_queries_allowed(self, tmp_path, query):
        """SELECT and WITH queries pass validation (may still fail at DB level)."""
        description = [("COL_A",)]
        rows = [[(1,)], []]
        mock_conn, _ = _make_mock_connection(description, rows)

        with patch(f"{MODULE}.create_sync_connection") as mock_create:
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = _run_sql_query_sync(_make_db_config(), query, str(tmp_path))

        assert result.endswith(".csv")


class TestRunSqlQuerySync:
    """Test synchronous SQL query execution and CSV generation."""

    def test_successful_query_writes_csv(self, tmp_path):
        """Successful query generates a CSV file with headers and data."""
        description = [("COL_A",), ("COL_B",)]
        rows = [[(1, "hello"), (2, "world")], []]
        mock_conn, _ = _make_mock_connection(description, rows)

        with patch(f"{MODULE}.create_sync_connection") as mock_create:
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = _run_sql_query_sync(_make_db_config(), "SELECT 1", str(tmp_path))

        assert result.endswith(".csv")
        with open(result, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == ["COL_A", "COL_B"]
            data = list(reader)
            assert len(data) == 2
            assert data[0] == ["1", "hello"]

    def test_no_description_returns_empty_string(self, tmp_path):
        """Query with no cursor description returns empty string."""
        mock_conn, _ = _make_mock_connection(None, [])

        with patch(f"{MODULE}.create_sync_connection") as mock_create:
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = _run_sql_query_sync(_make_db_config(), "SELECT 1 FROM DUAL", str(tmp_path))

        assert result == ""

    def test_oracledb_error_returns_empty_string(self, tmp_path):
        """oracledb.Error during connection returns empty string."""
        with patch(f"{MODULE}.create_sync_connection") as mock_create:
            mock_create.return_value.__enter__ = MagicMock(side_effect=oracledb.Error("connection failed"))
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = _run_sql_query_sync(_make_db_config(), "SELECT 1", str(tmp_path))

        assert result == ""

    def test_batch_fetching(self, tmp_path):
        """Multiple batches of rows are all written to CSV."""
        description = [("ID",)]
        batch1 = [(i,) for i in range(100)]
        batch2 = [(i,) for i in range(100, 150)]
        rows = [batch1, batch2, []]
        mock_conn, _ = _make_mock_connection(description, rows)

        with patch(f"{MODULE}.create_sync_connection") as mock_create:
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = _run_sql_query_sync(_make_db_config(), "SELECT id FROM t", str(tmp_path))

        with open(result, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            data = list(reader)
            assert len(data) == 150

    def test_arraysize_set_to_batch_size(self, tmp_path):
        """cursor.arraysize is set to the batch_size (100)."""
        description = [("ID",)]
        mock_conn, mock_cursor = _make_mock_connection(description, [[], []])

        with patch(f"{MODULE}.create_sync_connection") as mock_create:
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            _run_sql_query_sync(_make_db_config(), "SELECT 1", str(tmp_path))

        assert mock_cursor.arraysize == 100

    def test_sets_transaction_read_only_before_user_query(self, tmp_path):
        """Defense-in-depth: SET TRANSACTION READ ONLY runs before the user query.

        Oracle blocks any DML/DDL in a read-only transaction (ORA-01456 / ORA-01453),
        which closes the residual side-effect-via-PL/SQL-function vector that the
        SELECT-only allow-list cannot detect.
        """
        description = [("COL_A",)]
        rows = [[(1,)], []]
        mock_conn, mock_cursor = _make_mock_connection(description, rows)

        with patch(f"{MODULE}.create_sync_connection") as mock_create:
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            _run_sql_query_sync(_make_db_config(), "SELECT * FROM t", str(tmp_path))

        executed = [c.args[0] for c in mock_cursor.execute.call_args_list]
        assert executed[0] == "SET TRANSACTION READ ONLY"
        assert "SELECT * FROM t" in executed[1:]
        assert executed.index("SET TRANSACTION READ ONLY") < executed.index("SELECT * FROM t")

    def test_oracledb_error_during_user_query_returns_empty_string(self, tmp_path):
        """oracledb.Error raised by the user query (e.g. ORA-01456 from a function
        attempting DML in the read-only transaction) returns empty string."""
        description = [("COL_A",)]
        mock_conn, mock_cursor = _make_mock_connection(description, [])
        mock_cursor.execute = MagicMock(
            side_effect=[None, oracledb.Error("ORA-01456: may not perform insert/delete/update operation")]
        )

        with patch(f"{MODULE}.create_sync_connection") as mock_create:
            mock_create.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)

            result = _run_sql_query_sync(
                _make_db_config(), "SELECT my_pkg.do_dml() FROM dual", str(tmp_path)
            )

        assert result == ""


# ---------------------------------------------------------------------------
# run_sql_query (async wrapper)
# ---------------------------------------------------------------------------


class TestRunSqlQuery:
    """Test async wrapper for SQL query execution."""

    @pytest.mark.anyio
    async def test_async_wrapper_delegates_to_sync(self, tmp_path):
        """Async wrapper calls _run_sql_query_sync in a thread."""
        expected_path = "/tmp/result.csv"
        with patch(f"{MODULE}._run_sql_query_sync", return_value=expected_path) as mock_sync:
            db_config = _make_db_config()
            result = await run_sql_query(db_config, "SELECT 1", str(tmp_path))

        assert result == expected_path
        mock_sync.assert_called_once_with(db_config, "SELECT 1", str(tmp_path))
