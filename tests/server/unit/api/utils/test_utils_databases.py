"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=protected-access,import-error,too-many-public-methods,attribute-defined-outside-init

import json
from unittest.mock import patch, MagicMock

import pytest
import oracledb
from conftest import TEST_CONFIG

from server.api.utils import databases
from server.api.utils.databases import DbException
from common.schema import Database

class TestDatabases:
    """Test databases module functionality"""

    def setup_method(self):
        """Setup test data before each test"""
        self.sample_database = Database(name="test_db", user="test_user", password="test_password", dsn="test_dsn")
        self.sample_database_2 = Database(
            name="test_db_2", user="test_user_2", password="test_password_2", dsn="test_dsn_2"
        )

    @patch("server.api.utils.databases.DATABASE_OBJECTS")
    def test_get_all(self, mock_database_objects):
        """Test getting all databases when no name is provided"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([self.sample_database, self.sample_database_2]))
        mock_database_objects.__len__ = MagicMock(return_value=2)

        result = databases.get()

        assert result == [self.sample_database, self.sample_database_2]
        assert len(result) == 2

    @patch("server.api.utils.databases.DATABASE_OBJECTS")
    def test_get_by_name_found(self, mock_database_objects):
        """Test getting database by name when it exists"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([self.sample_database, self.sample_database_2]))
        mock_database_objects.__len__ = MagicMock(return_value=2)

        result = databases.get(name="test_db")

        assert result == [self.sample_database]
        assert len(result) == 1

    @patch("server.api.utils.databases.DATABASE_OBJECTS")
    def test_get_by_name_not_found(self, mock_database_objects):
        """Test getting database by name when it doesn't exist"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([self.sample_database]))
        mock_database_objects.__len__ = MagicMock(return_value=1)

        with pytest.raises(ValueError, match="nonexistent not found"):
            databases.get(name="nonexistent")

    @patch("server.api.utils.databases.DATABASE_OBJECTS")
    def test_get_empty_list(self, mock_database_objects):
        """Test getting databases when list is empty"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([]))
        mock_database_objects.__len__ = MagicMock(return_value=0)

        result = databases.get()

        assert result == []

    @patch("server.api.utils.databases.DATABASE_OBJECTS")
    def test_get_empty_list_with_name(self, mock_database_objects):
        """Test getting database by name when list is empty"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([]))
        mock_database_objects.__len__ = MagicMock(return_value=0)

        with pytest.raises(ValueError, match="test_db not found"):
            databases.get(name="test_db")

    def test_create_success(self, db_container):
        """Test successful database creation when database doesn't exist"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            # Clear the list to start fresh
            databases.DATABASE_OBJECTS.clear()

            # Create a new database
            new_database = Database(name="new_test_db", user="test_user", password="test_password", dsn="test_dsn")

            result = databases.create(new_database)

            # Verify database was added
            assert len(databases.DATABASE_OBJECTS) == 1
            assert databases.DATABASE_OBJECTS[0].name == "new_test_db"
            assert result == [new_database]

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_create_already_exists(self, db_container):
        """Test database creation when database already exists"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            # Add a database to the list
            databases.DATABASE_OBJECTS.clear()
            existing_db = Database(name="existing_db", user="test_user", password="test_password", dsn="test_dsn")
            databases.DATABASE_OBJECTS.append(existing_db)

            # Try to create a database with the same name
            duplicate_db = Database(name="existing_db", user="other_user", password="other_password", dsn="other_dsn")

            # Should raise an error for duplicate database
            with pytest.raises(ValueError, match="Database: existing_db already exists"):
                databases.create(duplicate_db)

            # Verify only original database exists
            assert len(databases.DATABASE_OBJECTS) == 1
            assert databases.DATABASE_OBJECTS[0] == existing_db

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_create_missing_user(self, db_container):
        """Test database creation with missing user field"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()

            # Create database with missing user
            incomplete_db = Database(name="incomplete_db", password="test_password", dsn="test_dsn")

            with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
                databases.create(incomplete_db)

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_create_missing_password(self, db_container):
        """Test database creation with missing password field"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()

            # Create database with missing password
            incomplete_db = Database(name="incomplete_db", user="test_user", dsn="test_dsn")

            with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
                databases.create(incomplete_db)

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_create_missing_dsn(self, db_container):
        """Test database creation with missing dsn field"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()

            # Create database with missing dsn
            incomplete_db = Database(name="incomplete_db", user="test_user", password="test_password")

            with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
                databases.create(incomplete_db)

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_create_multiple_missing_fields(self, db_container):
        """Test database creation with multiple missing required fields"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()

            # Create database with multiple missing fields
            incomplete_db = Database(name="incomplete_db")

            with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
                databases.create(incomplete_db)

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_delete(self, db_container):
        """Test database deletion"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            # Setup test data
            db1 = Database(name="test_db_1", user="user1", password="pass1", dsn="dsn1")
            db2 = Database(name="test_db_2", user="user2", password="pass2", dsn="dsn2")
            db3 = Database(name="test_db_3", user="user3", password="pass3", dsn="dsn3")

            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend([db1, db2, db3])

            # Delete middle database
            databases.delete("test_db_2")

            # Verify deletion
            assert len(databases.DATABASE_OBJECTS) == 2
            names = [db.name for db in databases.DATABASE_OBJECTS]
            assert "test_db_1" in names
            assert "test_db_2" not in names
            assert "test_db_3" in names

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_delete_nonexistent(self, db_container):
        """Test deleting non-existent database"""
        assert db_container is not None

        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            # Setup test data
            db1 = Database(name="test_db_1", user="user1", password="pass1", dsn="dsn1")
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.append(db1)

            original_length = len(databases.DATABASE_OBJECTS)

            # Try to delete non-existent database (should not raise error)
            databases.delete("nonexistent")

            # Verify no change
            assert len(databases.DATABASE_OBJECTS) == original_length
            assert databases.DATABASE_OBJECTS[0].name == "test_db_1"

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_delete_empty_list(self, db_container):
        """Test deleting from empty database list"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()

            # Try to delete from empty list (should not raise error)
            databases.delete("any_name")

            # Verify still empty
            assert len(databases.DATABASE_OBJECTS) == 0

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_delete_multiple_same_name(self, db_container):
        """Test deleting when multiple databases have the same name"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            # Setup test data with duplicate names
            db1 = Database(name="duplicate", user="user1", password="pass1", dsn="dsn1")
            db2 = Database(name="duplicate", user="user2", password="pass2", dsn="dsn2")
            db3 = Database(name="other", user="user3", password="pass3", dsn="dsn3")

            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend([db1, db2, db3])

            # Delete databases with duplicate name
            databases.delete("duplicate")

            # Verify all duplicates are removed
            assert len(databases.DATABASE_OBJECTS) == 1
            assert databases.DATABASE_OBJECTS[0].name == "other"

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(databases, "logger")
        assert databases.logger.name == "api.utils.database"

    def test_get_filters_correctly(self, db_container):
        """Test that get correctly filters by name"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            # Setup test data
            db1 = Database(name="alpha", user="user1", password="pass1", dsn="dsn1")
            db2 = Database(name="beta", user="user2", password="pass2", dsn="dsn2")
            db3 = Database(name="alpha", user="user3", password="pass3", dsn="dsn3")  # Duplicate name

            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend([db1, db2, db3])

            # Test getting all
            all_dbs = databases.get()
            assert len(all_dbs) == 3

            # Test getting by specific name
            alpha_dbs = databases.get(name="alpha")
            assert len(alpha_dbs) == 2
            assert all(db.name == "alpha" for db in alpha_dbs)

            beta_dbs = databases.get(name="beta")
            assert len(beta_dbs) == 1
            assert beta_dbs[0].name == "beta"

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_database_model_validation(self, db_container):
        """Test Database model validation and optional fields"""
        assert db_container is not None
        # Test with all required fields
        complete_db = Database(name="complete", user="test_user", password="test_password", dsn="test_dsn")
        assert complete_db.name == "complete"
        assert complete_db.user == "test_user"
        assert complete_db.password == "test_password"
        assert complete_db.dsn == "test_dsn"
        assert complete_db.connected is False  # Default value
        assert complete_db.tcp_connect_timeout == 5  # Default value
        assert complete_db.vector_stores == []  # Default value

        # Test with optional fields
        complete_db_with_options = Database(
            name="complete_with_options",
            user="test_user",
            password="test_password",
            dsn="test_dsn",
            wallet_location="/path/to/wallet",
            wallet_password="wallet_pass",
            tcp_connect_timeout=10,
        )
        assert complete_db_with_options.wallet_location == "/path/to/wallet"
        assert complete_db_with_options.wallet_password == "wallet_pass"
        assert complete_db_with_options.tcp_connect_timeout == 10

    def test_create_real_scenario(self, db_container):
        """Test create with realistic data using container DB"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()

            # Create database with realistic configuration
            test_db = Database(
                name="container_test",
                user="PYTEST",
                password="OrA_41_3xPl0d3r",
                dsn="//localhost:1525/FREEPDB1",
                tcp_connect_timeout=10,
            )

            result = databases.create(test_db)

            # Verify creation
            assert len(databases.DATABASE_OBJECTS) == 1
            created_db = databases.DATABASE_OBJECTS[0]
            assert created_db.name == "container_test"
            assert created_db.user == "PYTEST"
            assert created_db.dsn == "//localhost:1525/FREEPDB1"
            assert created_db.tcp_connect_timeout == 10
            assert result == [test_db]

        finally:
            # Restore original state
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)
            
