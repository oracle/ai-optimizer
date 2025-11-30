"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for server API integration tests.

Integration tests use a real FastAPI TestClient with the actual application,
testing the full request/response cycle through the API layer.

Note: Shared fixtures (make_database, make_model, db_container, db_connection, etc.)
are automatically available via pytest_plugins in test/conftest.py.

Environment Setup:
    Environment variables are managed via the session-scoped `server_test_env` fixture,
    which the `app` fixture depends on. This ensures proper isolation and explicit
    dependency ordering.
"""

# pylint: disable=redefined-outer-name

import os
import asyncio
from typing import Generator

# Import constants needed by fixtures and test configuration in this file
from tests.db_fixtures import TEST_DB_CONFIG
from tests.shared_fixtures import (
    DEFAULT_LL_MODEL_CONFIG,
    TEST_AUTH_TOKEN,
    ALL_TEST_ENV_VARS,
)

import numpy as np

import pytest
from fastapi.testclient import TestClient

from server.bootstrap.bootstrap import DATABASE_OBJECTS, MODEL_OBJECTS, SETTINGS_OBJECTS

# Test configuration - extends shared DB config with integration-specific settings
TEST_CONFIG = {
    "client": "integration_test",
    "auth_token": TEST_AUTH_TOKEN,
    **TEST_DB_CONFIG,
}


#################################################
# Environment Setup (Session-Scoped)
#################################################
@pytest.fixture(scope="session")
def server_test_env():
    """Session-scoped fixture to set up environment for server integration tests.

    This fixture:
    1. Saves the original environment state
    2. Clears all test-related environment variables
    3. Sets the required variables for the test server
    4. Restores the original state when the session ends

    The `app` fixture depends on this to ensure environment is configured
    before the FastAPI application is created.
    """
    # Save original environment state
    original_env = {var: os.environ.get(var) for var in ALL_TEST_ENV_VARS}

    # Also capture dynamic OCI_ vars
    dynamic_oci_vars = [v for v in os.environ if v.startswith("OCI_") and v not in ALL_TEST_ENV_VARS]
    for var in dynamic_oci_vars:
        original_env[var] = os.environ.get(var)

    # Clear all test-related vars
    for var in ALL_TEST_ENV_VARS:
        os.environ.pop(var, None)
    for var in dynamic_oci_vars:
        os.environ.pop(var, None)

    # Set required environment variables for test server
    os.environ["CONFIG_FILE"] = "/non/existent/path/config.json"  # Use empty config
    os.environ["OCI_CLI_CONFIG_FILE"] = "/non/existent/path"  # Prevent OCI config pickup
    os.environ["API_SERVER_KEY"] = TEST_CONFIG["auth_token"]

    yield

    # Restore original environment state
    for var, value in original_env.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]


#################################################
# Authentication Headers
#################################################
@pytest.fixture
def auth_headers():
    """Return common header configurations for testing."""
    return {
        "no_auth": {},
        "invalid_auth": {"Authorization": "Bearer invalid-token", "client": TEST_CONFIG["client"]},
        "valid_auth": {"Authorization": f"Bearer {TEST_CONFIG['auth_token']}", "client": TEST_CONFIG["client"]},
    }


@pytest.fixture
def test_client_auth_headers(test_client_settings):
    """Auth headers using test_client for endpoints that require client settings.

    Use this fixture for endpoints that look up client settings via the client header.
    It ensures the test_client exists in SETTINGS_OBJECTS before returning headers.
    """
    return {
        "no_auth": {},
        "invalid_auth": {"Authorization": "Bearer invalid-token", "client": test_client_settings},
        "valid_auth": {"Authorization": f"Bearer {TEST_CONFIG['auth_token']}", "client": test_client_settings},
    }


#################################################
# FastAPI Test Client
#################################################
@pytest.fixture(scope="session")
def app(server_test_env):
    """Create the FastAPI application for testing.

    This fixture creates the actual FastAPI app using the same factory
    function as the production server (launch_server.create_app).

    Depends on server_test_env to ensure environment variables are
    configured before any application modules are loaded.
    """
    # pylint: disable=import-outside-toplevel
    _ = server_test_env  # Ensure env is set up first
    from launch_server import create_app

    return asyncio.run(create_app())


@pytest.fixture(scope="session")
def client(app) -> Generator[TestClient, None, None]:
    """Create a TestClient for the FastAPI app.

    The TestClient allows making HTTP requests to the app without
    starting a real server, enabling fast integration testing.
    """
    with TestClient(app) as test_client:
        yield test_client


#################################################
# Test Data Helpers
#################################################
@pytest.fixture
def test_db_payload():
    """Get standard test database payload for integration tests."""
    return {
        "user": TEST_CONFIG["db_username"],
        "password": TEST_CONFIG["db_password"],
        "dsn": TEST_CONFIG["db_dsn"],
    }


@pytest.fixture
def sample_model_payload():
    """Sample model configuration for testing."""
    return {
        "id": "test-model",
        "type": "ll",
        "provider": "openai",
        "enabled": True,
    }


@pytest.fixture
def sample_settings_payload():
    """Sample settings configuration for testing."""
    return {
        "client": TEST_CONFIG["client"],
        "ll_model": DEFAULT_LL_MODEL_CONFIG.copy(),
    }


@pytest.fixture
def mock_embedding_model():
    """Provides a mock embedding model for testing.

    Returns a function that simulates embedding generation by returning random vectors.
    """

    def mock_embed_documents(texts: list[str]) -> list[list[float]]:
        """Mock function that returns random embeddings for testing"""
        return [np.random.rand(384).tolist() for _ in texts]  # 384 is a common embedding dimension

    return mock_embed_documents


#################################################
# State Management Helpers
#################################################
@pytest.fixture
def db_objects_manager():
    """Fixture to manage DATABASE_OBJECTS save/restore operations.

    This fixture saves the current state of DATABASE_OBJECTS before each test
    and restores it afterward, ensuring tests don't affect each other.
    """
    original_db_objects = DATABASE_OBJECTS.copy()
    yield DATABASE_OBJECTS
    DATABASE_OBJECTS.clear()
    DATABASE_OBJECTS.extend(original_db_objects)


@pytest.fixture
def test_client_settings(settings_objects_manager):
    """Ensure test_client exists in SETTINGS_OBJECTS for integration tests.

    Many endpoints use the client header to look up client settings.
    This fixture adds a test_client to SETTINGS_OBJECTS if not present.
    """
    # Import here to avoid circular imports
    from common.schema import Settings  # pylint: disable=import-outside-toplevel

    # Check if test_client already exists
    existing = next((s for s in settings_objects_manager if s.client == "test_client"), None)
    if not existing:
        # Create test_client settings based on default
        default = next((s for s in settings_objects_manager if s.client == "default"), None)
        if default:
            test_settings = Settings(**default.model_dump())
            test_settings.client = "test_client"
            settings_objects_manager.append(test_settings)
    return "test_client"


@pytest.fixture
def model_objects_manager():
    """Fixture to manage MODEL_OBJECTS save/restore operations."""
    original_model_objects = MODEL_OBJECTS.copy()
    yield MODEL_OBJECTS
    MODEL_OBJECTS.clear()
    MODEL_OBJECTS.extend(original_model_objects)


@pytest.fixture
def settings_objects_manager():
    """Fixture to manage SETTINGS_OBJECTS save/restore operations."""
    original_settings_objects = SETTINGS_OBJECTS.copy()
    yield SETTINGS_OBJECTS
    SETTINGS_OBJECTS.clear()
    SETTINGS_OBJECTS.extend(original_settings_objects)
