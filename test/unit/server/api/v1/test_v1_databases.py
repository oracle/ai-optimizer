"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/databases.py
Tests for database configuration endpoints.

Note: These tests mock utils_databases functions to test endpoint logic
(HTTP responses, error handling). The underlying database operations
are tested with real Oracle database in test_utils_databases.py.
"""

from unittest.mock import patch, MagicMock
import pytest
from fastapi import HTTPException

from server.api.v1 import databases


class TestDatabasesList:
    """Tests for the databases_list endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    async def test_databases_list_returns_all_databases(self, mock_get_databases, make_database):
        """databases_list should return all configured databases."""
        db_list = [
            make_database(name="DB1"),
            make_database(name="DB2"),
        ]
        mock_get_databases.return_value = db_list

        result = await databases.databases_list()

        assert result == db_list
        mock_get_databases.assert_called_once_with(validate=False)

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    async def test_databases_list_returns_empty_list(self, mock_get_databases):
        """databases_list should return empty list when no databases."""
        mock_get_databases.return_value = []

        result = await databases.databases_list()

        assert result == []

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    async def test_databases_list_raises_404_on_value_error(self, mock_get_databases):
        """databases_list should raise 404 when ValueError occurs."""
        mock_get_databases.side_effect = ValueError("No databases found")

        with pytest.raises(HTTPException) as exc_info:
            await databases.databases_list()

        assert exc_info.value.status_code == 404


class TestDatabasesGet:
    """Tests for the databases_get endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    async def test_databases_get_returns_single_database(self, mock_get_databases, make_database):
        """databases_get should return a single database by name."""
        database = make_database(name="TEST_DB")
        mock_get_databases.return_value = database

        result = await databases.databases_get(name="TEST_DB")

        assert result == database
        mock_get_databases.assert_called_once_with(db_name="TEST_DB", validate=True)

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    async def test_databases_get_raises_404_when_not_found(self, mock_get_databases):
        """databases_get should raise 404 when database not found."""
        mock_get_databases.side_effect = ValueError("Database not found")

        with pytest.raises(HTTPException) as exc_info:
            await databases.databases_get(name="NONEXISTENT")

        assert exc_info.value.status_code == 404


class TestDatabasesUpdate:
    """Tests for the databases_update endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    @patch("server.api.v1.databases.utils_databases.connect")
    @patch("server.api.v1.databases.utils_databases.disconnect")
    async def test_databases_update_returns_updated_database(
        self, _mock_disconnect, mock_connect, mock_get_databases, make_database, make_database_auth
    ):
        """databases_update should return the updated database."""
        existing_db = make_database(name="TEST_DB", user="old_user")
        # First call returns the single db, second call returns list for cleanup
        mock_get_databases.side_effect = [existing_db, [existing_db]]
        mock_connect.return_value = MagicMock()

        payload = make_database_auth(user="new_user", password="new_pass", dsn="localhost:1521/TEST")

        result = await databases.databases_update(name="TEST_DB", payload=payload)

        assert result.user == "new_user"
        assert result.connected is True

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    async def test_databases_update_raises_404_when_not_found(self, mock_get_databases, make_database_auth):
        """databases_update should raise 404 when database not found."""
        mock_get_databases.side_effect = ValueError("Database not found")

        payload = make_database_auth()

        with pytest.raises(HTTPException) as exc_info:
            await databases.databases_update(name="NONEXISTENT", payload=payload)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    @patch("server.api.v1.databases.utils_databases.connect")
    async def test_databases_update_raises_400_on_value_error(
        self, mock_connect, mock_get_databases, make_database, make_database_auth
    ):
        """databases_update should raise 400 on ValueError during connect."""
        existing_db = make_database(name="TEST_DB")
        mock_get_databases.return_value = existing_db
        mock_connect.side_effect = ValueError("Invalid parameters")

        payload = make_database_auth()

        with pytest.raises(HTTPException) as exc_info:
            await databases.databases_update(name="TEST_DB", payload=payload)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    @patch("server.api.v1.databases.utils_databases.connect")
    async def test_databases_update_raises_401_on_permission_error(
        self, mock_connect, mock_get_databases, make_database, make_database_auth
    ):
        """databases_update should raise 401 on PermissionError during connect."""
        existing_db = make_database(name="TEST_DB")
        mock_get_databases.return_value = existing_db
        mock_connect.side_effect = PermissionError("Access denied")

        payload = make_database_auth()

        with pytest.raises(HTTPException) as exc_info:
            await databases.databases_update(name="TEST_DB", payload=payload)

        assert exc_info.value.status_code == 401


class TestRouterConfiguration:
    """Tests for router configuration."""

    def test_auth_router_exists(self):
        """The auth router should be defined."""
        assert hasattr(databases, "auth")

    def test_auth_router_has_routes(self):
        """The auth router should have registered routes."""
        routes = [route.path for route in databases.auth.routes]

        assert "" in routes
        assert "/{name}" in routes


class TestLoggerConfiguration:
    """Tests for logger configuration."""

    def test_logger_exists(self):
        """Logger should be configured."""
        assert hasattr(databases, "logger")

    def test_logger_name(self):
        """Logger should have correct name."""
        assert databases.logger.name == "endpoints.v1.databases"