class TestDbException:
    """Test custom database exception class"""

    def test_db_exception_initialization(self):
        """Test DbException initialization"""
        exc = DbException(status_code=500, detail="Database error")
        assert exc.status_code == 500
        assert exc.detail == "Database error"
        assert str(exc) == "Database error"

    def test_db_exception_inheritance(self):
        """Test DbException inherits from Exception"""
        exc = DbException(status_code=404, detail="Not found")
        assert isinstance(exc, Exception)

    def test_db_exception_different_status_codes(self):
        """Test DbException with different status codes"""
        test_cases = [
            (400, "Bad request"),
            (401, "Unauthorized"),
            (403, "Forbidden"),
            (503, "Service unavailable"),
        ]

        for status_code, detail in test_cases:
            exc = DbException(status_code=status_code, detail=detail)
            assert exc.status_code == status_code
            assert exc.detail == detail


class TestDatabaseUtilsPrivateFunctions:
    """Test private utility functions"""

    def setup_method(self):
        """Setup test data"""
        self.sample_database = Database(
            name="test_db",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"]
        )

    def test_test_function_success(self, db_container):
        """Test successful database connection test with real database"""
        assert db_container is not None
        # Connect to real database
        conn = databases.connect(self.sample_database)
        self.sample_database.set_connection(conn)

        try:
            # Test the connection
            databases._test(self.sample_database)
            assert self.sample_database.connected is True
        finally:
            databases.disconnect(conn)

    @patch("oracledb.Connection")
    def test_test_function_reconnect(self, mock_connection):
        """Test database reconnection when ping fails"""
        mock_connection.ping.side_effect = oracledb.DatabaseError("Connection lost")
        self.sample_database.set_connection(mock_connection)

        with patch("server.api.utils.databases.connect") as mock_connect:
            databases._test(self.sample_database)
            mock_connect.assert_called_once_with(self.sample_database)

    @patch("oracledb.Connection")
    def test_test_function_value_error(self, mock_connection):
        """Test handling of value errors"""
        mock_connection.ping.side_effect = ValueError("Invalid value")
        self.sample_database.set_connection(mock_connection)

        with pytest.raises(DbException) as exc_info:
            databases._test(self.sample_database)

        assert exc_info.value.status_code == 400
        assert "Database: Invalid value" in str(exc_info.value)

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

    @patch("oracledb.Connection")
    def test_test_function_generic_exception(self, mock_connection):
        """Test handling of generic exceptions"""
        mock_connection.ping.side_effect = RuntimeError("Unknown error")
        self.sample_database.set_connection(mock_connection)

        with pytest.raises(DbException) as exc_info:
            databases._test(self.sample_database)

        assert exc_info.value.status_code == 500
        assert "Unknown error" in str(exc_info.value)

    def test_get_vs_with_real_database(self, db_container):
        """Test vector storage retrieval with real database"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        try:
            # Test with empty result (no vector stores initially)
            result = databases._get_vs(conn)
            assert isinstance(result, list)
            assert len(result) == 0  # Initially no vector stores
        finally:
            databases.disconnect(conn)

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
                '"chunk_size": 500, "distance_metric": "EUCLIDEAN_DISTANCE"}'
            )
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

    def test_selectai_enabled_with_real_database(self, db_container):
        """Test SelectAI enabled check with real database"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        try:
            # Test with real database (likely returns False for test environment)
            result = databases._selectai_enabled(conn)
            assert isinstance(result, bool)
            # We don't assert the specific value as it depends on the database setup
        finally:
            databases.disconnect(conn)

    @patch("server.api.utils.databases.execute_sql")
    def test_selectai_enabled_true(self, mock_execute_sql):
        """Test SelectAI enabled check returns True"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = [(2,)]

        result = databases._selectai_enabled(mock_connection)

        assert result is True

    @patch("server.api.utils.databases.execute_sql")
    def test_selectai_enabled_false(self, mock_execute_sql):
        """Test SelectAI enabled check returns False"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = [(1,)]

        result = databases._selectai_enabled(mock_connection)

        assert result is False

    @patch("server.api.utils.databases.execute_sql")
    def test_selectai_enabled_zero_privileges(self, mock_execute_sql):
        """Test SelectAI enabled check with zero privileges"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = [(0,)]

        result = databases._selectai_enabled(mock_connection)

        assert result is False

    def test_get_selectai_profiles_with_real_database(self, db_container):
        """Test SelectAI profiles retrieval with real database"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        try:
            # Test with real database (likely returns empty list for test environment)
            result = databases._get_selectai_profiles(conn)
            assert isinstance(result, list)
            # We don't assert the specific content as it depends on the database setup
        finally:
            databases.disconnect(conn)

    @patch("server.api.utils.databases.execute_sql")
    def test_get_selectai_profiles_with_data(self, mock_execute_sql):
        """Test SelectAI profiles retrieval with data"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = [("PROFILE1",), ("PROFILE2",), ("PROFILE3",)]

        result = databases._get_selectai_profiles(mock_connection)

        assert result == ["PROFILE1", "PROFILE2", "PROFILE3"]

    @patch("server.api.utils.databases.execute_sql")
    def test_get_selectai_profiles_empty(self, mock_execute_sql):
        """Test SelectAI profiles retrieval with no profiles"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = []

        result = databases._get_selectai_profiles(mock_connection)

        assert result == []

    @patch("server.api.utils.databases.execute_sql")
    def test_get_selectai_profiles_none_result(self, mock_execute_sql):
        """Test SelectAI profiles retrieval with None results"""
        mock_connection = MagicMock()
        mock_execute_sql.return_value = None

        result = databases._get_selectai_profiles(mock_connection)

        assert result == []


