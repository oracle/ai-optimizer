"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=attribute-defined-outside-init

from unittest.mock import patch, MagicMock
import pytest

from server.api.core import databases
from server.api.core import bootstrap
from common.schema import Database


class TestDatabases:
    """Test databases module functionality"""

    def setup_method(self):
        """Setup test data before each test"""
        self.sample_database = Database(name="test_db", user="test_user", password="test_password", dsn="test_dsn")
        self.sample_database_2 = Database(
            name="test_db_2", user="test_user_2", password="test_password_2", dsn="test_dsn_2"
        )

    @patch("server.api.core.databases.bootstrap.DATABASE_OBJECTS")
    def test_get_database_all(self, mock_database_objects):
        """Test getting all databases when no name is provided"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([self.sample_database, self.sample_database_2]))
        mock_database_objects.__len__ = MagicMock(return_value=2)

        result = databases.get_database()

        assert result == [self.sample_database, self.sample_database_2]
        assert len(result) == 2

    @patch("server.api.core.databases.bootstrap.DATABASE_OBJECTS")
    def test_get_database_by_name_found(self, mock_database_objects):
        """Test getting database by name when it exists"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([self.sample_database, self.sample_database_2]))
        mock_database_objects.__len__ = MagicMock(return_value=2)

        result = databases.get_database(name="test_db")

        assert result == [self.sample_database]
        assert len(result) == 1

    @patch("server.api.core.databases.bootstrap.DATABASE_OBJECTS")
    def test_get_database_by_name_not_found(self, mock_database_objects):
        """Test getting database by name when it doesn't exist"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([self.sample_database]))
        mock_database_objects.__len__ = MagicMock(return_value=1)

        with pytest.raises(ValueError, match="nonexistent not found"):
            databases.get_database(name="nonexistent")

    @patch("server.api.core.databases.bootstrap.DATABASE_OBJECTS")
    def test_get_database_empty_list(self, mock_database_objects):
        """Test getting databases when list is empty"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([]))
        mock_database_objects.__len__ = MagicMock(return_value=0)

        result = databases.get_database()

        assert result == []

    @patch("server.api.core.databases.bootstrap.DATABASE_OBJECTS")
    def test_get_database_empty_list_with_name(self, mock_database_objects):
        """Test getting database by name when list is empty"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([]))
        mock_database_objects.__len__ = MagicMock(return_value=0)

        with pytest.raises(ValueError, match="test_db not found"):
            databases.get_database(name="test_db")

    def test_create_database_success(self, db_container):
        """Test successful database creation when database doesn't exist"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            # Clear the list to start fresh
            bootstrap.DATABASE_OBJECTS.clear()

            # Create a new database
            new_database = Database(name="new_test_db", user="test_user", password="test_password", dsn="test_dsn")

            result = databases.create_database(new_database)

            # Verify database was added
            assert len(bootstrap.DATABASE_OBJECTS) == 1
            assert bootstrap.DATABASE_OBJECTS[0].name == "new_test_db"
            assert result == [new_database]

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

    def test_create_database_already_exists(self, db_container):
        """Test database creation when database already exists"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            # Add a database to the list
            bootstrap.DATABASE_OBJECTS.clear()
            existing_db = Database(name="existing_db", user="test_user", password="test_password", dsn="test_dsn")
            bootstrap.DATABASE_OBJECTS.append(existing_db)

            # Try to create a database with the same name
            duplicate_db = Database(name="existing_db", user="other_user", password="other_password", dsn="other_dsn")

            # Should raise an error for duplicate database
            with pytest.raises(ValueError, match="Database existing_db already exists"):
                databases.create_database(duplicate_db)

            # Verify only original database exists
            assert len(bootstrap.DATABASE_OBJECTS) == 1
            assert bootstrap.DATABASE_OBJECTS[0] == existing_db

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

    def test_create_database_missing_user(self, db_container):
        """Test database creation with missing user field"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            bootstrap.DATABASE_OBJECTS.clear()

            # Create database with missing user
            incomplete_db = Database(name="incomplete_db", password="test_password", dsn="test_dsn")

            with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
                databases.create_database(incomplete_db)

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

    def test_create_database_missing_password(self, db_container):
        """Test database creation with missing password field"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            bootstrap.DATABASE_OBJECTS.clear()

            # Create database with missing password
            incomplete_db = Database(name="incomplete_db", user="test_user", dsn="test_dsn")

            with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
                databases.create_database(incomplete_db)

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

    def test_create_database_missing_dsn(self, db_container):
        """Test database creation with missing dsn field"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            bootstrap.DATABASE_OBJECTS.clear()

            # Create database with missing dsn
            incomplete_db = Database(name="incomplete_db", user="test_user", password="test_password")

            with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
                databases.create_database(incomplete_db)

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

    def test_create_database_multiple_missing_fields(self, db_container):
        """Test database creation with multiple missing required fields"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            bootstrap.DATABASE_OBJECTS.clear()

            # Create database with multiple missing fields
            incomplete_db = Database(name="incomplete_db")

            with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
                databases.create_database(incomplete_db)

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

    def test_delete_database(self, db_container):
        """Test database deletion"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            # Setup test data
            db1 = Database(name="test_db_1", user="user1", password="pass1", dsn="dsn1")
            db2 = Database(name="test_db_2", user="user2", password="pass2", dsn="dsn2")
            db3 = Database(name="test_db_3", user="user3", password="pass3", dsn="dsn3")

            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend([db1, db2, db3])

            # Delete middle database
            databases.delete_database("test_db_2")

            # Verify deletion
            assert len(bootstrap.DATABASE_OBJECTS) == 2
            names = [db.name for db in bootstrap.DATABASE_OBJECTS]
            assert "test_db_1" in names
            assert "test_db_2" not in names
            assert "test_db_3" in names

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

    def test_delete_database_nonexistent(self, db_container):
        """Test deleting non-existent database"""
        assert db_container is not None

        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            # Setup test data
            db1 = Database(name="test_db_1", user="user1", password="pass1", dsn="dsn1")
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.append(db1)

            original_length = len(bootstrap.DATABASE_OBJECTS)

            # Try to delete non-existent database (should not raise error)
            databases.delete_database("nonexistent")

            # Verify no change
            assert len(bootstrap.DATABASE_OBJECTS) == original_length
            assert bootstrap.DATABASE_OBJECTS[0].name == "test_db_1"

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

    def test_delete_database_empty_list(self, db_container):
        """Test deleting from empty database list"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            bootstrap.DATABASE_OBJECTS.clear()

            # Try to delete from empty list (should not raise error)
            databases.delete_database("any_name")

            # Verify still empty
            assert len(bootstrap.DATABASE_OBJECTS) == 0

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

    def test_delete_database_multiple_same_name(self, db_container):
        """Test deleting when multiple databases have the same name"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            # Setup test data with duplicate names
            db1 = Database(name="duplicate", user="user1", password="pass1", dsn="dsn1")
            db2 = Database(name="duplicate", user="user2", password="pass2", dsn="dsn2")
            db3 = Database(name="other", user="user3", password="pass3", dsn="dsn3")

            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend([db1, db2, db3])

            # Delete databases with duplicate name
            databases.delete_database("duplicate")

            # Verify all duplicates are removed
            assert len(bootstrap.DATABASE_OBJECTS) == 1
            assert bootstrap.DATABASE_OBJECTS[0].name == "other"

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(databases, "logger")
        assert databases.logger.name == "api.core.database"

    def test_get_database_filters_correctly(self, db_container):
        """Test that get_database correctly filters by name"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            # Setup test data
            db1 = Database(name="alpha", user="user1", password="pass1", dsn="dsn1")
            db2 = Database(name="beta", user="user2", password="pass2", dsn="dsn2")
            db3 = Database(name="alpha", user="user3", password="pass3", dsn="dsn3")  # Duplicate name

            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend([db1, db2, db3])

            # Test getting all
            all_dbs = databases.get_database()
            assert len(all_dbs) == 3

            # Test getting by specific name
            alpha_dbs = databases.get_database(name="alpha")
            assert len(alpha_dbs) == 2
            assert all(db.name == "alpha" for db in alpha_dbs)

            beta_dbs = databases.get_database(name="beta")
            assert len(beta_dbs) == 1
            assert beta_dbs[0].name == "beta"

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)

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

    def test_create_database_real_scenario(self, db_container):
        """Test create_database with realistic data using container DB"""
        assert db_container is not None
        # Use real bootstrap DATABASE_OBJECTS
        original_db_objects = bootstrap.DATABASE_OBJECTS.copy()

        try:
            bootstrap.DATABASE_OBJECTS.clear()

            # Create database with realistic configuration
            test_db = Database(
                name="container_test",
                user="PYTEST",
                password="OrA_41_3xPl0d3r",
                dsn="//localhost:1525/FREEPDB1",
                tcp_connect_timeout=10,
            )

            result = databases.create_database(test_db)

            # Verify creation
            assert len(bootstrap.DATABASE_OBJECTS) == 1
            created_db = bootstrap.DATABASE_OBJECTS[0]
            assert created_db.name == "container_test"
            assert created_db.user == "PYTEST"
            assert created_db.dsn == "//localhost:1525/FREEPDB1"
            assert created_db.tcp_connect_timeout == 10
            assert result == [test_db]

        finally:
            # Restore original state
            bootstrap.DATABASE_OBJECTS.clear()
            bootstrap.DATABASE_OBJECTS.extend(original_db_objects)
