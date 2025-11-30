"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for client integration tests.

These fixtures provide Streamlit AppTest and FastAPI server management
for testing the client UI components.
"""

# pylint: disable=redefined-outer-name

import os
import sys
import time
import socket
import subprocess
from contextlib import contextmanager

# Re-export shared fixtures for pytest discovery
from test.shared_fixtures import (  # noqa: F401 pylint: disable=unused-import
    make_database,
    make_model,
    make_oci_config,
    make_ll_settings,
    make_settings,
    make_configuration,
    TEST_DB_USER,
    TEST_DB_PASSWORD,
    TEST_DB_DSN,
    TEST_AUTH_TOKEN,
    sample_vector_store_data,
    sample_vector_store_data_alt,
    sample_vector_stores_list,
)

# Import TEST_DB_CONFIG for use in helper functions
# Note: db_container, db_connection, db_transaction fixtures are inherited
# from test/conftest.py - do not re-import here to avoid multiple containers
from test.db_fixtures import TEST_DB_CONFIG

import pytest
import requests

# Lazy import to avoid circular imports - stored in module-level variable
_app_test_class = None


def get_app_test():
    """Lazy import of Streamlit's AppTest."""
    global _app_test_class  # pylint: disable=global-statement
    if _app_test_class is None:
        from streamlit.testing.v1 import AppTest  # pylint: disable=import-outside-toplevel

        _app_test_class = AppTest
    return _app_test_class


#################################################
# Environment Setup for Client Tests
#################################################

# Clear environment variables that might interfere with tests
API_VARS = ["API_SERVER_KEY", "API_SERVER_URL", "API_SERVER_PORT"]
DB_VARS = ["DB_USERNAME", "DB_PASSWORD", "DB_DSN", "DB_WALLET_PASSWORD", "TNS_ADMIN"]
MODEL_VARS = [
    "ON_PREM_OLLAMA_URL",
    "ON_PREM_HF_URL",
    "OPENAI_API_KEY",
    "PPLX_API_KEY",
    "COHERE_API_KEY",
]

for env_var in [
    *API_VARS,
    *DB_VARS,
    *MODEL_VARS,
    *[var for var in os.environ if var.startswith("OCI_")],
]:
    os.environ.pop(env_var, None)

# Test client configuration
TEST_CLIENT = "client_test"
TEST_SERVER_PORT = 8015

# Set up test environment
os.environ["CONFIG_FILE"] = "/non/existent/path/config.json"
os.environ["OCI_CLI_CONFIG_FILE"] = "/non/existent/path"
os.environ["API_SERVER_KEY"] = TEST_AUTH_TOKEN
os.environ["API_SERVER_URL"] = "http://localhost"
os.environ["API_SERVER_PORT"] = str(TEST_SERVER_PORT)


#################################################
# Fixtures for Client Tests
#################################################


@pytest.fixture(name="auth_headers")
def _auth_headers():
    """Return common header configurations for testing."""
    return {
        "no_auth": {},
        "invalid_auth": {"Authorization": "Bearer invalid-token", "client": TEST_CLIENT},
        "valid_auth": {"Authorization": f"Bearer {TEST_AUTH_TOKEN}", "client": TEST_CLIENT},
    }


@pytest.fixture(scope="session")
def app_server(request):
    """Start the FastAPI server for Streamlit and wait for it to be ready."""

    def is_port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("localhost", port)) == 0

    config_file = getattr(request, "param", None)

    # If config_file is passed, include it in the subprocess command
    cmd = ["python", "launch_server.py"]
    if config_file:
        cmd.extend(["-c", config_file])

    # Create environment with explicit port setting
    # This ensures the server uses the correct port even when other conftest files
    # may have modified os.environ during test collection
    env = os.environ.copy()
    env["API_SERVER_PORT"] = str(TEST_SERVER_PORT)
    env["API_SERVER_KEY"] = TEST_AUTH_TOKEN
    env["CONFIG_FILE"] = "/non/existent/path/config.json"
    env["OCI_CLI_CONFIG_FILE"] = "/non/existent/path"

    server_process = subprocess.Popen(cmd, cwd="src", env=env)  # pylint: disable=consider-using-with

    try:
        # Wait for server to be ready (up to 30 seconds)
        max_wait = 30
        start_time = time.time()
        while not is_port_in_use(TEST_SERVER_PORT):
            if time.time() - start_time > max_wait:
                raise TimeoutError("Server failed to start within 30 seconds")
            time.sleep(0.5)

        yield server_process

    finally:
        # Terminate the server after tests
        server_process.terminate()
        server_process.wait()


