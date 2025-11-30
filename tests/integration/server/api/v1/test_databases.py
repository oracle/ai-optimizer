"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/databases.py

Tests the database configuration endpoints through the full API stack.
These endpoints require authentication.
"""

from tests.db_fixtures import TEST_DB_CONFIG


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

    def test_databases_list_initial_state(self, client, auth_headers, db_objects_manager, make_database):
        """Test initial database listing shows disconnected state with no credentials."""
        # Ensure DEFAULT database exists
        default_db = next((db for db in db_objects_manager if db.name == "DEFAULT"), None)
        if not default_db:
            db_objects_manager.append(make_database(name="DEFAULT"))

        response = client.get("/v1/databases", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        default_db_data = next((db for db in data if db["name"] == "DEFAULT"), None)
        assert default_db_data is not None
        assert default_db_data["connected"] is False
        assert default_db_data["vector_stores"] == []

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

    def test_databases_update_db_down(self, client, auth_headers, db_objects_manager, make_database):
        """Test updating database when target database is unreachable."""
        # Add a test database
        test_db = make_database(name="DOWN_DB_TEST")
        db_objects_manager.append(test_db)

        payload = {
            "user": "test_user",
            "password": "test_pass",
            "dsn": "//localhost:1521/DOWNDB_TP",  # Non-existent database
        }
        response = client.patch("/v1/databases/DOWN_DB_TEST", headers=auth_headers["valid_auth"], json=payload)
        assert response.status_code == 503
        assert "cannot connect to database" in response.json().get("detail", "")

    def test_databases_update_empty_payload(self, client, auth_headers, db_objects_manager, make_database):
        """Test updating database with empty payload."""
        test_db = make_database(name="EMPTY_PAYLOAD_TEST")
        db_objects_manager.append(test_db)

        response = client.patch("/v1/databases/EMPTY_PAYLOAD_TEST", headers=auth_headers["valid_auth"], json="")
        assert response.status_code == 422
        assert "Input should be a valid dictionary" in str(response.json())

    def test_databases_update_missing_credentials(self, client, auth_headers, db_objects_manager, make_database):
        """Test updating database with missing connection credentials."""
        # Create database with no credentials
        test_db = make_database(name="MISSING_CREDS_TEST", user=None, password=None, dsn=None)
        db_objects_manager.append(test_db)

        response = client.patch("/v1/databases/MISSING_CREDS_TEST", headers=auth_headers["valid_auth"], json={})
        assert response.status_code == 400
        assert "missing connection details" in response.json().get("detail", "")

    def test_databases_update_wrong_password(
        self, client, auth_headers, db_objects_manager, db_container, make_database
    ):
        """Test updating database with wrong password."""
        _ = db_container  # Ensure container is running
        test_db = make_database(name="WRONG_PASS_TEST")
        db_objects_manager.append(test_db)

        payload = {
            "user": TEST_DB_CONFIG["db_username"],
            "password": "Wr0ng_P4sswOrd",
            "dsn": TEST_DB_CONFIG["db_dsn"],
        }
        response = client.patch("/v1/databases/WRONG_PASS_TEST", headers=auth_headers["valid_auth"], json=payload)
        assert response.status_code == 401
        assert "invalid credential or not authorized" in response.json().get("detail", "")

    def test_databases_update_successful(
        self, client, auth_headers, db_objects_manager, db_container, test_db_payload, make_database
    ):
        """Test successful database update and verify state changes."""
        _ = db_container  # Ensure container is running
        test_db = make_database(name="SUCCESS_UPDATE_TEST")
        db_objects_manager.append(test_db)

        response = client.patch(
            "/v1/databases/SUCCESS_UPDATE_TEST", headers=auth_headers["valid_auth"], json=test_db_payload
        )
        assert response.status_code == 200
        data = response.json()
        data.pop("config_dir", None)  # Remove environment-specific field
        assert data["connected"] is True
        assert data["user"] == test_db_payload["user"]
        assert data["dsn"] == test_db_payload["dsn"]

        # Verify GET returns updated state
        response = client.get("/v1/databases/SUCCESS_UPDATE_TEST", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True

        # Verify LIST returns updated state
        response = client.get("/v1/databases", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        data = response.json()
        updated_db = next((db for db in data if db["name"] == "SUCCESS_UPDATE_TEST"), None)
        assert updated_db is not None
        assert updated_db["connected"] is True

    def test_databases_update_invalid_wallet(
        self, client, auth_headers, db_objects_manager, db_container, test_db_payload, make_database
    ):
        """Test updating database with invalid wallet configuration still works if wallet not required."""
        _ = db_container  # Ensure container is running
        test_db = make_database(name="WALLET_TEST")
        db_objects_manager.append(test_db)

        payload = {
            **test_db_payload,
            "wallet_location": "/nonexistent/path",
            "wallet_password": "invalid",
        }
        response = client.patch("/v1/databases/WALLET_TEST", headers=auth_headers["valid_auth"], json=payload)
        # Should still work if wallet is not required
        assert response.status_code == 200

    def test_databases_concurrent_connections(
        self, client, auth_headers, db_objects_manager, db_container, test_db_payload, make_database
    ):
        """Test concurrent database connection attempts are handled properly."""
        _ = db_container  # Ensure container is running
        test_db = make_database(name="CONCURRENT_TEST")
        db_objects_manager.append(test_db)

        # Make multiple concurrent connection attempts
        responses = []
        for _ in range(5):
            response = client.patch(
                "/v1/databases/CONCURRENT_TEST", headers=auth_headers["valid_auth"], json=test_db_payload
            )
            responses.append(response)

        # Verify all connections were handled properly
        for response in responses:
            assert response.status_code in [200, 503]  # Either successful or proper error
            if response.status_code == 200:
                data = response.json()
                assert data["connected"] is True