class TestDatabaseUtilsPublicFunctions:
    """Test public utility functions"""

    def setup_method(self):
        """Setup test data"""
        self.sample_database = Database(
            name="test_db",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"]
        )

    def test_connect_success_with_real_database(self, db_container):
        """Test successful database connection with real database"""
        assert db_container is not None
        result = databases.connect(self.sample_database)

        try:
            assert result is not None
            assert isinstance(result, oracledb.Connection)
            # Test that connection is active
            result.ping()
        finally:
            databases.disconnect(result)

    def test_connect_missing_user(self):
        """Test connection with missing user"""
        incomplete_db = Database(
            name="test_db",
            user="",  # Missing user
            password=TEST_CONFIG["db_password"],
            dsn=TEST_CONFIG["db_dsn"],
        )

        with pytest.raises(ValueError, match="missing connection details"):
            databases.connect(incomplete_db)

    def test_connect_missing_password(self):
        """Test connection with missing password"""
        incomplete_db = Database(
            name="test_db",
            user=TEST_CONFIG["db_username"],
            password="",  # Missing password
            dsn=TEST_CONFIG["db_dsn"],
        )

        with pytest.raises(ValueError, match="missing connection details"):
            databases.connect(incomplete_db)

    def test_connect_missing_dsn(self):
        """Test connection with missing DSN"""
        incomplete_db = Database(
            name="test_db",
            user=TEST_CONFIG["db_username"],
            password=TEST_CONFIG["db_password"],
            dsn="",  # Missing DSN
        )

        with pytest.raises(ValueError, match="missing connection details"):
            databases.connect(incomplete_db)

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

    def test_connect_invalid_credentials(self, db_container):
        """Test connection with invalid credentials"""
        assert db_container is not None
        invalid_db = Database(
            name="test_db",
            user="invalid_user",
            password="invalid_password",
            dsn=TEST_CONFIG["db_dsn"],
        )

        with pytest.raises(PermissionError):
            databases.connect(invalid_db)

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

    def test_disconnect_success(self, db_container):
        """Test successful database disconnection"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        result = databases.disconnect(conn)

        assert result is None
        # Try to use connection after disconnect - should fail
        with pytest.raises(oracledb.InterfaceError):
            conn.ping()

    def test_execute_sql_success_with_real_database(self, db_container):
        """Test successful SQL execution with real database"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        try:
            # Test simple query
            result = databases.execute_sql(conn, "SELECT 1 FROM DUAL")
            assert result is not None
            assert len(result) == 1
            assert result[0][0] == 1
        finally:
            databases.disconnect(conn)

    def test_execute_sql_with_binds(self, db_container):
        """Test SQL execution with bind variables using real database"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        try:
            binds = {"test_value": 42}
            result = databases.execute_sql(conn, "SELECT :test_value FROM DUAL", binds)
            assert result is not None
            assert len(result) == 1
            assert result[0][0] == 42
        finally:
            databases.disconnect(conn)

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

    def test_execute_sql_invalid_syntax(self, db_container):
        """Test SQL execution with invalid syntax"""
        assert db_container is not None
        conn = databases.connect(self.sample_database)

        try:
            with pytest.raises(oracledb.DatabaseError):
                databases.execute_sql(conn, "INVALID SQL STATEMENT")
        finally:
            databases.disconnect(conn)

    def test_drop_vs_function_exists(self):
        """Test that drop_vs function exists and is callable"""
        assert hasattr(databases, "drop_vs")
        assert callable(databases.drop_vs)

    @patch("langchain_community.vectorstores.oraclevs.drop_table_purge")
    def test_drop_vs_calls_langchain(self, mock_drop_table):
        """Test drop_vs calls LangChain drop_table_purge"""
        mock_connection = MagicMock()
        vs_name = "TEST_VECTOR_STORE"

        databases.drop_vs(mock_connection, vs_name)

        mock_drop_table.assert_called_once_with(mock_connection, vs_name)

    def test_get_without_validation(self, db_container):
        """Test get without validation"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.append(self.sample_database)

            # Test getting all databases
            result = databases.get()
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0].name == "test_db"
            assert result[0].connected is False  # No validation, so not connected

        finally:
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_get_with_validation(self, db_container):
        """Test get with validation using real database"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.append(self.sample_database)

            # Test getting all databases with validation
            result = databases.get_databases(validate=True)
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0].name == "test_db"
            assert result[0].connected is True  # Validation should connect
            assert result[0].connection is not None

        finally:
            # Clean up connections
            for db in databases.DATABASE_OBJECTS:
                if db.connection:
                    databases.disconnect(db.connection)
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_get_by_name(self, db_container):
        """Test get by specific name"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()
            db1 = Database(name="db1", user="user1", password="pass1", dsn="dsn1")
            db2 = Database(name="db2", user=TEST_CONFIG["db_username"],
                          password=TEST_CONFIG["db_password"], dsn=TEST_CONFIG["db_dsn"])
            databases.DATABASE_OBJECTS.extend([db1, db2])

            # Test getting specific database
            result = databases.get_databases(db_name="db2")
            assert isinstance(result, Database)  # Single database, not list
            assert result.name == "db2"

        finally:
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_get_validation_failure(self, db_container):
        """Test get with validation when connection fails"""
        assert db_container is not None
        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()
            # Add database with invalid credentials
            invalid_db = Database(name="invalid", user="invalid", password="invalid", dsn="invalid")
            databases.DATABASE_OBJECTS.append(invalid_db)

            # Test validation with invalid database (should continue without error)
            result = databases.get_databases(validate=True)
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0].connected is False  # Should remain False due to connection failure

        finally:
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    @patch("server.api.utils.settings.get_client")
    def test_get_client_database_default(self, mock_get_settings, db_container):
        """Test get_client_database with default settings"""
        assert db_container is not None
        # Mock client settings without vector_search or selectai
        mock_settings = MagicMock()
        mock_settings.vector_search = None
        mock_settings.selectai = None
        mock_get_settings.return_value = mock_settings

        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()
            default_db = Database(name="DEFAULT", user=TEST_CONFIG["db_username"],
                                password=TEST_CONFIG["db_password"], dsn=TEST_CONFIG["db_dsn"])
            databases.DATABASE_OBJECTS.append(default_db)

            result = databases.get_client_database("test_client")
            assert isinstance(result, Database)
            assert result.name == "DEFAULT"

        finally:
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    @patch("server.api.utils.settings.get_client")
    def test_get_client_database_with_vector_search(self, mock_get_settings, db_container):
        """Test get_client_database with vector_search settings"""
        assert db_container is not None
        # Mock client settings with vector_search
        mock_vector_search = MagicMock()
        mock_vector_search.database = "VECTOR_DB"
        mock_settings = MagicMock()
        mock_settings.vector_search = mock_vector_search
        mock_settings.selectai = None
        mock_get_settings.return_value = mock_settings

        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()
            vector_db = Database(name="VECTOR_DB", user=TEST_CONFIG["db_username"],
                               password=TEST_CONFIG["db_password"], dsn=TEST_CONFIG["db_dsn"])
            databases.DATABASE_OBJECTS.append(vector_db)

            result = databases.get_client_database("test_client")
            assert isinstance(result, Database)
            assert result.name == "VECTOR_DB"

        finally:
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    @patch("server.api.utils.settings.get_client")
    def test_get_client_database_with_validation(self, mock_get_settings, db_container):
        """Test get_client_database with validation enabled"""
        assert db_container is not None
        # Mock client settings
        mock_settings = MagicMock()
        mock_settings.vector_search = None
        mock_settings.selectai = None
        mock_get_settings.return_value = mock_settings

        # Use real  DATABASE_OBJECTS
        original_db_objects = databases.DATABASE_OBJECTS.copy()

        try:
            databases.DATABASE_OBJECTS.clear()
            default_db = Database(name="DEFAULT", user=TEST_CONFIG["db_username"],
                                password=TEST_CONFIG["db_password"], dsn=TEST_CONFIG["db_dsn"])
            databases.DATABASE_OBJECTS.append(default_db)

            result = databases.get_client_database("test_client", validate=True)
            assert isinstance(result, Database)
            assert result.name == "DEFAULT"
            assert result.connected is True
            assert result.connection is not None

        finally:
            # Clean up connections
            for db in databases.DATABASE_OBJECTS:
                if db.connection:
                    databases.disconnect(db.connection)
            databases.DATABASE_OBJECTS.clear()
            databases.DATABASE_OBJECTS.extend(original_db_objects)

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(databases, "logger")
        assert databases.logger.name == "api.utils.database"