@pytest.fixture
def app_test(auth_headers):
    """Establish Streamlit State for Client to Operate.

    This fixture mimics what launch_client.py does in init_configs_state(),
    loading the full configuration including all *_configs (database_configs, model_configs,
    oci_configs, etc.) into session state, just like the real application does.
    """
    app_test_cls = get_app_test()

    def _app_test(page):
        # Convert relative paths like "../src/client/..." to absolute paths
        # Tests use paths relative to old structure, convert to absolute
        if page.startswith("../src/"):
            # Get project root (test/integration/client -> project root)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            page = os.path.join(project_root, page.replace("../src/", "src/"))
        at = app_test_cls.from_file(page, default_timeout=30)
        # Use constants directly instead of os.environ to avoid issues when
        # other conftest files pop these variables during test collection
        at.session_state.server = {
            "key": TEST_AUTH_TOKEN,
            "url": "http://localhost",
            "port": TEST_SERVER_PORT,
            "control": True,
        }
        server_url = f"{at.session_state.server['url']}:{at.session_state.server['port']}"

        # First, create the client (POST) - this initializes client settings on the server
        # If client already exists (409), that's fine - we just need it to exist
        requests.post(
            url=f"{server_url}/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": TEST_CLIENT},
            timeout=120,
        )

        # Load full config like launch_client.py does in init_configs_state()
        full_config = requests.get(
            url=f"{server_url}/v1/settings",
            headers=auth_headers["valid_auth"],
            params={
                "client": TEST_CLIENT,
                "full_config": True,
                "incl_sensitive": True,
                "incl_readonly": True,
            },
            timeout=120,
        ).json()
        # Load all config items into session state
        for key, value in full_config.items():
            at.session_state[key] = value
        return at

    return _app_test


#################################################
# Helper Functions
#################################################


