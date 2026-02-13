"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for common/functions.py

Tests utility functions for URL checking, vector store operations, and SQL operations.
"""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock
import requests
import oracledb

from common import functions


class TestIsUrlAccessible:
    """Tests for is_url_accessible function."""

    def test_empty_url_returns_false(self):
        """is_url_accessible should return False for empty URL."""
        result, msg = functions.is_url_accessible("")
        assert result is False
        assert msg == "No URL Provided"

    def test_none_url_returns_false(self):
        """is_url_accessible should return False for None URL."""
        result, msg = functions.is_url_accessible(None)
        assert result is False
        assert msg == "No URL Provided"

    @patch("common.functions.requests.get")
    def test_successful_200_response(self, mock_get):
        """is_url_accessible should return True for 200 response."""
        mock_get.return_value = MagicMock(status_code=200)

        result, msg = functions.is_url_accessible("http://example.com")

        assert result is True
        assert msg is None
        mock_get.assert_called_once_with("http://example.com", timeout=2)

    @patch("common.functions.requests.get")
    def test_successful_403_response(self, mock_get):
        """is_url_accessible should return True for 403 response (accessible but forbidden)."""
        mock_get.return_value = MagicMock(status_code=403)

        result, msg = functions.is_url_accessible("http://example.com")

        assert result is True
        assert msg is None

    @patch("common.functions.requests.get")
    def test_successful_404_response(self, mock_get):
        """is_url_accessible should return True for 404 response (server accessible)."""
        mock_get.return_value = MagicMock(status_code=404)

        result, msg = functions.is_url_accessible("http://example.com")

        assert result is True
        assert msg is None

    @patch("common.functions.requests.get")
    def test_successful_421_response(self, mock_get):
        """is_url_accessible should return True for 421 response."""
        mock_get.return_value = MagicMock(status_code=421)

        result, msg = functions.is_url_accessible("http://example.com")

        assert result is True
        assert msg is None

    @patch("common.functions.requests.get")
    def test_unsuccessful_500_response(self, mock_get):
        """is_url_accessible should return False for 500 response."""
        mock_get.return_value = MagicMock(status_code=500)

        result, msg = functions.is_url_accessible("http://example.com")

        assert result is False
        assert "not accessible" in msg
        assert "500" in msg

    @patch("common.functions.requests.get")
    def test_connection_error(self, mock_get):
        """is_url_accessible should return False for connection errors."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

        result, msg = functions.is_url_accessible("http://example.com")

        assert result is False
        assert "not accessible" in msg
        assert "ConnectionError" in msg

    @patch("common.functions.requests.get")
    def test_timeout_error(self, mock_get):
        """is_url_accessible should return False for timeout errors."""
        mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

        result, msg = functions.is_url_accessible("http://example.com")

        assert result is False
        assert "not accessible" in msg
        assert "Timeout" in msg


class TestGetVsTable:
    """Tests for get_vs_table function."""

    def test_basic_table_name_generation(self):
        """get_vs_table should generate correct table name."""
        table, comment = functions.get_vs_table(
            model="text-embedding-3-small",
            chunk_size=512,
            chunk_overlap=50,
            distance_metric="COSINE",
            index_type="HNSW",
        )

        assert table == "TEXT_EMBEDDING_3_SMALL_512_50_COSINE_HNSW"
        assert comment is not None

    def test_table_name_with_alias(self):
        """get_vs_table should include alias in table name."""
        table, _ = functions.get_vs_table(
            model="test-model",
            chunk_size=500,
            chunk_overlap=50,
            distance_metric="EUCLIDEAN_DISTANCE",
            alias="myalias",
        )

        assert table.startswith("MYALIAS_")
        assert "TEST_MODEL" in table

    def test_special_characters_replaced(self):
        """get_vs_table should replace special characters with underscores."""
        table, _ = functions.get_vs_table(
            model="openai/gpt-4",
            chunk_size=1000,
            chunk_overlap=100,
            distance_metric="COSINE",
        )

        assert "/" not in table
        assert "-" not in table
        assert "_" in table

    def test_chunk_overlap_ceiling(self):
        """get_vs_table should use ceiling for chunk_overlap."""
        table, comment = functions.get_vs_table(
            model="test",
            chunk_size=1000,
            chunk_overlap=99.5,
            distance_metric="COSINE",
        )

        assert "100" in table
        parsed_comment = json.loads(comment)
        assert parsed_comment["chunk_overlap"] == 100

    def test_comment_json_structure(self):
        """get_vs_table should generate valid JSON comment."""
        _, comment = functions.get_vs_table(
            model="test-model",
            chunk_size=1000,
            chunk_overlap=100,
            distance_metric="COSINE",
            index_type="HNSW",
            alias="test_alias",
            description="Test description",
        )

        parsed = json.loads(comment)
        assert parsed["alias"] == "test_alias"
        assert parsed["description"] == "Test description"
        assert parsed["model"] == "test-model"
        assert parsed["chunk_size"] == 1000
        assert parsed["chunk_overlap"] == 100
        assert parsed["distance_metric"] == "COSINE"
        assert parsed["index_type"] == "HNSW"

    def test_comment_null_description(self):
        """get_vs_table should include null description when not provided."""
        _, comment = functions.get_vs_table(
            model="test",
            chunk_size=1000,
            chunk_overlap=100,
            distance_metric="COSINE",
        )

        parsed = json.loads(comment)
        assert parsed["description"] is None

    def test_default_index_type(self):
        """get_vs_table should default to HNSW index type."""
        table, _ = functions.get_vs_table(
            model="test",
            chunk_size=1000,
            chunk_overlap=100,
            distance_metric="COSINE",
        )

        assert "HNSW" in table

    def test_missing_required_values_returns_none(self):
        """get_vs_table should return None for missing required values."""
        table, comment = functions.get_vs_table(
            model=None,
            chunk_size=None,
            chunk_overlap=None,
            distance_metric=None,
        )

        assert table is None
        assert comment is None


