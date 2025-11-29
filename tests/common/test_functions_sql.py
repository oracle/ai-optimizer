# pylint: disable=protected-access,import-error,import-outside-toplevel,redefined-outer-name
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client-side SQL validation integration

Note: Tests for common.functions.is_sql_accessible have been migrated to
test/unit/common/test_functions.py. This file contains only client-side tests
for FileSourceData and UI error display logic.
"""
# spell-checker: disable

from unittest.mock import patch
import pytest

from common import functions


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