def setup_test_database(app_test_instance):
    """Configure and connect to test database for integration tests.

    This helper function:
    1. Updates database config with test credentials
    2. Patches the database on the server
    3. Reloads full config to get updated database status

    Args:
        app_test_instance: The AppTest instance from app_test fixture

    Returns:
        The updated AppTest instance with database configured
    """
    if not app_test_instance.session_state.database_configs:
        return app_test_instance

    # Update database config with test credentials
    db_config = app_test_instance.session_state.database_configs[0]
    db_config["user"] = TEST_DB_CONFIG["db_username"]
    db_config["password"] = TEST_DB_CONFIG["db_password"]
    db_config["dsn"] = TEST_DB_CONFIG["db_dsn"]

    # Update the database on the server to establish connection
    server_url = app_test_instance.session_state.server["url"]
    server_port = app_test_instance.session_state.server["port"]
    server_key = app_test_instance.session_state.server["key"]
    db_name = db_config["name"]

    response = requests.patch(
        url=f"{server_url}:{server_port}/v1/databases/{db_name}",
        headers={"Authorization": f"Bearer {server_key}", "client": TEST_CLIENT},
        json={
            "user": db_config["user"],
            "password": db_config["password"],
            "dsn": db_config["dsn"],
        },
        timeout=120,
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to update database: {response.text}")

    # Reload the full config to get the updated database status
    full_config = requests.get(
        url=f"{server_url}:{server_port}/v1/settings",
        headers={"Authorization": f"Bearer {server_key}", "client": TEST_CLIENT},
        params={
            "client": TEST_CLIENT,
            "full_config": True,
            "incl_sensitive": True,
            "incl_readonly": True,
        },
        timeout=120,
    ).json()

    # Update session state with refreshed config
    for key, value in full_config.items():
        app_test_instance.session_state[key] = value

    return app_test_instance


def enable_test_models(app_test_instance):
    """Enable at least one LL model for testing.

    Args:
        app_test_instance: The AppTest instance from app_test fixture

    Returns:
        The updated AppTest instance with models enabled
    """
    for model in app_test_instance.session_state.model_configs:
        if model["type"] == "ll":
            model["enabled"] = True
            break

    return app_test_instance


def enable_test_embed_models(app_test_instance):
    """Enable at least one embedding model for testing.

    Args:
        app_test_instance: The AppTest instance from app_test fixture

    Returns:
        The updated AppTest instance with embed models enabled
    """
    for model in app_test_instance.session_state.model_configs:
        if model["type"] == "embed":
            model["enabled"] = True
            break

    return app_test_instance


def create_tabs_mock(monkeypatch):
    """Create a mock for st.tabs that captures what tabs are created.

    This is a helper function to reduce code duplication in tests that need
    to verify which tabs are created by the application.

    Args:
        monkeypatch: pytest monkeypatch fixture

    Returns:
        A list that will be populated with tab names as they are created
    """
    import streamlit as st  # pylint: disable=import-outside-toplevel

    tabs_created = []
    original_tabs = st.tabs

    def mock_tabs(tab_list):
        tabs_created.extend(tab_list)
        return original_tabs(tab_list)

    monkeypatch.setattr(st, "tabs", mock_tabs)
    return tabs_created


@contextmanager
def temporary_sys_path(path):
    """Temporarily add a path to sys.path and remove it when done.

    This context manager is useful for tests that need to temporarily modify
    the Python path to import modules from specific locations.

    Args:
        path: Path to add to sys.path

    Yields:
        None
    """
    sys.path.insert(0, path)
    try:
        yield
    finally:
        if path in sys.path:
            sys.path.remove(path)


def run_streamlit_test(app_test_instance, run=True):
    """Helper to run a Streamlit test and verify no exceptions.

    This helper reduces code duplication in tests that follow the pattern:
    1. Run the app test
    2. Verify no exceptions occurred

    Args:
        app_test_instance: The AppTest instance to run
        run: Whether to run the test (default: True)

    Returns:
        The AppTest instance (run or not based on the run parameter)
    """
    if run:
        app_test_instance = app_test_instance.run()
    assert not app_test_instance.exception
    return app_test_instance


def run_page_with_models_enabled(app_server, app_test_func, st_file):
    """Helper to run a Streamlit page with models enabled and verify no exceptions.

    Common test pattern that:
    1. Verifies app_server is available
    2. Creates app test instance
    3. Enables test models
    4. Runs the test
    5. Verifies no exceptions occurred

    Args:
        app_server: The app_server fixture (asserted not None)
        app_test_func: The app_test fixture function
        st_file: The Streamlit file path to test

    Returns:
        The AppTest instance after running
    """
    assert app_server is not None
    at = app_test_func(st_file)
    at = enable_test_models(at)
    at = at.run()
    assert not at.exception
    return at


def get_test_db_payload():
    """Get standard test database payload for integration tests.

    Returns:
        dict: Database configuration payload with test credentials
    """
    return {
        "user": TEST_DB_CONFIG["db_username"],
        "password": TEST_DB_CONFIG["db_password"],
        "dsn": TEST_DB_CONFIG["db_dsn"],
    }


def get_sample_oci_config():
    """Get sample OCI configuration for unit tests.

    Returns:
        OracleCloudSettings: Sample OCI configuration object
    """
    from common.schema import OracleCloudSettings  # pylint: disable=import-outside-toplevel

    return OracleCloudSettings(
        auth_profile="DEFAULT",
        compartment_id="ocid1.compartment.oc1..test",
        genai_region="us-ashburn-1",
        user="ocid1.user.oc1..testuser",
        fingerprint="test-fingerprint",
        tenancy="ocid1.tenancy.oc1..testtenant",
        key_file="/path/to/key.pem",
    )