class TestParseVsComment:
    """Tests for parse_vs_comment function."""

    def test_empty_comment_returns_defaults(self):
        """parse_vs_comment should return defaults for empty comment."""
        result = functions.parse_vs_comment("")

        assert result["alias"] is None
        assert result["description"] is None
        assert result["model"] is None
        assert result["parse_status"] == "no_comment"

    def test_none_comment_returns_defaults(self):
        """parse_vs_comment should return defaults for None comment."""
        result = functions.parse_vs_comment(None)

        assert result["parse_status"] == "no_comment"

    def test_valid_json_comment(self):
        """parse_vs_comment should parse valid JSON comment."""
        comment = json.dumps({
            "alias": "test_alias",
            "description": "Test description",
            "model": "test-model",
            "chunk_size": 1000,
            "chunk_overlap": 100,
            "distance_metric": "COSINE",
            "index_type": "HNSW",
        })

        result = functions.parse_vs_comment(comment)

        assert result["alias"] == "test_alias"
        assert result["description"] == "Test description"
        assert result["model"] == "test-model"
        assert result["chunk_size"] == 1000
        assert result["chunk_overlap"] == 100
        assert result["distance_metric"] == "COSINE"
        assert result["index_type"] == "HNSW"
        assert result["parse_status"] == "success"

    def test_genai_prefix_stripped(self):
        """parse_vs_comment should strip 'GENAI: ' prefix."""
        comment = 'GENAI: {"alias": "test", "model": "test-model"}'

        result = functions.parse_vs_comment(comment)

        assert result["alias"] == "test"
        assert result["model"] == "test-model"
        assert result["parse_status"] == "success"

    def test_missing_description_backward_compat(self):
        """parse_vs_comment should handle missing description for backward compatibility."""
        comment = json.dumps({
            "alias": "test",
            "model": "test-model",
        })

        result = functions.parse_vs_comment(comment)

        assert result["description"] is None
        assert result["parse_status"] == "success"

    def test_invalid_json_returns_error(self):
        """parse_vs_comment should return error for invalid JSON."""
        result = functions.parse_vs_comment("not valid json")

        assert "parse_error" in result["parse_status"]


