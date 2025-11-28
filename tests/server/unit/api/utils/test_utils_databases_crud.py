"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=protected-access import-error import-outside-toplevel

from unittest.mock import patch, MagicMock

import pytest

from server.api.utils import databases
from server.api.utils.databases import DbException
from common.schema import Database


class TestDatabases:
    """Test databases module functionality"""

    sample_database: Database
    sample_database_2: Database

    def setup_method(self):
        """Setup test data before each test"""
        self.sample_database = Database(name="test_db", user="test_user", password="test_password", dsn="test_dsn")
        self.sample_database_2 = Database(
            name="test_db_2", user="test_user_2", password="test_password_2", dsn="test_dsn_2"
        )

    # test_get_all: See test/unit/server/api/utils/test_utils_databases.py::TestGet::test_get_all_databases
    # test_get_by_name_found: See test/unit/server/api/utils/test_utils_databases.py::TestGet::test_get_specific_database
    # test_get_by_name_not_found: See test/unit/server/api/utils/test_utils_databases.py::TestGet::test_get_raises_unknown_error

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

    # test_create_success: See test/unit/server/api/utils/test_utils_databases.py::TestCreate::test_create_success
    # test_create_already_exists: See test/unit/server/api/utils/test_utils_databases.py::TestCreate::test_create_raises_exists_error
    # test_create_missing_user: See test/unit/server/api/utils/test_utils_databases.py::TestCreate::test_create_raises_value_error_missing_fields

    def test_create_missing_password(self, db_container, db_objects_manager):
        """Test database creation with missing password field"""
        assert db_container is not None
        assert db_objects_manager is not None
        databases.DATABASE_OBJECTS.clear()

        # Create database with missing password
        incomplete_db = Database(name="incomplete_db", user="test_user", dsn="test_dsn")

        with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
            databases.create(incomplete_db)

    def test_create_missing_dsn(self, db_container, db_objects_manager):
        """Test database creation with missing dsn field"""
        assert db_container is not None
        assert db_objects_manager is not None
        databases.DATABASE_OBJECTS.clear()

        # Create database with missing dsn
        incomplete_db = Database(name="incomplete_db", user="test_user", password="test_password")

        with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
            databases.create(incomplete_db)

    def test_create_multiple_missing_fields(self, db_container, db_objects_manager):
        """Test database creation with multiple missing required fields"""
        assert db_container is not None
        assert db_objects_manager is not None
        databases.DATABASE_OBJECTS.clear()

        # Create database with multiple missing fields
        incomplete_db = Database(name="incomplete_db")

        with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
            databases.create(incomplete_db)

    # test_delete: See test/unit/server/api/utils/test_utils_databases.py::TestDelete::test_delete_removes_database

    def test_delete_nonexistent(self, db_container, db_objects_manager):
        """Test deleting non-existent database"""
        assert db_container is not None
        assert db_objects_manager is not None

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

    def test_delete_empty_list(self, db_container, db_objects_manager):
        """Test deleting from empty database list"""
        assert db_container is not None
        assert db_objects_manager is not None
        databases.DATABASE_OBJECTS.clear()

        # Try to delete from empty list (should not raise error)
        databases.delete("any_name")

        # Verify still empty
        assert len(databases.DATABASE_OBJECTS) == 0

    def test_delete_multiple_same_name(self, db_container, db_objects_manager):
        """Test deleting when multiple databases have the same name"""
        assert db_container is not None
        assert db_objects_manager is not None
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

    # test_logger_exists: See test/unit/server/api/utils/test_utils_databases.py::TestLoggerConfiguration::test_logger_exists

    def test_get_filters_correctly(self, db_container, db_objects_manager):
        """Test that get correctly filters by name"""
        assert db_container is not None
        assert db_objects_manager is not None
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

    def test_create_real_scenario(self, db_container, db_objects_manager):
        """Test create with realistic data using container DB"""
        assert db_container is not None
        assert db_objects_manager is not None
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


class TestDbException:
    """Test custom database exception class"""

    # test_db_exception_initialization: See test/unit/server/api/utils/test_utils_databases.py::TestDbException::test_db_exception_init

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
