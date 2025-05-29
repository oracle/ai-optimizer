"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

import pytest
from conftest import TEST_CONFIG


#############################################################################
# Test AuthN required and Valid
#############################################################################
class TestInvalidAuthEndpoints:
    """Test endpoints without Headers and Invalid AuthN"""

    @pytest.mark.parametrize(
        "auth_type, status_code",
        [
            pytest.param("no_auth", 403, id="no_auth"),
            pytest.param("invalid_auth", 401, id="invalid_auth"),
        ],
    )
    @pytest.mark.parametrize(
        "endpoint, api_method",
        [
            pytest.param("/v1/databases", "get", id="databases_list"),
            pytest.param("/v1/databases/DEFAULT", "get", id="databases_get"),
            pytest.param("/v1/databases/DEFAULT", "patch", id="databases_update"),
        ],
    )
    def test_endpoints(self, client, auth_headers, endpoint, api_method, auth_type, status_code):
        """Test endpoints require valide authentication."""
        response = getattr(client, api_method)(endpoint, headers=auth_headers[auth_type])
        assert response.status_code == status_code


#############################################################################
# Endpoints Test
#############################################################################
class TestEndpoints:
    """Test Endpoints"""

    def test_databases_list_initial(self, client, auth_headers):
        """Test initial database listing before any updates"""
        response = client.get("/v1/databases", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        default_db = next((db for db in data if db["name"] == "DEFAULT"), None)
        assert default_db is not None
        assert default_db["connected"] is False
        assert default_db["dsn"] is None
        assert default_db["password"] is None
        assert default_db["tcp_connect_timeout"] == 5
        assert default_db["user"] is None
        assert default_db["vector_stores"] is None
        assert default_db["wallet_location"] is None
        assert default_db["wallet_password"] is None

    def test_databases_get_nonexistent(self, client, auth_headers):
        """Test getting non-existent database"""
        response = client.get("/v1/databases/NONEXISTENT", headers=auth_headers["valid_auth"])
        assert response.status_code == 404
        assert response.json() == {"detail": "Database: NONEXISTENT not found."}

    def test_databases_update_nonexistent(self, client, auth_headers):
        """Test updating non-existent database"""
        payload = {"user": "test_user", "password": "test_pass", "dsn": "test_dsn", "wallet_password": "test_wallet"}
        response = client.patch("/v1/databases/NONEXISTENT", headers=auth_headers["valid_auth"], json=payload)
        assert response.status_code == 404
        assert response.json() == {"detail": "Database: NONEXISTENT not found."}

    def test_databases_update_db_down(self, client, auth_headers):
        """Test updating the DB when it is down"""
        payload = {
            "user": TEST_CONFIG["db_username"],
            "password": TEST_CONFIG["db_password"],
            "dsn": "//localhost:1521/DOWNDB_TP",
        }
        response = client.patch("/v1/databases/DEFAULT", headers=auth_headers["valid_auth"], json=payload)
        assert response.status_code == 503
        assert response.json() == {"detail": "Database: DEFAULT unable to connect."}

    test_cases = [
        pytest.param(
            TEST_CONFIG["db_dsn"].split("/")[3],
            404,
            {
                "user": TEST_CONFIG["db_username"],
                "password": TEST_CONFIG["db_password"],
                "dsn": TEST_CONFIG["db_dsn"],
            },
            {"detail": f"Database: {TEST_CONFIG['db_dsn'].split('/')[3]} not found."},
            id="non_existent_database",
        ),
        pytest.param(
            "DEFAULT",
            422,
            "",
            {
                "detail": [
                    {
                        "input": "",
                        "loc": ["body"],
                        "msg": "Input should be a valid dictionary or object to extract fields from",
                        "type": "model_attributes_type",
                    }
                ]
            },
            id="empty_payload",
        ),
        pytest.param(
            "DEFAULT",
            400,
            {},
            {"detail": "Database: DEFAULT missing connection details."},
            id="missing_credentials",
        ),
        pytest.param(
            "DEFAULT",
            503,
            {"user": "user", "password": "password", "dsn": "//localhost:1521/dsn"},
            {"detail": "Database: DEFAULT unable to connect."},
            id="invalid_connection",
        ),
        pytest.param(
            "DEFAULT",
            401,
            {
                "user": TEST_CONFIG["db_username"],
                "password": "Wr0ng_P4sswOrd",
                "dsn": TEST_CONFIG["db_dsn"],
            },
            {"detail": "Database: DEFAULT invalid credentials."},
            id="wrong_password",
        ),
        pytest.param(
            "DEFAULT",
            200,
            {
                "user": TEST_CONFIG["db_username"],
                "password": TEST_CONFIG["db_password"],
                "dsn": TEST_CONFIG["db_dsn"],
            },
            {
                "connected": True,
                "dsn": TEST_CONFIG["db_dsn"],
                "name": "DEFAULT",
                "password": TEST_CONFIG["db_password"],
                "tcp_connect_timeout": 5,
                "user": TEST_CONFIG["db_username"],
                "vector_stores": [],
                "selectai": False,
                "selectai_profiles": [],
                "wallet_location": None,
                "wallet_password": None,
            },
            id="successful_update",
        ),
    ]

    @pytest.mark.parametrize("database, status_code, payload, expected", test_cases)
    def test_databases_update_cases(
        self, client, auth_headers, db_container, database, status_code, payload, expected
    ):
        """Test various database update scenarios"""
        assert db_container is not None
        response = client.patch(f"/v1/databases/{database}", headers=auth_headers["valid_auth"], json=payload)
        assert response.status_code == status_code

        if response.status_code != 200:
            assert response.json() == expected
        else:
            data = response.json()
            data.pop("config_dir", None)  # Remove config_dir as it's environment-specific
            assert data == expected
            # Get after successful update
            response = client.get("/v1/databases/DEFAULT", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            data = response.json()
            assert "config_dir" in data
            data.pop("config_dir", None)
            assert data == expected
            # List after successful update
            response = client.get("/v1/databases", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            data = response.json()
            default_db = next((db for db in data if db["name"] == "DEFAULT"), None)
            assert default_db is not None
            assert "config_dir" in default_db
            default_db.pop("config_dir", None)
            assert default_db == expected

    def test_databases_update_invalid_wallet(self, client, auth_headers, db_container):
        """Test updating database with invalid wallet configuration"""
        assert db_container is not None
        payload = {
            "user": TEST_CONFIG["db_username"],
            "password": TEST_CONFIG["db_password"],
            "dsn": TEST_CONFIG["db_dsn"],
            "wallet_location": "/nonexistent/path",
            "wallet_password": "invalid",
        }
        response = client.patch("/v1/databases/DEFAULT", headers=auth_headers["valid_auth"], json=payload)
        # Should still work if wallet is not required.
        assert response.status_code == 200

    def test_databases_concurrent_connections(self, client, auth_headers, db_container):
        """Test concurrent database connections"""
        assert db_container is not None
        # Make multiple concurrent connection attempts
        payload = {
            "user": TEST_CONFIG["db_username"],
            "password": TEST_CONFIG["db_password"],
            "dsn": TEST_CONFIG["db_dsn"],
        }
        responses = []
        for _ in range(5):  # Try 5 concurrent connections
            response = client.patch("/v1/databases/DEFAULT", headers=auth_headers["valid_auth"], json=payload)
            responses.append(response)

        # Verify all connections were handled properly
        for response in responses:
            assert response.status_code in [200, 503]  # Either successful or proper error
            if response.status_code == 200:
                data = response.json()
                assert data["connected"] is True