class TestIsSqlAccessible:
    """Tests for is_sql_accessible function."""

    def test_empty_connection_returns_false(self):
        """is_sql_accessible should return False for empty connection."""
        result, _ = functions.is_sql_accessible("", "SELECT 1")
        assert result is False

    def test_empty_query_returns_false(self):
        """is_sql_accessible should return False for empty query."""
        result, _ = functions.is_sql_accessible("user/pass@dsn", "")
        assert result is False

    def test_invalid_connection_string_format(self):
        """is_sql_accessible should handle invalid connection string format."""
        result, msg = functions.is_sql_accessible("invalid_format", "SELECT 1")

        assert result is False
        # The function may fail at connection string parsing or at actual connection
        assert msg is not None

    @patch("common.functions.oracledb.connect")
    def test_database_error(self, mock_connect):
        """is_sql_accessible should return False for database errors."""
        mock_connect.side_effect = oracledb.Error("Connection failed")

        result, msg = functions.is_sql_accessible("user/pass@localhost/db", "SELECT 1")

        assert result is False
        assert "connection error" in msg

    @patch("common.functions.oracledb.connect")
    def test_empty_result_returns_false(self, mock_connect):
        """is_sql_accessible should return False when query returns no rows."""
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = []
        mock_cursor.description = [("COL1", oracledb.DB_TYPE_VARCHAR, None, None, None, None, None)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        result, msg = functions.is_sql_accessible("user/pass@localhost/db", "SELECT col FROM table")

        assert result is False
        assert "empty table" in msg

    @patch("common.functions.oracledb.connect")
    def test_multiple_columns_returns_false(self, mock_connect):
        """is_sql_accessible should return False when query returns multiple columns."""
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.return_value = [("value1", "value2")]
        mock_cursor.description = [
            ("COL1", oracledb.DB_TYPE_VARCHAR, None, None, None, None, None),
            ("COL2", oracledb.DB_TYPE_VARCHAR, None, None, None, None, None),
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        result, msg = functions.is_sql_accessible("user/pass@localhost/db", "SELECT col1, col2 FROM table")

        assert result is False
        assert "returns 2 columns" in msg

    @patch("common.functions.oracledb.connect")
    def test_valid_sql_connection_and_query(self, mock_connect):
        """is_sql_accessible should return True for valid connection and query."""
        mock_cursor = MagicMock()
        mock_cursor.description = [MagicMock(type=oracledb.DB_TYPE_VARCHAR)]
        mock_cursor.fetchmany.return_value = [("row1",), ("row2",), ("row3",)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        result, msg = functions.is_sql_accessible("user/pass@localhost/db", "SELECT text FROM documents")

        assert result is True
        assert msg == ""

    @patch("common.functions.oracledb.connect")
    def test_invalid_column_type_returns_false(self, mock_connect):
        """is_sql_accessible should return False for non-VARCHAR column type."""
        mock_cursor = MagicMock()
        mock_cursor.description = [MagicMock(type=oracledb.DB_TYPE_NUMBER)]
        mock_cursor.fetchmany.return_value = [(123,)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        result, msg = functions.is_sql_accessible("user/pass@localhost/db", "SELECT id FROM table")

        assert result is False
        assert "VARCHAR" in msg

    @patch("common.functions.oracledb.connect")
    def test_nvarchar_column_type_accepted(self, mock_connect):
        """is_sql_accessible should accept NVARCHAR column type as valid."""
        mock_cursor = MagicMock()
        mock_cursor.description = [MagicMock(type=oracledb.DB_TYPE_NVARCHAR)]
        mock_cursor.fetchmany.return_value = [("text1",), ("text2",)]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        result, msg = functions.is_sql_accessible("user/pass@localhost/db", "SELECT ntext FROM table")

        assert result is True
        assert msg == ""


class TestRunSqlQuery:
    """Tests for run_sql_query function."""

    def test_empty_connection_returns_false(self):
        """run_sql_query should return False for empty connection."""
        result = functions.run_sql_query("", "SELECT 1", "/tmp")
        assert result is False

    def test_invalid_connection_string_format(self):
        """run_sql_query should return False for invalid connection string."""
        result = functions.run_sql_query("invalid_format", "SELECT 1", "/tmp")
        assert result is False

    @patch("common.functions.oracledb.connect")
    def test_database_error_returns_empty(self, mock_connect):
        """run_sql_query should return empty string for database errors."""
        mock_connect.side_effect = oracledb.Error("Connection failed")

        result = functions.run_sql_query("user/pass@localhost/db", "SELECT 1", "/tmp")

        assert result == ""

    @patch("common.functions.oracledb.connect")
    def test_successful_query_creates_csv(self, mock_connect):
        """run_sql_query should create CSV file with query results."""
        mock_cursor = MagicMock()
        mock_cursor.description = [
            ("COL1", None, None, None, None, None, None),
            ("COL2", None, None, None, None, None, None),
        ]
        mock_cursor.fetchmany.side_effect = [
            [("val1", "val2"), ("val3", "val4")],
            [],  # Second call returns empty to end loop
        ]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = functions.run_sql_query("user/pass@localhost/db", "SELECT * FROM table", tmpdir)

            assert result.endswith(".csv")
            assert os.path.exists(result)

            with open(result, "r", encoding="utf-8") as f:
                content = f.read()
                assert "COL1,COL2" in content
                assert "val1,val2" in content
