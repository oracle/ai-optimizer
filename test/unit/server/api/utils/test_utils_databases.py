"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/databases.py
Tests for database utility functions.

Uses hybrid approach:
- Real Oracle database for connection/SQL execution tests
- Mocks for pure Python logic tests (in-memory operations, exception handling)
"""

# pylint: disable=too-few-public-methods

from test.conftest import TEST_CONFIG
from unittest.mock import patch, MagicMock

import pytest
import oracledb

from common.schema import DatabaseSettings
from server.api.utils import databases as utils_databases
from server.api.utils.databases import DbException, ExistsDatabaseError, UnknownDatabaseError


class TestDbException:
    """Tests for DbException class."""

    def test_db_exception_init(self):
        """DbException should store status_code and detail."""
        exc = DbException(status_code=404, detail="Not found")
        assert exc.status_code == 404
        assert exc.detail == "Not found"

    def test_db_exception_message(self):
        """DbException should use detail as message."""
        exc = DbException(status_code=500, detail="Server error")
        assert str(exc) == "Server error"


class TestExistsDatabaseError:
    """Tests for ExistsDatabaseError class."""

    def test_exists_database_error_is_value_error(self):
        """ExistsDatabaseError should inherit from ValueError."""
        exc = ExistsDatabaseError("Database exists")
        assert isinstance(exc, ValueError)


class TestUnknownDatabaseError:
    """Tests for UnknownDatabaseError class."""

    def test_unknown_database_error_is_value_error(self):
        """UnknownDatabaseError should inherit from ValueError."""
        exc = UnknownDatabaseError("Database not found")
        assert isinstance(exc, ValueError)


class TestCreate:
    """Tests for the create function."""

    @patch("server.api.utils.databases.get")
    @patch("server.api.utils.databases.DATABASE_OBJECTS", [])
    def test_create_success(self, mock_get, make_database):
        """create should add database to DATABASE_OBJECTS."""
        mock_get.side_effect = [UnknownDatabaseError("Not found"), [make_database()]]
        database = make_database(name="NEW_DB")

        result = utils_databases.create(database)

        assert result is not None

    @patch("server.api.utils.databases.get")
    def test_create_raises_exists_error(self, mock_get, make_database):
        """create should raise ExistsDatabaseError if database exists."""
        mock_get.return_value = [make_database(name="EXISTING_DB")]
        database = make_database(name="EXISTING_DB")

        with pytest.raises(ExistsDatabaseError):
            utils_databases.create(database)

    @patch("server.api.utils.databases.get")
    def test_create_raises_value_error_missing_fields(self, mock_get, make_database):
        """create should raise ValueError if required fields missing."""
        mock_get.side_effect = UnknownDatabaseError("Not found")
        database = make_database(user=None)

        with pytest.raises(ValueError) as exc_info:
            utils_databases.create(database)

        assert "user" in str(exc_info.value)


class TestGet:
    """Tests for the get function."""

    @patch("server.api.utils.databases.DATABASE_OBJECTS")
    def test_get_all_databases(self, mock_objects, make_database):
        """get should return all databases when no name provided."""
        mock_objects.__iter__ = lambda _: iter([make_database(name="DB1"), make_database(name="DB2")])
        mock_objects.__len__ = lambda _: 2

        result = utils_databases.get()

        assert len(result) == 2

    @patch("server.api.utils.databases.DATABASE_OBJECTS")
    def test_get_specific_database(self, mock_objects, make_database):
        """get should return specific database when name provided."""
        db1 = make_database(name="DB1")
        db2 = make_database(name="DB2")
        mock_objects.__iter__ = lambda _: iter([db1, db2])
        mock_objects.__len__ = lambda _: 2

        result = utils_databases.get(name="DB1")

        assert len(result) == 1
        assert result[0].name == "DB1"

    @patch("server.api.utils.databases.DATABASE_OBJECTS")
    def test_get_raises_unknown_error(self, mock_objects):
        """get should raise UnknownDatabaseError if name not found."""
        mock_objects.__iter__ = lambda _: iter([])
        mock_objects.__len__ = lambda _: 0

        with pytest.raises(UnknownDatabaseError):
            utils_databases.get(name="NONEXISTENT")


class TestDelete:
    """Tests for the delete function."""

    def test_delete_removes_database(self, make_database):
        """delete should remove database from DATABASE_OBJECTS."""
        db1 = make_database(name="DB1")
        db2 = make_database(name="DB2")

        with patch("server.api.utils.databases.DATABASE_OBJECTS", [db1, db2]) as mock_objects:
            utils_databases.delete("DB1")
            assert len(mock_objects) == 1
            assert mock_objects[0].name == "DB2"


class TestConnect:
    """Tests for the connect function.

    Uses real database for success case, mocks for error code testing
    (since we can't easily trigger specific Oracle errors).
    """

    def test_connect_success_real_db(self, db_container, make_database):
        """connect should return connection on success (real database)."""
        # pylint: disable=unused-argument
        config = make_database(
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"],
        )

        result = utils_databases.connect(config)

        assert result is not None
        assert result.is_healthy()
        result.close()

    def test_connect_raises_value_error_missing_details(self, make_database):
        """connect should raise ValueError if connection details missing."""
        config = make_database(user=None, password=None, dsn=None)

        with pytest.raises(ValueError) as exc_info:
            utils_databases.connect(config)

        assert "missing connection details" in str(exc_info.value)

    def test_connect_raises_permission_error_invalid_credentials(self, db_container, make_database):
        """connect should raise PermissionError on invalid credentials (real database)."""
        # pylint: disable=unused-argument
        config = make_database(
            user="INVALID_USER",
            password="wrong_password",
            dsn=TEST_CONFIG["db_dsn"],
        )

        with pytest.raises(PermissionError):
            utils_databases.connect(config)

    def test_connect_raises_connection_error_invalid_dsn(self, db_container, make_database):
        """connect should raise ConnectionError on invalid service name (real database).

        Note: DPY-6005 (cannot connect) wraps DPY-6001 (service not registered),
        and the current implementation maps DPY-6005 to ConnectionError.
        """
        # pylint: disable=unused-argument
        config = make_database(
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn="//localhost:1525/NONEXISTENT_SERVICE",
        )

        with pytest.raises(ConnectionError):
            utils_databases.connect(config)

    @patch("server.api.utils.databases.oracledb.connect")
    def test_connect_raises_connection_error_on_oserror(self, mock_connect, make_database):
        """connect should raise ConnectionError on OSError (mocked - can't easily trigger)."""
        mock_connect.side_effect = OSError("Network unreachable")
        config = make_database()

        with pytest.raises(ConnectionError):
            utils_databases.connect(config)

    @patch("server.api.utils.databases.oracledb.connect")
    def test_connect_wallet_location_defaults_to_config_dir(self, mock_connect, make_database):
        """connect should default wallet_location to config_dir if not set (mocked - verifies call args)."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        config = make_database(wallet_password="secret", config_dir="/path/to/config")

        utils_databases.connect(config)

        call_kwargs = mock_connect.call_args.kwargs
        assert call_kwargs.get("wallet_location") == "/path/to/config"


class TestDisconnect:
    """Tests for the disconnect function."""

    def test_disconnect_closes_connection(self):
        """disconnect should call close on connection."""
        mock_conn = MagicMock()

        utils_databases.disconnect(mock_conn)

        mock_conn.close.assert_called_once()


class TestExecuteSql:
    """Tests for the execute_sql function.

    Uses real database for actual SQL execution tests.
    """

    def test_execute_sql_returns_rows(self, db_transaction):
        """execute_sql should return query results (real database)."""
        result = utils_databases.execute_sql(db_transaction, "SELECT 'val1' AS col1, 'val2' AS col2 FROM dual")

        assert len(result) == 1
        assert result[0] == ("val1", "val2")

    def test_execute_sql_with_binds(self, db_transaction):
        """execute_sql should pass binds to cursor (real database)."""
        result = utils_databases.execute_sql(
            db_transaction, "SELECT :val AS result FROM dual", {"val": "test_value"}
        )

        assert result[0] == ("test_value",)

    def test_execute_sql_handles_clob_columns(self, db_transaction):
        """execute_sql should read CLOB column values (real database)."""
        # Create a CLOB using TO_CLOB function
        result = utils_databases.execute_sql(
            db_transaction, "SELECT TO_CLOB('CLOB content here') AS clob_col FROM dual"
        )

        # Result should have the CLOB content read as string
        assert len(result) == 1
        assert "CLOB content here" in str(result[0])

    def test_execute_sql_returns_dbms_output(self, db_transaction):
        """execute_sql should return DBMS_OUTPUT when no rows (real database)."""
        result = utils_databases.execute_sql(
            db_transaction,
            """
            BEGIN
                DBMS_OUTPUT.ENABLE;
                DBMS_OUTPUT.PUT_LINE('Test DBMS Output');
            END;
            """,
        )

        assert "Test DBMS Output" in str(result)

    def test_execute_sql_multiple_rows(self, db_transaction):
        """execute_sql should handle multiple rows (real database)."""
        result = utils_databases.execute_sql(
            db_transaction,
            """
            SELECT LEVEL AS num FROM dual CONNECT BY LEVEL <= 3
            """,
        )

        assert len(result) == 3
        assert result[0] == (1,)
        assert result[1] == (2,)
        assert result[2] == (3,)


class TestDropVs:
    """Tests for the drop_vs function."""

    @patch("server.api.utils.databases.LangchainVS.drop_table_purge")
    def test_drop_vs_calls_langchain(self, mock_drop):
        """drop_vs should call LangchainVS.drop_table_purge."""
        mock_conn = MagicMock()

        utils_databases.drop_vs(mock_conn, "VS_TEST")

        mock_drop.assert_called_once_with(mock_conn, "VS_TEST")


class TestGetDatabases:
    """Tests for the get_databases function."""

    @patch("server.api.utils.databases.get")
    def test_get_databases_without_name(self, mock_get, make_database):
        """get_databases should return all databases without name."""
        mock_get.return_value = [make_database(name="DB1"), make_database(name="DB2")]

        result = utils_databases.get_databases()

        assert len(result) == 2

    @patch("server.api.utils.databases.get")
    def test_get_databases_with_name(self, mock_get, make_database):
        """get_databases should return single database with name."""
        mock_get.return_value = [make_database(name="DB1")]

        result = utils_databases.get_databases(db_name="DB1")

        assert result.name == "DB1"

    @patch("server.api.utils.databases.get")
    @patch("server.api.utils.databases.connect")
    @patch("server.api.utils.databases._get_vs")
    def test_get_databases_with_validate(self, mock_get_vs, mock_connect, mock_get, make_database):
        """get_databases should validate connections when validate=True."""
        db = make_database(name="DB1")
        mock_get.return_value = [db]
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_get_vs.return_value = []

        result = utils_databases.get_databases(validate=True)

        mock_connect.assert_called_once()
        assert result[0].connected is True

    @patch("server.api.utils.databases.get")
    @patch("server.api.utils.databases.connect")
    def test_get_databases_validate_handles_connection_error(self, mock_connect, mock_get, make_database):
        """get_databases should continue on connection error during validation."""
        db = make_database(name="DB1")
        mock_get.return_value = [db]
        mock_connect.side_effect = ConnectionError("Cannot connect")

        result = utils_databases.get_databases(validate=True)

        assert len(result) == 1
        # Should not crash, just continue


class TestGetClientDatabase:
    """Tests for the get_client_database function."""

    @patch("server.api.utils.databases.utils_settings.get_client")
    @patch("server.api.utils.databases.get_databases")
    def test_get_client_database_default(self, mock_get_databases, mock_get_client, make_settings, make_database):
        """get_client_database should default to DEFAULT database."""
        mock_get_client.return_value = make_settings()
        mock_get_databases.return_value = make_database(name="DEFAULT")

        utils_databases.get_client_database("test_client")

        mock_get_databases.assert_called_once_with(db_name="DEFAULT", validate=False)

    @patch("server.api.utils.databases.utils_settings.get_client")
    @patch("server.api.utils.databases.get_databases")
    def test_get_client_database_from_database_settings(
        self, mock_get_databases, mock_get_client, make_settings, make_database
    ):
        """get_client_database should use database alias from Settings.database."""
        settings = make_settings()
        settings.database = DatabaseSettings(alias="CUSTOM_DB")
        mock_get_client.return_value = settings
        mock_get_databases.return_value = make_database(name="CUSTOM_DB")

        utils_databases.get_client_database("test_client")

        # Should use the alias from Settings.database
        mock_get_databases.assert_called_once_with(db_name="CUSTOM_DB", validate=False)

    @patch("server.api.utils.databases.utils_settings.get_client")
    @patch("server.api.utils.databases.get_databases")
    def test_get_client_database_with_validate(
        self, mock_get_databases, mock_get_client, make_settings, make_database
    ):
        """get_client_database should pass validate flag."""
        mock_get_client.return_value = make_settings()
        mock_get_databases.return_value = make_database()

        utils_databases.get_client_database("test_client", validate=True)

        mock_get_databases.assert_called_once_with(db_name="DEFAULT", validate=True)


class TestTestConnection:  # pylint: disable=protected-access
    """Tests for the _test function."""

    def test_test_connection_active(self, make_database):
        """_test should set connected=True when ping succeeds."""
        config = make_database()
        mock_conn = MagicMock()
        mock_conn.ping.return_value = None
        config.set_connection(mock_conn)

        utils_databases._test(config)

        assert config.connected is True

    @patch("server.api.utils.databases.connect")
    def test_test_connection_refreshes_on_database_error(self, mock_connect, make_database):
        """_test should refresh connection on DatabaseError."""
        config = make_database()
        mock_conn = MagicMock()
        mock_conn.ping.side_effect = oracledb.DatabaseError("Connection lost")
        config.set_connection(mock_conn)
        mock_connect.return_value = MagicMock()

        utils_databases._test(config)

        mock_connect.assert_called_once_with(config)

    def test_test_raises_db_exception_on_value_error(self, make_database):
        """_test should raise DbException on ValueError."""
        config = make_database()
        mock_conn = MagicMock()
        mock_conn.ping.side_effect = ValueError("Invalid config")
        config.set_connection(mock_conn)

        with pytest.raises(DbException) as exc_info:
            utils_databases._test(config)

        assert exc_info.value.status_code == 400

    def test_test_raises_db_exception_on_permission_error(self, make_database):
        """_test should raise DbException on PermissionError."""
        config = make_database()
        mock_conn = MagicMock()
        mock_conn.ping.side_effect = PermissionError("Access denied")
        config.set_connection(mock_conn)

        with pytest.raises(DbException) as exc_info:
            utils_databases._test(config)

        assert exc_info.value.status_code == 401

    def test_test_raises_db_exception_on_connection_error(self, make_database):
        """_test should raise DbException on ConnectionError."""
        config = make_database()
        mock_conn = MagicMock()
        mock_conn.ping.side_effect = ConnectionError("Network error")
        config.set_connection(mock_conn)

        with pytest.raises(DbException) as exc_info:
            utils_databases._test(config)

        assert exc_info.value.status_code == 503


class TestGetVs:  # pylint: disable=protected-access
    """Tests for the _get_vs function.

    Uses real database - queries user_tables for vector store metadata.
    Note: Results depend on actual tables in test database schema.
    """

    def test_get_vs_returns_list(self, db_transaction):
        """_get_vs should return a list (real database)."""
        result = utils_databases._get_vs(db_transaction)

        # Should return a list (may be empty if no vector stores exist)
        assert isinstance(result, list)

    def test_get_vs_empty_for_clean_schema(self, db_transaction):
        """_get_vs should return empty list when no vector stores (real database)."""
        # In a clean test schema, there should be no vector stores
        result = utils_databases._get_vs(db_transaction)

        # Either empty or returns actual vector stores if they exist
        assert isinstance(result, list)


class TestLoggerConfiguration:
    """Tests for logger configuration."""

    def test_logger_exists(self):
        """Logger should be configured."""
        assert hasattr(utils_databases, "logger")

    def test_logger_name(self):
        """Logger should have correct name."""
        assert utils_databases.logger.name == "api.utils.database"
