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
from server.api.utils import databases as utils_databases


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
        mock_get_databases.assert_called_once_with(validate=False)

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    async def test_databases_list_raises_404_on_value_error(self, mock_get_databases):
        """databases_list should raise 404 when ValueError occurs."""
        mock_get_databases.side_effect = ValueError("No databases found")

        with pytest.raises(HTTPException) as exc_info:
            await databases.databases_list()

        assert exc_info.value.status_code == 404
        mock_get_databases.assert_called_once_with(validate=False)


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
        mock_get_databases.assert_called_once_with(db_name="NONEXISTENT", validate=True)


class TestDatabasesUpdate:
    """Tests for the databases_update endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    @patch("server.api.v1.databases.utils_databases.connect")
    @patch("server.api.v1.databases.utils_databases.disconnect")
    async def test_databases_update_returns_updated_database(
        self, mock_disconnect, mock_connect, mock_get_databases, make_database, make_database_auth
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

        # Verify get_databases called twice: first to get target DB, second to get all DBs for cleanup
        assert mock_get_databases.call_count == 2
        mock_get_databases.assert_any_call(db_name="TEST_DB", validate=False)
        mock_get_databases.assert_any_call()

        # Verify connect was called with the payload (which has config_dir/wallet_location set from db)
        mock_connect.assert_called_once()
        connect_arg = mock_connect.call_args[0][0]
        assert connect_arg.user == "new_user"
        assert connect_arg.password == "new_pass"
        assert connect_arg.dsn == "localhost:1521/TEST"

        # Verify disconnect was NOT called (no other databases with connections)
        mock_disconnect.assert_not_called()

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    async def test_databases_update_raises_404_when_not_found(self, mock_get_databases, make_database_auth):
        """databases_update should raise 404 when database not found."""
        mock_get_databases.side_effect = ValueError("Database not found")

        payload = make_database_auth()

        with pytest.raises(HTTPException) as exc_info:
            await databases.databases_update(name="NONEXISTENT", payload=payload)

        assert exc_info.value.status_code == 404
        mock_get_databases.assert_called_once_with(db_name="NONEXISTENT", validate=False)

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    @patch("server.api.v1.databases.utils_databases.connect")
    async def test_databases_update_raises_400_on_db_exception(
        self, mock_connect, mock_get_databases, make_database, make_database_auth
    ):
        """databases_update should raise 400 on DbException with status 400 during connect."""
        existing_db = make_database(name="TEST_DB")
        mock_get_databases.return_value = existing_db
        mock_connect.side_effect = utils_databases.DbException(
            status_code=400, detail="Missing connection details"
        )

        payload = make_database_auth()

        with pytest.raises(HTTPException) as exc_info:
            await databases.databases_update(name="TEST_DB", payload=payload)

        assert exc_info.value.status_code == 400
        assert "Missing connection details" in exc_info.value.detail

        # Verify get_databases was called to retrieve the target database
        mock_get_databases.assert_called_once_with(db_name="TEST_DB", validate=False)

        # Verify connect was called with the test config
        mock_connect.assert_called_once()
        connect_arg = mock_connect.call_args[0][0]
        assert connect_arg.user == payload.user
        assert connect_arg.dsn == payload.dsn

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

        # Verify get_databases was called to retrieve the target database
        mock_get_databases.assert_called_once_with(db_name="TEST_DB", validate=False)

        # Verify connect was called with the payload
        mock_connect.assert_called_once()
        connect_arg = mock_connect.call_args[0][0]
        assert connect_arg.user == payload.user
        assert connect_arg.dsn == payload.dsn

    @pytest.mark.asyncio
    @patch("server.api.v1.databases.utils_databases.get_databases")
    @patch("server.api.v1.databases.utils_databases.connect")
    @patch("server.api.v1.databases.utils_databases.disconnect")
    async def test_databases_update_disconnects_other_databases(
        self, mock_disconnect, mock_connect, mock_get_databases, make_database, make_database_auth
    ):
        """databases_update should disconnect OTHER database connections, not the newly connected one.

        When connecting to a database, the system enforces single-connection mode:
        only one database can be connected at a time. This test verifies that when
        updating/connecting to TEST_DB, any existing connections on OTHER databases
        are properly disconnected using their own connection objects.

        Expected behavior:
        1. Connect to TEST_DB with new connection
        2. For each other database with an active connection, disconnect it
        3. The disconnect call should receive the OTHER database's connection
        4. The newly connected database's connection should remain intact
        """
        # Setup: TEST_DB is the database being updated
        target_db = make_database(name="TEST_DB", user="old_user")

        # Setup: OTHER_DB has an existing connection that should be disconnected
        other_db = make_database(name="OTHER_DB")
        other_db_existing_connection = MagicMock(name="other_db_connection")
        other_db.set_connection(other_db_existing_connection)
        other_db.connected = True

        # Setup: ANOTHER_DB has no connection (should not trigger disconnect)
        another_db = make_database(name="ANOTHER_DB")
        another_db.connected = False

        # Mock: First call returns target DB, second call returns all DBs for cleanup
        mock_get_databases.side_effect = [target_db, [target_db, other_db, another_db]]

        # Mock: New connection for TEST_DB
        new_connection = MagicMock(name="new_test_db_connection")
        mock_connect.return_value = new_connection

        # Mock: disconnect returns None (connection closed)
        mock_disconnect.return_value = None

        payload = make_database_auth(user="new_user", password="new_pass", dsn="localhost:1521/TEST")

        # Execute
        result = await databases.databases_update(name="TEST_DB", payload=payload)

        # Verify: Target database is connected with new connection
        assert result.connected is True
        assert result.user == "new_user"

        # Verify: disconnect was called exactly once (only OTHER_DB had a connection)
        mock_disconnect.assert_called_once()

        # CRITICAL ASSERTION: disconnect must be called with OTHER_DB's connection,
        # not the new TEST_DB connection
        actual_disconnect_arg = mock_disconnect.call_args[0][0]
        assert actual_disconnect_arg is other_db_existing_connection, (
            f"Expected disconnect to be called with other_db's connection, "
            f"but was called with: {actual_disconnect_arg}"
        )
        assert actual_disconnect_arg is not new_connection, (
            "disconnect should NOT be called with the newly created connection"
        )

        # Verify: OTHER_DB is now disconnected
        assert other_db.connected is False


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
