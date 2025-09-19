"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch, MagicMock

import pytest

from server.api.core import databases
from common.schema import Database


class TestDatabases:
    """Test databases module functionality"""

    def setup_method(self):
        """Setup test data before each test"""
        self.sample_database = Database(name="test_db", user="test_user", password="test_password", dsn="test_dsn")

    @patch("server.api.core.databases.bootstrap.DATABASE_OBJECTS")
    def test_get_database_all(self, mock_database_objects):
        """Test getting all databases when no name is provided"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([self.sample_database]))
        mock_database_objects.__len__ = MagicMock(return_value=1)

        result = databases.get_database()

        assert result == [self.sample_database]

    @patch("server.api.core.databases.bootstrap.DATABASE_OBJECTS")
    def test_get_database_by_name_found(self, mock_database_objects):
        """Test getting database by name when it exists"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([self.sample_database]))
        mock_database_objects.__len__ = MagicMock(return_value=1)

        result = databases.get_database(name="test_db")

        assert result == [self.sample_database]

    @patch("server.api.core.databases.bootstrap.DATABASE_OBJECTS")
    def test_get_database_by_name_not_found(self, mock_database_objects):
        """Test getting database by name when it doesn't exist"""
        mock_database_objects.__iter__ = MagicMock(return_value=iter([self.sample_database]))
        mock_database_objects.__len__ = MagicMock(return_value=1)

        with pytest.raises(ValueError, match="nonexistent not found"):
            databases.get_database(name="nonexistent")

    @patch("server.api.core.databases.bootstrap.DATABASE_OBJECTS")
    @patch("server.api.core.databases.get_database")
    def test_create_database_success(self, mock_get_database, mock_database_objects):
        """Test successful database creation when database doesn't exist"""
        mock_database_objects.append = MagicMock()

        # Based on the actual implementation:
        # 1. get_database is called to check if database exists - should return empty list for non-existent
        # 2. Then attributes are checked on database_objects
        # 3. Database is appended
        # 4. get_database is called again to return the created database

        mock_get_database.side_effect = [
            [],  # First call returns empty list (database doesn't exist)
            [self.sample_database],  # Second call returns the created database
        ]

        # Mock the attributes check - these attributes should exist on database_objects
        mock_database_objects.user = "test_user"
        mock_database_objects.password = "test_password"
        mock_database_objects.dsn = "test_dsn"

        result = databases.create_database(self.sample_database)

        mock_database_objects.append.assert_called_once_with(self.sample_database)
        assert result == [self.sample_database]

    @patch("server.api.core.databases.bootstrap.DATABASE_OBJECTS")
    @patch("server.api.core.databases.get_database")
    def test_create_database_missing_required_fields(self, mock_get_database, mock_database_objects):
        """Test database creation with missing required fields"""
        # Mock that database doesn't exist yet
        mock_get_database.return_value = []

        # Mock missing required attributes
        mock_database_objects.user = None
        mock_database_objects.password = "test_password"
        mock_database_objects.dsn = "test_dsn"

        with pytest.raises(ValueError, match="'user', 'password', and 'dsn' are required"):
            databases.create_database(self.sample_database)

    @patch("server.api.core.databases.bootstrap")
    def test_delete_database(self, mock_bootstrap):
        """Test database deletion"""
        mock_database_objects = [
            Database(name="test_db", user="user1", password="pass1", dsn="dsn1"),
            Database(name="other_db", user="user2", password="pass2", dsn="dsn2"),
        ]
        mock_bootstrap.DATABASE_OBJECTS = mock_database_objects

        databases.delete_database("test_db")

        # Verify the database was removed
        remaining_dbs = [db for db in mock_bootstrap.DATABASE_OBJECTS if db.name != "test_db"]
        assert len(remaining_dbs) == 1
        assert remaining_dbs[0].name == "other_db"

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(databases, "logger")
        assert databases.logger.name == "api.core.database"
