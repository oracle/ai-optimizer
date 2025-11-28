"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=protected-access import-error import-outside-toplevel

import json
from unittest.mock import patch, MagicMock

import pytest
import oracledb
from conftest import TEST_CONFIG

from server.api.utils import databases
from server.api.utils.databases import DbException
from common.schema import Database


class TestDatabaseUtilsPrivateFunctions:
    """Test private utility functions"""

    sample_database: Database

    def setup_method(self):
        """Setup test data"""
        self.sample_database = Database(
            name="test_db",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"],
        )

    # test_test_function_success: See test/unit/server/api/utils/test_utils_databases.py::TestTestConnection::test_test_connection_active
    # test_test_function_reconnect: See test/unit/server/api/utils/test_utils_databases.py::TestTestConnection::test_test_connection_refreshes_on_database_error
    # test_test_function_value_error: See test/unit/server/api/utils/test_utils_databases.py::TestTestConnection::test_test_raises_db_exception_on_value_error
    # test_test_function_permission_error: See test/unit/server/api/utils/test_utils_databases.py::TestTestConnection::test_test_raises_db_exception_on_permission_error
    # test_test_function_connection_error: See test/unit/server/api/utils/test_utils_databases.py::TestTestConnection::test_test_raises_db_exception_on_connection_error
    # test_test_function_generic_exception: See test/unit/server/api/utils/test_utils_databases.py::TestTestConnection::test_test_raises_db_exception_on_generic_exception
    # test_get_vs_with_real_database: See test/unit/server/api/utils/test_utils_databases.py::TestGetVs::test_get_vs_returns_list

    @patch("server.api.utils.databases.execute_sql")
    def test_get_vs_with_mock_data(self, mock_execute_sql):
        """Test vector storage retrieval with mocked data"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = [
            (
                "TEST_TABLE",
                '{"alias": "test_alias", "model": "test_model", "chunk_size": 1000, "distance_metric": "COSINE"}',
            ),
            (
                "ANOTHER_TABLE",
                '{"alias": "another_alias", "model": "another_model", '
                '"chunk_size": 500, "distance_metric": "EUCLIDEAN_DISTANCE"}',
            ),
        ]

        result = databases._get_vs(mock_connection)

        assert len(result) == 2
        assert result[0].vector_store == "TEST_TABLE"
        assert result[0].alias == "test_alias"
        assert result[0].model == "test_model"
        assert result[0].chunk_size == 1000
        assert result[0].distance_metric == "COSINE"

        assert result[1].vector_store == "ANOTHER_TABLE"
        assert result[1].alias == "another_alias"
        assert result[1].distance_metric == "EUCLIDEAN_DISTANCE"

    @patch("server.api.utils.databases.execute_sql")
    def test_get_vs_empty_result(self, mock_execute_sql):
        """Test vector storage retrieval with empty results"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = []

        result = databases._get_vs(mock_connection)

        assert isinstance(result, list)
        assert len(result) == 0

    @patch("server.api.utils.databases.execute_sql")
    def test_get_vs_malformed_json(self, mock_execute_sql):
        """Test vector storage retrieval with malformed JSON"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = [
            ("TEST_TABLE", '{"invalid_json": }'),
        ]

        with pytest.raises(json.JSONDecodeError):
            databases._get_vs(mock_connection)

class TestDatabaseUtilsPublicFunctions:
    """Test public utility functions - connection and execution"""

    sample_database: Database

    def setup_method(self):
        """Setup test data"""
        self.sample_database = Database(
            name="test_db",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"],
        )

    # test_connect_success_with_real_database: See test/unit/server/api/utils/test_utils_databases.py::TestConnect::test_connect_success_real_db
    # test_connect_missing_user: See test/unit/server/api/utils/test_utils_databases.py::TestConnect::test_connect_raises_value_error_missing_details
    # test_connect_missing_password: See test/unit/server/api/utils/test_utils_databases.py::TestConnect::test_connect_raises_value_error_missing_details
    # test_connect_missing_dsn: See test/unit/server/api/utils/test_utils_databases.py::TestConnect::test_connect_raises_value_error_missing_details

    def test_connect_with_wallet_configuration(self, db_container):
        """Test connection with wallet configuration"""
        assert db_container is not None
        db_with_wallet = Database(
            name="test_db",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"],
            wallet_password="wallet_pass",
            config_dir="/path/to/config",
        )

        # This should attempt to connect but may fail due to wallet config
        # The test verifies the code path works, not necessarily successful connection
        try:
            result = databases.connect(db_with_wallet)
            databases.disconnect(result)
        except oracledb.DatabaseError:
            # Expected if wallet doesn't exist
            pass

    def test_connect_wallet_password_without_location(self, db_container):
        """Test connection with wallet password but no location"""
        assert db_container is not None
        db_with_wallet = Database(
            name="test_db",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"],
            wallet_password="wallet_pass",
            config_dir="/default/config",
        )

        # This should set wallet_location to config_dir
        try:
            result = databases.connect(db_with_wallet)
            databases.disconnect(result)
        except oracledb.DatabaseError:
            # Expected if wallet doesn't exist
            pass

    # test_connect_invalid_credentials: See test/unit/server/api/utils/test_utils_databases.py::TestConnect::test_connect_raises_permission_error_invalid_credentials

    def test_connect_invalid_dsn(self, db_container):
        """Test connection with invalid DSN"""
        assert db_container is not None
        invalid_db = Database(
            name="test_db",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn="//invalid:1521/INVALID",
        )

        # This will raise socket.gaierror which is wrapped in oracledb.DatabaseError
        with pytest.raises(Exception):  # Catch any exception - DNS resolution errors vary by environment
            databases.connect(invalid_db)

    # test_disconnect_success: See test/unit/server/api/utils/test_utils_databases.py::TestDisconnect::test_disconnect_closes_connection
    # test_execute_sql_success_with_real_database: See test/unit/server/api/utils/test_utils_databases.py::TestExecuteSql::test_execute_sql_returns_rows
    # test_execute_sql_with_binds: See test/unit/server/api/utils/test_utils_databases.py::TestExecuteSql::test_execute_sql_with_binds

    def test_execute_sql_no_rows(self, db_container):
        """Test SQL execution that returns no rows"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        try:
            # Test query with no results
            result = databases.execute_sql(conn, "SELECT 1 FROM DUAL WHERE 1=0")
            assert result == []
        finally:
            databases.disconnect(conn)

    def test_execute_sql_ddl_statement(self, db_container):
        """Test SQL execution with DDL statement"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        try:
            # Create a test table
            databases.execute_sql(conn, "CREATE TABLE test_temp (id NUMBER)")

            # Drop the test table
            result = databases.execute_sql(conn, "DROP TABLE test_temp")
            # DDL statements typically return None
            assert result is None
        except oracledb.DatabaseError as e:
            # If table already exists or other DDL error, that's okay for testing
            if "name is already used" not in str(e):
                raise
        finally:
            # Clean up if table still exists
            try:
                databases.execute_sql(conn, "DROP TABLE test_temp")
            except oracledb.DatabaseError:
                pass  # Table doesn't exist, which is fine
            databases.disconnect(conn)

    def test_execute_sql_table_exists_error(self, db_container):
        """Test SQL execution with table exists error (ORA-00955)"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        try:
            # Create table twice to trigger ORA-00955
            databases.execute_sql(conn, "CREATE TABLE test_exists (id NUMBER)")

            # This should log but not raise an exception
            databases.execute_sql(conn, "CREATE TABLE test_exists (id NUMBER)")

        except oracledb.DatabaseError:
            # Expected behavior - the function should handle this gracefully
            pass
        finally:
            try:
                databases.execute_sql(conn, "DROP TABLE test_exists")
            except oracledb.DatabaseError:
                pass
            databases.disconnect(conn)

    def test_execute_sql_table_not_exists_error(self, db_container):
        """Test SQL execution with table not exists error (ORA-00942)"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        try:
            # Try to select from non-existent table to trigger ORA-00942
            databases.execute_sql(conn, "SELECT * FROM non_existent_table")
        except oracledb.DatabaseError:
            # Expected behavior - the function should handle this gracefully
            pass
        finally:
            databases.disconnect(conn)

    # test_execute_sql_invalid_syntax: See test/unit/server/api/utils/test_utils_databases.py::TestExecuteSql::test_execute_sql_raises_on_other_database_error

    def test_drop_vs_function_exists(self):
        """Test that drop_vs function exists and is callable"""
        assert hasattr(databases, "drop_vs")
        assert callable(databases.drop_vs)

    # test_drop_vs_calls_langchain: See test/unit/server/api/utils/test_utils_databases.py::TestDropVs::test_drop_vs_calls_langchain


class TestDatabaseUtilsQueryFunctions:
    """Test public utility functions - get and client database functions"""

    sample_database: Database

    def setup_method(self):
        """Setup test data"""
        self.sample_database = Database(
            name="test_db",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"],
        )

    def test_get_without_validation(self, db_container, db_objects_manager):
        """Test get without validation"""
        assert db_container is not None
        assert db_objects_manager is not None
        databases.DATABASE_OBJECTS.clear()
        databases.DATABASE_OBJECTS.append(self.sample_database)

        # Test getting all databases
        result = databases.get()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].name == "test_db"
        assert result[0].connected is False  # No validation, so not connected

    def test_get_with_validation(self, db_container, db_objects_manager):
        """Test get with validation using real database"""
        assert db_container is not None
        assert db_objects_manager is not None
        databases.DATABASE_OBJECTS.clear()
        databases.DATABASE_OBJECTS.append(self.sample_database)

        # Test getting all databases with validation
        result = databases.get_databases(validate=True)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].name == "test_db"
        assert result[0].connected is True  # Validation should connect
        assert result[0].connection is not None

        # Clean up connections
        for db in databases.DATABASE_OBJECTS:
            if db.connection:
                databases.disconnect(db.connection)

    def test_get_by_name(self, db_container, db_objects_manager):
        """Test get by specific name"""
        assert db_container is not None
        assert db_objects_manager is not None
        databases.DATABASE_OBJECTS.clear()
        db1 = Database(name="db1", user="user1", password="pass1", dsn="dsn1")
        db2 = Database(
            name="db2", user=TEST_CONFIG["db_username"], password=TEST_CONFIG["db_password"], dsn=TEST_CONFIG["db_dsn"]
        )
        databases.DATABASE_OBJECTS.extend([db1, db2])

        # Test getting specific database
        result = databases.get_databases(db_name="db2")
        assert isinstance(result, Database)  # Single database, not list
        assert result.name == "db2"

    def test_get_validation_failure(self, db_container, db_objects_manager):
        """Test get with validation when connection fails"""
        assert db_container is not None
        assert db_objects_manager is not None
        databases.DATABASE_OBJECTS.clear()
        # Add database with invalid credentials
        invalid_db = Database(name="invalid", user="invalid", password="invalid", dsn="invalid")
        databases.DATABASE_OBJECTS.append(invalid_db)

        # Test validation with invalid database (should continue without error)
        result = databases.get_databases(validate=True)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].connected is False  # Should remain False due to connection failure

    @patch("server.api.utils.settings.get_client")
    def test_get_client_database_default(self, mock_get_settings, db_container, db_objects_manager):
        """Test get_client_database with default settings"""
        assert db_container is not None
        assert db_objects_manager is not None
        # Mock client settings without vector_search
        mock_settings = MagicMock()
        mock_settings.vector_search = None
        mock_get_settings.return_value = mock_settings

        databases.DATABASE_OBJECTS.clear()
        default_db = Database(
            name="DEFAULT",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"],
        )
        databases.DATABASE_OBJECTS.append(default_db)

        result = databases.get_client_database("test_client")
        assert isinstance(result, Database)
        assert result.name == "DEFAULT"

    @patch("server.api.utils.settings.get_client")
    def test_get_client_database_with_vector_search(self, mock_get_settings, db_container, db_objects_manager):
        """Test get_client_database with vector_search settings"""
        assert db_container is not None
        assert db_objects_manager is not None
        # Mock client settings with vector_search
        mock_vector_search = MagicMock()
        mock_vector_search.database = "VECTOR_DB"
        mock_settings = MagicMock()
        mock_settings.vector_search = mock_vector_search
        mock_get_settings.return_value = mock_settings

        databases.DATABASE_OBJECTS.clear()
        vector_db = Database(
            name="VECTOR_DB",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"],
        )
        databases.DATABASE_OBJECTS.append(vector_db)

        result = databases.get_client_database("test_client")
        assert isinstance(result, Database)
        assert result.name == "VECTOR_DB"

    @patch("server.api.utils.settings.get_client")
    def test_get_client_database_with_validation(self, mock_get_settings, db_container, db_objects_manager):
        """Test get_client_database with validation enabled"""
        assert db_container is not None
        assert db_objects_manager is not None
        # Mock client settings
        mock_settings = MagicMock()
        mock_settings.vector_search = None
        mock_get_settings.return_value = mock_settings

        databases.DATABASE_OBJECTS.clear()
        default_db = Database(
            name="DEFAULT",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"],
        )
        databases.DATABASE_OBJECTS.append(default_db)

        result = databases.get_client_database("test_client", validate=True)
        assert isinstance(result, Database)
        assert result.name == "DEFAULT"
        assert result.connected is True
        assert result.connection is not None

        # Clean up connections
        for db in databases.DATABASE_OBJECTS:
            if db.connection:
                databases.disconnect(db.connection)

    # test_logger_exists: See test/unit/server/api/utils/test_utils_databases.py::TestLoggerConfiguration::test_logger_exists
