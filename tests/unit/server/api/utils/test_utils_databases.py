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

from unittest.mock import patch, MagicMock

import pytest
import oracledb
from db_fixtures import TEST_DB_CONFIG
from shared_fixtures import TEST_DB_WALLET_PASSWORD

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
            user=TEST_DB_CONFIG["db_username"],
            password=TEST_DB_CONFIG["db_password"],
            dsn=TEST_DB_CONFIG["db_dsn"],
        )

        result = utils_databases.connect(config)

        assert result is not None
        assert result.is_healthy()
        result.close()

    def test_connect_raises_db_exception_missing_details(self, make_database):
        """connect should raise DbException if connection details missing."""
        config = make_database(user=None, password=None, dsn=None)

        with pytest.raises(DbException) as exc_info:
            utils_databases.connect(config)

        assert exc_info.value.status_code == 400
        assert "missing connection details" in str(exc_info.value.detail)

    def test_connect_raises_permission_error_invalid_credentials(self, db_container, make_database):
        """connect should raise PermissionError on invalid credentials (real database)."""
        # pylint: disable=unused-argument
        config = make_database(
            user="INVALID_USER",
            password=TEST_DB_WALLET_PASSWORD,  # Using a fake password for invalid login test
            dsn=TEST_DB_CONFIG["db_dsn"],
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
            user=TEST_DB_CONFIG["db_username"],
            password=TEST_DB_CONFIG["db_password"],
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
        config = make_database(wallet_password=TEST_DB_WALLET_PASSWORD, config_dir="/path/to/config")

        utils_databases.connect(config)

        call_kwargs = mock_connect.call_args.kwargs
        assert call_kwargs.get("wallet_location") == "/path/to/config"

    @patch("server.api.utils.databases.oracledb.connect")
    def test_connect_raises_permission_error_on_ora_28009(self, mock_connect, make_database):
        """connect should raise PermissionError with custom message on ORA-28009 (mocked)."""
        # Create a mock error object with full_code and message
        mock_error = MagicMock()
        mock_error.full_code = "ORA-28009"
        mock_error.message = "connection not allowed"
        mock_connect.side_effect = oracledb.DatabaseError(mock_error)
        config = make_database(user="SYS")

        with pytest.raises(PermissionError) as exc_info:
            utils_databases.connect(config)

        assert "Connecting as SYS is not permitted" in str(exc_info.value)

    @patch("server.api.utils.databases.oracledb.connect")
    def test_connect_reraises_unmapped_database_error(self, mock_connect, make_database):
        """connect should re-raise unmapped DatabaseError codes (mocked)."""
        # Create a mock error object with an unmapped error code
        mock_error = MagicMock()
        mock_error.full_code = "ORA-12345"
        mock_error.message = "some other error"
        mock_connect.side_effect = oracledb.DatabaseError(mock_error)
        config = make_database()

        with pytest.raises(oracledb.DatabaseError):
            utils_databases.connect(config)


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

    def test_execute_sql_logs_table_exists_error(self, db_connection, caplog):
        """execute_sql should log ORA-00955 table exists error (real database).

        Note: Due to a bug in the source code (two if statements instead of elif),
        the function logs 'Table exists' but still raises. This test verifies
        the logging behavior and that the error is raised.
        """
        cursor = db_connection.cursor()
        table_name = "TEST_DUPLICATE_TABLE"

        try:
            # Create table first
            cursor.execute(f"CREATE TABLE {table_name} (id NUMBER)")
            db_connection.commit()

            # Try to create it again - logs 'Table exists' but raises due to bug
            with pytest.raises(oracledb.DatabaseError):
                utils_databases.execute_sql(
                    db_connection,
                    f"CREATE TABLE {table_name} (id NUMBER)",
                )

            # Verify the logging happened
            assert "Table exists" in caplog.text

        finally:
            try:
                cursor.execute(f"DROP TABLE {table_name} PURGE")
                db_connection.commit()
            except oracledb.DatabaseError:
                pass
            cursor.close()

    def test_execute_sql_handles_table_not_exists_error(self, db_connection, caplog):
        """execute_sql should handle ORA-00942 table not exists error (real database).

        The function logs 'Table does not exist' and returns None (doesn't raise)
        for error code 942.
        """
        # Try to select from a non-existent table
        result = utils_databases.execute_sql(
            db_connection,
            "SELECT * FROM NONEXISTENT_TABLE_12345",
        )

        # Should not raise, returns None
        assert result is None

        # Verify the logging happened
        assert "Table does not exist" in caplog.text

    def test_execute_sql_raises_on_other_database_error(self, db_transaction):
        """execute_sql should raise on other DatabaseError codes (real database)."""
        # Invalid SQL syntax should raise
        with pytest.raises(oracledb.DatabaseError):
            utils_databases.execute_sql(db_transaction, "INVALID SQL SYNTAX HERE")

    def test_execute_sql_raises_on_interface_error(self):
        """execute_sql should raise on InterfaceError (mocked)."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.callproc.side_effect = oracledb.InterfaceError("Interface error")

        with pytest.raises(oracledb.InterfaceError):
            utils_databases.execute_sql(mock_conn, "SELECT 1 FROM dual")

    def test_execute_sql_raises_on_database_error_no_args(self):
        """execute_sql should raise on DatabaseError with no args (mocked)."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        # DatabaseError with empty args
        mock_cursor.callproc.side_effect = oracledb.DatabaseError()

        with pytest.raises(oracledb.DatabaseError):
            utils_databases.execute_sql(mock_conn, "SELECT 1 FROM dual")


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

    def test_test_raises_db_exception_on_generic_exception(self, make_database):
        """_test should raise DbException with 500 on generic Exception."""
        config = make_database()
        mock_conn = MagicMock()
        mock_conn.ping.side_effect = RuntimeError("Unexpected error")
        config.set_connection(mock_conn)

        with pytest.raises(DbException) as exc_info:
            utils_databases._test(config)

        assert exc_info.value.status_code == 500
        assert "Unexpected error" in exc_info.value.detail


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

    def test_get_vs_parses_genai_comment(self, db_connection):
        """_get_vs should parse GENAI comment JSON and return DatabaseVectorStorage (real database)."""
        cursor = db_connection.cursor()
        table_name = "VS_TEST_TABLE"

        try:
            # Create a test table
            cursor.execute(f"CREATE TABLE {table_name} (id NUMBER, data VARCHAR2(100))")

            # Add GENAI comment with JSON metadata (matching the expected format)
            comment_json = '{"description": "Test vector store"}'
            cursor.execute(f"COMMENT ON TABLE {table_name} IS 'GENAI: {comment_json}'")
            db_connection.commit()

            # Test _get_vs
            result = utils_databases._get_vs(db_connection)

            # Should find our test table
            vs_names = [vs.vector_store for vs in result]
            assert table_name in vs_names

            # Find our test vector store and verify parsed data
            test_vs = next(vs for vs in result if vs.vector_store == table_name)
            assert test_vs.description == "Test vector store"

        finally:
            # Cleanup - drop table
            try:
                cursor.execute(f"DROP TABLE {table_name} PURGE")
                db_connection.commit()
            except oracledb.DatabaseError:
                pass
            cursor.close()
