"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for server API integration tests.

Integration tests use a real FastAPI TestClient with the actual application,
testing the full request/response cycle through the API layer.

Note: db_container fixture is inherited from test/conftest.py - do not import here.
"""

# pylint: disable=redefined-outer-name unused-import
# Pytest fixtures use parameter injection where fixture names match parameters

import os
import asyncio
from typing import Generator

# Re-export shared fixtures for pytest discovery (before third-party imports per pylint)
from test.db_fixtures import TEST_DB_CONFIG
from test.shared_fixtures import (
    make_database,
    make_model,
    DEFAULT_LL_MODEL_CONFIG,
    TEST_AUTH_TOKEN,
)

import numpy as np

import pytest
from fastapi.testclient import TestClient

from server.bootstrap.bootstrap import DATABASE_OBJECTS, MODEL_OBJECTS, SETTINGS_OBJECTS


# Clear environment variables that could interfere with tests
# This must happen before importing application modules
API_VARS = ["API_SERVER_KEY", "API_SERVER_URL", "API_SERVER_PORT"]
DB_VARS = ["DB_USERNAME", "DB_PASSWORD", "DB_DSN", "DB_WALLET_PASSWORD", "TNS_ADMIN"]
MODEL_VARS = ["ON_PREM_OLLAMA_URL", "ON_PREM_HF_URL", "OPENAI_API_KEY", "PPLX_API_KEY", "COHERE_API_KEY"]
for env_var in [*API_VARS, *DB_VARS, *MODEL_VARS, *[var for var in os.environ if var.startswith("OCI_")]]:
    os.environ.pop(env_var, None)

# Test configuration - extends shared DB config with integration-specific settings
TEST_CONFIG = {
    "client": "integration_test",
    "auth_token": TEST_AUTH_TOKEN,
    **TEST_DB_CONFIG,
}

# Set environment variables for test server
os.environ["CONFIG_FILE"] = "/non/existent/path/config.json"  # Use empty config
os.environ["OCI_CLI_CONFIG_FILE"] = "/non/existent/path"  # Prevent OCI config pickup
os.environ["API_SERVER_KEY"] = TEST_CONFIG["auth_token"]


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
def app():
    """Create the FastAPI application for testing.

    This fixture creates the actual FastAPI app using the same factory
    function as the production server (launch_server.create_app).

    Import is done inside the fixture to ensure environment variables
    are set before any application modules are loaded.
    """
    # pylint: disable=import-outside-toplevel
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
