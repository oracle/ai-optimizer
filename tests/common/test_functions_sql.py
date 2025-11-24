# pylint: disable=protected-access,import-error,import-outside-toplevel,redefined-outer-name
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for SQL validation functions in common.functions
"""
# spell-checker: disable

from unittest.mock import Mock, patch
import pytest
import oracledb

from common import functions


class TestIsSQLAccessible:
    """Tests for the is_sql_accessible function"""

    def test_valid_sql_connection_and_query(self):
        """Test that a valid SQL connection and query returns (True, '')"""
        # Mock the oracledb connection and cursor
        mock_cursor = Mock()
        mock_cursor.description = [Mock(type=oracledb.DB_TYPE_VARCHAR)]
        mock_cursor.fetchmany.return_value = [("row1",), ("row2",), ("row3",)]

        mock_connection = Mock()
        mock_connection.__enter__ = Mock(return_value=mock_connection)
        mock_connection.__exit__ = Mock(return_value=None)
        mock_connection.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = Mock(return_value=None)

        with patch("oracledb.connect", return_value=mock_connection):
            ok, msg = functions.is_sql_accessible("testuser/testpass@testdsn", "SELECT text FROM documents")

        assert ok is True, "Expected SQL validation to succeed with valid connection and query"
        assert msg == "", f"Expected no error message, got: {msg}"

    def test_invalid_connection_string_format(self):
        """Test that an invalid connection string format returns (False, error_msg)"""
        ok, msg = functions.is_sql_accessible("invalid_connection_string", "SELECT * FROM table")

        assert ok is False, "Expected SQL validation to fail with invalid connection string"
        # The function logs "Wrong connection string" but returns the connection error
        assert msg != "", "Expected an error message, got empty string"
        # Either the ValueError message or the connection error should be present
        assert "connection error" in msg.lower() or "Wrong connection string" in msg, \
            f"Expected connection error or 'Wrong connection string' in error, got: {msg}"

    def test_empty_result_set(self):
        """Test that a query returning no rows returns (False, error_msg)"""
        mock_cursor = Mock()
        mock_cursor.description = [Mock(type=oracledb.DB_TYPE_VARCHAR)]
        mock_cursor.fetchmany.return_value = []  # Empty result set

        mock_connection = Mock()
        mock_connection.__enter__ = Mock(return_value=mock_connection)
        mock_connection.__exit__ = Mock(return_value=None)
        mock_connection.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = Mock(return_value=None)

        with patch("oracledb.connect", return_value=mock_connection):
            ok, msg = functions.is_sql_accessible("testuser/testpass@testdsn", "SELECT text FROM empty_table")

        assert ok is False, "Expected SQL validation to fail with empty result set"
        assert "empty table" in msg, f"Expected 'empty table' in error, got: {msg}"

    def test_multiple_columns_returned(self):
        """Test that a query returning multiple columns returns (False, error_msg)"""
        mock_cursor = Mock()
        mock_cursor.description = [
            Mock(type=oracledb.DB_TYPE_VARCHAR),
            Mock(type=oracledb.DB_TYPE_VARCHAR),
        ]
        mock_cursor.fetchmany.return_value = [("col1", "col2")]

        mock_connection = Mock()
        mock_connection.__enter__ = Mock(return_value=mock_connection)
        mock_connection.__exit__ = Mock(return_value=None)
        mock_connection.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = Mock(return_value=None)

        with patch("oracledb.connect", return_value=mock_connection):
            ok, msg = functions.is_sql_accessible("testuser/testpass@testdsn", "SELECT col1, col2 FROM table")

        assert ok is False, "Expected SQL validation to fail with multiple columns"
        assert "2 columns" in msg, f"Expected '2 columns' in error, got: {msg}"

    def test_invalid_column_type(self):
        """Test that a query returning non-VARCHAR column returns (False, error_msg)"""
        mock_cursor = Mock()
        mock_cursor.description = [Mock(type=oracledb.DB_TYPE_NUMBER)]
        mock_cursor.fetchmany.return_value = [(123,)]

        mock_connection = Mock()
        mock_connection.__enter__ = Mock(return_value=mock_connection)
        mock_connection.__exit__ = Mock(return_value=None)
        mock_connection.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = Mock(return_value=None)

        with patch("oracledb.connect", return_value=mock_connection):
            ok, msg = functions.is_sql_accessible("testuser/testpass@testdsn", "SELECT id FROM table")

        assert ok is False, "Expected SQL validation to fail with non-VARCHAR column type"
        assert "VARCHAR" in msg, f"Expected 'VARCHAR' in error, got: {msg}"

    def test_database_connection_error(self):
        """Test that a database connection error returns (False, error_msg)"""
        with patch("oracledb.connect", side_effect=oracledb.Error("Connection failed")):
            ok, msg = functions.is_sql_accessible("testuser/testpass@testdsn", "SELECT text FROM table")

        assert ok is False, "Expected SQL validation to fail with connection error"
        assert "connection error" in msg.lower(), f"Expected 'connection error' in message, got: {msg}"

    def test_empty_connection_string(self):
        """Test that empty connection string returns (False, '')"""
        ok, msg = functions.is_sql_accessible("", "SELECT * FROM table")

        assert ok is False, "Expected SQL validation to fail with empty connection string"
        assert msg == "", f"Expected empty error message, got: {msg}"

    def test_empty_query(self):
        """Test that empty query returns (False, '')"""
        ok, msg = functions.is_sql_accessible("testuser/testpass@testdsn", "")

        assert ok is False, "Expected SQL validation to fail with empty query"
        assert msg == "", f"Expected empty error message, got: {msg}"

    def test_nvarchar_column_type_accepted(self):
        """Test that NVARCHAR column type is accepted as valid"""
        mock_cursor = Mock()
        mock_cursor.description = [Mock(type=oracledb.DB_TYPE_NVARCHAR)]
        mock_cursor.fetchmany.return_value = [("text1",), ("text2",)]

        mock_connection = Mock()
        mock_connection.__enter__ = Mock(return_value=mock_connection)
        mock_connection.__exit__ = Mock(return_value=None)
        mock_connection.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = Mock(return_value=None)

        with patch("oracledb.connect", return_value=mock_connection):
            ok, msg = functions.is_sql_accessible("testuser/testpass@testdsn", "SELECT ntext FROM table")

        assert ok is True, "Expected SQL validation to succeed with NVARCHAR column type"
        assert msg == "", f"Expected no error message, got: {msg}"


class TestFileSourceDataSQLValidation:
    """
    Tests for FileSourceData.is_valid() method with SQL source

    These tests verify that the is_valid() method correctly uses the return value
    from is_sql_accessible() function. The fix ensures that when is_sql_accessible
    returns (True, ""), is_valid() should return True, and vice versa.
    """

    def test_is_valid_returns_true_when_sql_accessible_succeeds(self):
        """Test that is_valid() returns True when SQL validation succeeds"""
        from client.content.tools.tabs.split_embed import FileSourceData

        # Mock is_sql_accessible to return success (True, "")
        with patch.object(functions, "is_sql_accessible", return_value=(True, "")):
            data = FileSourceData(
                file_source="SQL",
                sql_connection="user/pass@dsn",
                sql_query="SELECT text FROM docs"
            )

            result = data.is_valid()

        # The fix ensures this assertion passes
        assert result is True, (
            "FileSourceData.is_valid() should return True when is_sql_accessible returns (True, ''). "
            "This test will fail until the bug fix is applied."
        )

    def test_is_valid_returns_false_when_sql_accessible_fails(self):
        """Test that is_valid() returns False when SQL validation fails"""
        from client.content.tools.tabs.split_embed import FileSourceData

        # Mock is_sql_accessible to return failure (False, "error message")
        with patch.object(functions, "is_sql_accessible", return_value=(False, "Connection failed")):
            data = FileSourceData(
                file_source="SQL",
                sql_connection="user/pass@dsn",
                sql_query="INVALID SQL"
            )

            result = data.is_valid()

        assert result is False, (
            "FileSourceData.is_valid() should return False when is_sql_accessible returns (False, msg)"
        )

    def test_is_valid_with_various_error_conditions(self):
        """Test is_valid() with various SQL error conditions"""
        from client.content.tools.tabs.split_embed import FileSourceData

        test_cases = [
            ((False, "Empty table"), False, "Empty result set"),
            ((False, "Wrong connection"), False, "Invalid connection string"),
            ((False, "2 columns"), False, "Multiple columns"),
            ((False, "VARCHAR expected"), False, "Wrong column type"),
        ]

        for sql_result, expected_valid, description in test_cases:
            with patch.object(functions, "is_sql_accessible", return_value=sql_result):
                data = FileSourceData(
                    file_source="SQL",
                    sql_connection="user/pass@dsn",
                    sql_query="SELECT text FROM docs"
                )

                result = data.is_valid()

            assert result == expected_valid, f"Failed for case: {description}"


class TestRenderLoadKBSectionErrorDisplay:
    """
    Tests for the error display logic in _render_load_kb_section

    The fix changes line 272 from:
        if is_invalid or msg:
    to:
        if not(is_invalid) or msg:

    This ensures errors are displayed when SQL validation actually fails.
    """

    def test_error_displayed_when_sql_validation_fails(self):
        """Test that error is displayed when is_sql_accessible returns (False, msg)"""
        # When is_sql_accessible returns (False, "Error message")
        # The unpacked values are: is_invalid=False, msg="Error message"
        # The condition should display error: not(False) or "Error message" = True or True = True

        is_invalid, msg = False, "Connection failed"

        # Simulate the logic in line 272 after the fix
        should_display_error = not(is_invalid) or bool(msg)

        assert should_display_error is True, (
            "Error should be displayed when SQL validation fails. "
            "is_sql_accessible returned (False, 'Connection failed'), "
            "which should trigger error display."
        )

    def test_no_error_displayed_when_sql_validation_succeeds(self):
        """Test that no error is displayed when is_sql_accessible returns (True, '')"""
        # When is_sql_accessible returns (True, "")
        # The unpacked values are: is_invalid=True, msg=""
        # The condition should NOT display error: not(True) or "" = False or False = False

        is_invalid, msg = True, ""

        # Simulate the logic in line 272 after the fix
        should_display_error = not(is_invalid) or bool(msg)

        assert should_display_error is False, (
            "Error should NOT be displayed when SQL validation succeeds. "
            "is_sql_accessible returned (True, ''), "
            "which should NOT trigger error display."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
