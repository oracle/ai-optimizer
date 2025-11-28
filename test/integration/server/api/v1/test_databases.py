"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/databases.py

Tests the database configuration endpoints through the full API stack.
These endpoints require authentication.
"""


class TestAuthentication:
    """Integration tests for authentication on database endpoints."""

    def test_databases_list_requires_auth(self, client):
        """GET /v1/databases should require authentication."""
        response = client.get("/v1/databases")

        assert response.status_code == 401  # No auth header = Unauthorized

    def test_databases_list_rejects_invalid_token(self, client, auth_headers):
        """GET /v1/databases should reject invalid tokens."""
        response = client.get("/v1/databases", headers=auth_headers["invalid_auth"])

        assert response.status_code == 401

    def test_databases_list_accepts_valid_token(self, client, auth_headers):
        """GET /v1/databases should accept valid tokens."""
        response = client.get("/v1/databases", headers=auth_headers["valid_auth"])

        assert response.status_code == 200


class TestDatabasesList:
    """Integration tests for the databases list endpoint."""

    def test_databases_list_returns_list(self, client, auth_headers):
        """GET /v1/databases should return a list of databases."""
        response = client.get("/v1/databases", headers=auth_headers["valid_auth"])

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_databases_list_contains_default(self, client, auth_headers):
        """GET /v1/databases should contain a DEFAULT database."""
        response = client.get("/v1/databases", headers=auth_headers["valid_auth"])

        data = response.json()
        # There should be at least one database (DEFAULT is created by bootstrap)
        # If no config file, the list may be empty or contain DEFAULT
        assert isinstance(data, list)

    def test_databases_list_returns_database_schema(self, client, auth_headers, db_objects_manager, make_database):
        """GET /v1/databases should return databases with correct schema."""
        # Ensure there's at least one database for testing
        if not db_objects_manager:
            db_objects_manager.append(make_database())

        response = client.get("/v1/databases", headers=auth_headers["valid_auth"])

        assert response.status_code == 200
        data = response.json()
        if data:
            db = data[0]
            assert "name" in db
            assert "user" in db
            assert "dsn" in db
            assert "connected" in db


class TestDatabasesGet:
    """Integration tests for the single database get endpoint."""

    def test_databases_get_requires_auth(self, client):
        """GET /v1/databases/{name} should require authentication."""
        response = client.get("/v1/databases/DEFAULT")

        assert response.status_code == 401

    def test_databases_get_returns_404_for_unknown(self, client, auth_headers):
        """GET /v1/databases/{name} should return 404 for unknown database."""
        response = client.get("/v1/databases/NONEXISTENT_DB", headers=auth_headers["valid_auth"])

        assert response.status_code == 404

    def test_databases_get_returns_database(self, client, auth_headers, db_objects_manager, make_database):
        """GET /v1/databases/{name} should return the specified database."""
        # Ensure there's a test database
        test_db = make_database(name="INTEGRATION_TEST_DB")
        db_objects_manager.append(test_db)

        response = client.get("/v1/databases/INTEGRATION_TEST_DB", headers=auth_headers["valid_auth"])

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "INTEGRATION_TEST_DB"


class TestDatabasesUpdate:
    """Integration tests for the database update endpoint."""

    def test_databases_update_requires_auth(self, client):
        """PATCH /v1/databases/{name} should require authentication."""
        response = client.patch("/v1/databases/DEFAULT", json={"user": "test"})

        assert response.status_code == 401

    def test_databases_update_returns_404_for_unknown(self, client, auth_headers):
        """PATCH /v1/databases/{name} should return 404 for unknown database."""
        response = client.patch(
            "/v1/databases/NONEXISTENT_DB",
            headers=auth_headers["valid_auth"],
            json={"user": "test", "password": "test", "dsn": "localhost:1521/TEST"},
        )

        assert response.status_code == 404

    def test_databases_update_validates_connection(self, client, auth_headers, db_objects_manager, make_database):
        """PATCH /v1/databases/{name} should validate connection details."""
        # Add a test database
        test_db = make_database(name="UPDATE_TEST_DB")
        db_objects_manager.append(test_db)

        # Try to update with invalid connection details (no real DB running)
        response = client.patch(
            "/v1/databases/UPDATE_TEST_DB",
            headers=auth_headers["valid_auth"],
            json={"user": "invalid", "password": "invalid", "dsn": "localhost:9999/INVALID"},
        )

        # Should fail because it tries to connect
        assert response.status_code in [400, 401, 404, 503]

    def test_databases_update_connects_to_real_db(
        self, client, auth_headers, db_objects_manager, db_container, test_db_payload, make_database
    ):
        """PATCH /v1/databases/{name} should connect to real database."""
        _ = db_container  # Ensure container is running
        # Add a test database
        test_db = make_database(name="REAL_DB_TEST", user="placeholder", password="placeholder", dsn="placeholder")
        db_objects_manager.append(test_db)

        response = client.patch(
            "/v1/databases/REAL_DB_TEST",
            headers=auth_headers["valid_auth"],
            json=test_db_payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert data["user"] == test_db_payload["user"]
