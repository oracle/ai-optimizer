"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch, MagicMock

import pytest
import oracledb

from server.api.utils import databases
from server.api.utils.databases import DbException
from common.schema import Database


class TestDbException:
    """Test custom database exception class"""

    def test_db_exception_initialization(self):
        """Test DbException initialization"""
        exc = DbException(status_code=500, detail="Database error")
        assert exc.status_code == 500
        assert exc.detail == "Database error"
        assert str(exc) == "Database error"


class TestDatabaseUtilsPrivateFunctions:
    """Test private utility functions"""

    def setup_method(self):
        """Setup test data"""
        self.sample_database = Database(name="test_db", user="test_user", password="test_password", dsn="test_dsn")

    @patch("oracledb.Connection")
    def test_test_function_success(self, mock_connection):
        """Test successful database connection test"""
        mock_connection.ping.return_value = None
        self.sample_database.set_connection(mock_connection)

        databases._test(self.sample_database)

        assert self.sample_database.connected is True
        mock_connection.ping.assert_called_once()

    @patch("oracledb.Connection")
    @patch("server.api.utils.databases.connect")
    def test_test_function_reconnect(self, mock_connect, mock_connection):
        """Test database reconnection when ping fails"""
        mock_connection.ping.side_effect = oracledb.DatabaseError("Connection lost")
        self.sample_database.set_connection(mock_connection)

        databases._test(self.sample_database)

        mock_connect.assert_called_once_with(self.sample_database)

    @patch("oracledb.Connection")
    def test_test_function_permission_error(self, mock_connection):
        """Test handling of permission errors"""
        mock_connection.ping.side_effect = PermissionError("Access denied")
        self.sample_database.set_connection(mock_connection)

        with pytest.raises(DbException) as exc_info:
            databases._test(self.sample_database)

        assert exc_info.value.status_code == 401
        assert "Database: Access denied" in str(exc_info.value)

    @patch("oracledb.Connection")
    def test_test_function_connection_error(self, mock_connection):
        """Test handling of connection errors"""
        mock_connection.ping.side_effect = ConnectionError("Connection failed")
        self.sample_database.set_connection(mock_connection)

        with pytest.raises(DbException) as exc_info:
            databases._test(self.sample_database)

        assert exc_info.value.status_code == 503
        assert "Database: Connection failed" in str(exc_info.value)

    @patch("server.api.utils.databases.execute_sql")
    def test_get_vs(self, mock_execute_sql):
        """Test vector storage retrieval"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = [
            (
                "TEST_TABLE",
                '{"alias": "test_alias", "model": "test_model", "chunk_size": 1000, "distance_metric": "COSINE"}',
            )
        ]

        result = databases._get_vs(mock_connection)

        assert len(result) == 1
        assert result[0].vector_store == "TEST_TABLE"
        assert result[0].alias == "test_alias"
        assert result[0].model == "test_model"
        assert result[0].chunk_size == 1000
        assert result[0].distance_metric == "COSINE"

    @patch("server.api.utils.databases.execute_sql")
    def test_selectai_enabled_true(self, mock_execute_sql):
        """Test SelectAI enabled check returns True"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = [(3,)]

        result = databases._selectai_enabled(mock_connection)

        assert result is True

    @patch("server.api.utils.databases.execute_sql")
    def test_selectai_enabled_false(self, mock_execute_sql):
        """Test SelectAI enabled check returns False"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = [(2,)]

        result = databases._selectai_enabled(mock_connection)

        assert result is False

    @patch("server.api.utils.databases.execute_sql")
    def test_get_selectai_profiles(self, mock_execute_sql):
        """Test SelectAI profiles retrieval"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = [("PROFILE1",), ("PROFILE2",)]

        result = databases._get_selectai_profiles(mock_connection)

        assert result == ["PROFILE1", "PROFILE2"]

    @patch("server.api.utils.databases.execute_sql")
    def test_get_selectai_profiles_empty(self, mock_execute_sql):
        """Test SelectAI profiles retrieval with no profiles"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = []

        result = databases._get_selectai_profiles(mock_connection)

        assert result == []


class TestDatabaseUtilsPublicFunctions:
    """Test public utility functions"""

    def setup_method(self):
        """Setup test data"""
        self.sample_database = Database(name="test_db", user="test_user", password="test_password", dsn="test_dsn")

    @patch("oracledb.connect")
    def test_connect_success(self, mock_connect):
        """Test successful database connection"""
        mock_connection = MagicMock()
        mock_connect.return_value = mock_connection

        result = databases.connect(self.sample_database)

        assert result == mock_connection
        mock_connect.assert_called_once()

    def test_connect_missing_details(self):
        """Test connection with missing required details"""
        incomplete_db = Database(
            name="test_db",
            user="test_user",
            password="",  # Missing password
            dsn="test_dsn",
        )

        with pytest.raises(ValueError, match="missing connection details"):
            databases.connect(incomplete_db)

    @patch("oracledb.connect")
    def test_connect_with_wallet(self, mock_connect):
        """Test connection with wallet configuration"""
        db_with_wallet = Database(
            name="test_db",
            user="test_user",
            password="test_password",
            dsn="test_dsn",
            wallet_password="wallet_pass",
            config_dir="/path/to/config",
        )
        mock_connection = MagicMock()
        mock_connect.return_value = mock_connection

        result = databases.connect(db_with_wallet)

        assert result == mock_connection
        mock_connect.assert_called_once()

    @patch("oracledb.connect")
    def test_connect_permission_error(self, mock_connect):
        """Test connection with permission error"""
        mock_error = MagicMock()
        mock_error.full_code = "ORA-01017"
        mock_error.message = "invalid username/password"
        # Create a proper DatabaseError with the mock error in args
        mock_connect.side_effect = oracledb.DatabaseError(mock_error)

        with pytest.raises(PermissionError, match="invalid username/password"):
            databases.connect(self.sample_database)

    @patch("oracledb.connect")
    def test_connect_connection_error(self, mock_connect):
        """Test connection with connection error"""
        mock_error = MagicMock()
        mock_error.full_code = "DPY-6005"
        mock_error.message = "cannot connect to database"
        mock_connect.side_effect = oracledb.DatabaseError(mock_error)

        with pytest.raises(ConnectionError, match="cannot connect to database"):
            databases.connect(self.sample_database)

    @patch("oracledb.connect")
    def test_connect_lookup_error(self, mock_connect):
        """Test connection with lookup error"""
        mock_error = MagicMock()
        mock_error.full_code = "DPY-4000"
        mock_error.message = "invalid connect string"
        mock_connect.side_effect = oracledb.DatabaseError(mock_error)

        with pytest.raises(LookupError, match="invalid connect string"):
            databases.connect(self.sample_database)

    def test_disconnect(self):
        """Test database disconnection"""
        mock_connection = MagicMock()
        mock_connection.close.return_value = None

        result = databases.disconnect(mock_connection)

        assert result is None
        mock_connection.close.assert_called_once()

    def test_execute_sql_success(self):
        """Test successful SQL execution"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = [("row1",), ("row2",)]

        result = databases.execute_sql(mock_connection, "SELECT * FROM test_table")

        assert result == [("row1",), ("row2",)]
        mock_cursor.execute.assert_called_once_with("SELECT * FROM test_table", None)

    def test_execute_sql_with_binds(self):
        """Test SQL execution with bind variables"""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = [("row1",)]

        binds = {"name": "test"}
        result = databases.execute_sql(mock_connection, "SELECT * FROM test WHERE name = :name", binds)

        assert result == [("row1",)]
        mock_cursor.execute.assert_called_once_with("SELECT * FROM test WHERE name = :name", binds)

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(databases, "logger")
        assert databases.logger.name == "api.utils.database"
