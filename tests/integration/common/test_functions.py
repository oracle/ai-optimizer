"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for common/functions.py

Tests functions that interact with external systems (URLs, databases).
These tests may require network access or database connectivity.
"""
# spell-checker: disable
# pylint: disable=protected-access,import-error,import-outside-toplevel

import os
import tempfile

import pytest
from db_fixtures import TEST_DB_CONFIG

from common import functions


class TestIsUrlAccessibleIntegration:
    """Integration tests for is_url_accessible function."""

    @pytest.mark.integration
    def test_real_accessible_url(self):
        """is_url_accessible should return True for known accessible URLs."""
        # Using example.com - IANA-maintained domain specifically for testing/documentation
        result, msg = functions.is_url_accessible("https://example.com")

        assert result is True
        assert msg is None

    @pytest.mark.integration
    def test_real_inaccessible_url(self):
        """is_url_accessible should return False for non-existent URLs."""
        result, msg = functions.is_url_accessible("https://this-domain-does-not-exist-xyz123.com")

        assert result is False
        assert msg is not None


class TestGetVsTableIntegration:
    """Integration tests for get_vs_table function."""

    def test_roundtrip_table_comment(self):
        """get_vs_table output should be parseable by parse_vs_comment."""
        _, comment = functions.get_vs_table(
            model="cohere-embed-english-v3",
            chunk_size=2048,
            chunk_overlap=256,
            distance_metric="DOT_PRODUCT",
            index_type="IVF",
            alias="integration_alias",
            description="Integration test description",
        )

        # Parse the generated comment
        parsed = functions.parse_vs_comment(comment)

        assert parsed["parse_status"] == "success"
        assert parsed["alias"] == "integration_alias"
        assert parsed["description"] == "Integration test description"
        assert parsed["model"] == "cohere-embed-english-v3"
        assert parsed["chunk_size"] == 2048
        assert parsed["chunk_overlap"] == 256
        assert parsed["distance_metric"] == "DOT_PRODUCT"
        assert parsed["index_type"] == "IVF"

    def test_roundtrip_with_genai_prefix(self):
        """parse_vs_comment should handle GENAI prefix correctly."""
        _, comment = functions.get_vs_table(
            model="test-model",
            chunk_size=500,
            chunk_overlap=50,
            distance_metric="DOT_PRODUCT",
            index_type="IVF",
            alias="test",
        )

        # Add GENAI prefix as it would be stored in database
        prefixed_comment = f"GENAI: {comment}"

        parsed = functions.parse_vs_comment(prefixed_comment)

        assert parsed["parse_status"] == "success"
        assert parsed["alias"] == "test"
        assert parsed["model"] == "test-model"

    def test_table_name_uniqueness(self):
        """Different parameters should generate different table names."""
        table1, _ = functions.get_vs_table(
            model="model-a",
            chunk_size=1000,
            chunk_overlap=100,
            distance_metric="COSINE",
        )

        table2, _ = functions.get_vs_table(
            model="model-b",
            chunk_size=1000,
            chunk_overlap=100,
            distance_metric="COSINE",
        )

        table3, _ = functions.get_vs_table(
            model="model-a",
            chunk_size=500,
            chunk_overlap=100,
            distance_metric="COSINE",
        )

        assert table1 != table2
        assert table1 != table3
        assert table2 != table3


class TestDatabaseFunctionsIntegration:
    """Integration tests for database functions.

    These tests are marked with db_container to indicate they require
    a real database connection.
    """

    @pytest.mark.db_container
    def test_is_sql_accessible_with_real_database(self, db_container):
        """is_sql_accessible should return True for valid database and query."""
        # pylint: disable=unused-argument
        # Connection string format: username/password@dsn
        db_conn = f"{TEST_DB_CONFIG['db_username']}/{TEST_DB_CONFIG['db_password']}@{TEST_DB_CONFIG['db_dsn']}"
        # Must use VARCHAR2 - the function checks column type is VARCHAR, not CHAR
        query = "SELECT CAST('test' AS VARCHAR2(10)) FROM dual"

        result, msg = functions.is_sql_accessible(db_conn, query)

        assert result is True
        assert msg == ""

    @pytest.mark.db_container
    def test_is_sql_accessible_invalid_credentials(self, db_container):
        """is_sql_accessible should return False for invalid credentials."""
        # pylint: disable=unused-argument
        db_conn = f"INVALID_USER/INVALID_PASSWORD@{TEST_DB_CONFIG['db_dsn']}"
        query = "SELECT 'test' FROM dual"

        result, msg = functions.is_sql_accessible(db_conn, query)

        assert result is False
        assert "error" in msg.lower()

    @pytest.mark.db_container
    def test_is_sql_accessible_wrong_column_count(self, db_container):
        """is_sql_accessible should return False when query returns multiple columns."""
        # pylint: disable=unused-argument
        db_conn = f"{TEST_DB_CONFIG['db_username']}/{TEST_DB_CONFIG['db_password']}@{TEST_DB_CONFIG['db_dsn']}"
        query = "SELECT 'a', 'b' FROM dual"  # Two columns - should fail

        result, msg = functions.is_sql_accessible(db_conn, query)

        assert result is False
        assert "columns" in msg.lower()

    @pytest.mark.db_container
    def test_run_sql_query_with_real_database(self, db_container):
        """run_sql_query should execute SQL and save results to CSV."""
        # pylint: disable=unused-argument
        db_conn = f"{TEST_DB_CONFIG['db_username']}/{TEST_DB_CONFIG['db_password']}@{TEST_DB_CONFIG['db_dsn']}"
        query = "SELECT 'value1' AS col1, 'value2' AS col2 FROM dual"

        with tempfile.TemporaryDirectory() as tmpdir:
            result = functions.run_sql_query(db_conn, query, tmpdir)

            # Should return the file path
            assert result is not False
            assert result.endswith(".csv")

            # File should exist and contain data
            assert os.path.exists(result)
            with open(result, encoding="utf-8") as f:
                content = f.read()
                assert "COL1" in content or "col1" in content.lower()
                assert "value1" in content

    @pytest.mark.db_container
    def test_run_sql_query_invalid_connection(self, db_container):
        """run_sql_query should return falsy value for invalid connection."""
        # pylint: disable=unused-argument
        db_conn = f"INVALID_USER/INVALID_PASSWORD@{TEST_DB_CONFIG['db_dsn']}"
        query = "SELECT 'test' FROM dual"

        with tempfile.TemporaryDirectory() as tmpdir:
            result = functions.run_sql_query(db_conn, query, tmpdir)

            # Function returns '' or False on error
            assert not result
