"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=protected-access import-error import-outside-toplevel consider-using-with

import os
import sys
import time
import socket
import shutil
import subprocess
from pathlib import Path
from typing import Generator, Optional
from contextlib import contextmanager

import requests
import numpy as np
import pytest
import docker
from docker.errors import DockerException
from docker.models.containers import Container

# This contains all the environment variables we consume on startup (add as required)
# Used to clear testing environment from users env; Do before any additional imports
API_VARS = ["API_SERVER_KEY", "API_SERVER_URL", "API_SERVER_PORT"]
DB_VARS = ["DB_USERNAME", "DB_PASSWORD", "DB_DSN", "DB_WALLET_PASSWORD", "TNS_ADMIN"]
MODEL_VARS = ["ON_PREM_OLLAMA_URL", "ON_PREM_HF_URL", "OPENAI_API_KEY", "PPLX_API_KEY", "COHERE_API_KEY"]
for env_var in [*API_VARS, *DB_VARS, *MODEL_VARS, *[var for var in os.environ if var.startswith("OCI_")]]:
    os.environ.pop(env_var, None)

# Setup a Test Configurations
TEST_CONFIG = {
    "client": "server",
    "auth_token": "testing-token",
    "db_username": "PYTEST",
    "db_password": "OrA_41_3xPl0d3r",
    "db_dsn": "//localhost:1525/FREEPDB1",
}

# Environments for Client/Server
os.environ["CONFIG_FILE"] = "/non/existant/path/config.json"  # Prevent picking up an exported settings file
os.environ["OCI_CLI_CONFIG_FILE"] = "/non/existant/path"  # Prevent picking up default OCI config file
os.environ["API_SERVER_KEY"] = TEST_CONFIG["auth_token"]
os.environ["API_SERVER_URL"] = "http://localhost"
os.environ["API_SERVER_PORT"] = "8015"

# Import rest of required modules
from fastapi.testclient import TestClient  # pylint: disable=wrong-import-position
from streamlit.testing.v1 import AppTest  # pylint: disable=wrong-import-position


#################################################
# Fixures for tests/server
#################################################
@pytest.fixture(name="auth_headers")
def _auth_headers():
    """Return common header configurations for testing."""
    return {
        "no_auth": {},
        "invalid_auth": {"Authorization": "Bearer invalid-token", "client": TEST_CONFIG["client"]},
        "valid_auth": {"Authorization": f"Bearer {TEST_CONFIG['auth_token']}", "client": TEST_CONFIG["client"]},
    }


@pytest.fixture(scope="session")
def client():
    """Create a test client for the FastAPI app."""
    # Lazy Load
    import asyncio
    from launch_server import create_app

    app = asyncio.run(create_app())
    return TestClient(app)


@pytest.fixture
def mock_embedding_model():
    """
    This fixture provides a mock embedding model for testing.
    It returns a function that simulates embedding generation by returning random vectors.
    """

    def mock_embed_documents(texts: list[str]) -> list[list[float]]:
        """Mock function that returns random embeddings for testing"""
        return [np.random.rand(384).tolist() for _ in texts]  # 384 is a common embedding dimension

    return mock_embed_documents


@pytest.fixture
def db_objects_manager():
    """
    Fixture to manage DATABASE_OBJECTS save/restore operations.
    This reduces code duplication across tests that need to manipulate DATABASE_OBJECTS.
    """
    from server.bootstrap.bootstrap import DATABASE_OBJECTS

    original_db_objects = DATABASE_OBJECTS.copy()
    yield DATABASE_OBJECTS
    DATABASE_OBJECTS.clear()
    DATABASE_OBJECTS.extend(original_db_objects)


#################################################
# Fixures for tests/client
#################################################
@pytest.fixture(scope="session")
def app_server(request):
    """Start the FastAPI server for Streamlit and wait for it to be ready"""

    def is_port_in_use(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("localhost", port)) == 0

    config_file = getattr(request, "param", None)

    # If config_file is passed, include it in the subprocess command
    cmd = ["python", "launch_server.py"]
    if config_file:
        cmd.extend(["-c", config_file])

    server_process = subprocess.Popen(cmd, cwd="src")

    try:
        # Wait for server to be ready (up to 30 seconds)
        max_wait = 30
        start_time = time.time()
        while not is_port_in_use(8015):
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
    """Establish Streamlit State for Client to Operate

    This fixture mimics what launch_client.py does in init_configs_state(),
    loading the full configuration including all *_configs (database_configs, model_configs,
    oci_configs, etc.) into session state, just like the real application does.
    """

    def _app_test(page):
        at = AppTest.from_file(page, default_timeout=30)
        at.session_state.server = {
            "key": os.environ.get("API_SERVER_KEY"),
            "url": os.environ.get("API_SERVER_URL"),
            "port": int(os.environ.get("API_SERVER_PORT")),
            "control": True,
        }
        # Load full config like launch_client.py does in init_configs_state()
        full_config = requests.get(
            url=f"{at.session_state.server['url']}:{at.session_state.server['port']}/v1/settings",
            headers=auth_headers["valid_auth"],
            params={
                "client": TEST_CONFIG["client"],
                "full_config": True,
                "incl_sensitive": True,
                "incl_readonly": True,
            },
            timeout=120,
        ).json()
        # Load all config items into session state (database_configs, model_configs, oci_configs, etc.)
        for key, value in full_config.items():
            at.session_state[key] = value
        return at

    return _app_test


def setup_test_database(app_test_instance):
    """Configure and connect to test database for integration tests

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
    db_config["user"] = TEST_CONFIG["db_username"]
    db_config["password"] = TEST_CONFIG["db_password"]
    db_config["dsn"] = TEST_CONFIG["db_dsn"]

    # Update the database on the server to establish connection
    server_url = app_test_instance.session_state.server["url"]
    server_port = app_test_instance.session_state.server["port"]
    server_key = app_test_instance.session_state.server["key"]
    db_name = db_config["name"]

    response = requests.patch(
        url=f"{server_url}:{server_port}/v1/databases/{db_name}",
        headers={"Authorization": f"Bearer {server_key}", "client": "server"},
        json={"user": db_config["user"], "password": db_config["password"], "dsn": db_config["dsn"]},
        timeout=120,
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to update database: {response.text}")

    # Reload the full config to get the updated database status
    full_config = requests.get(
        url=f"{server_url}:{server_port}/v1/settings",
        headers={"Authorization": f"Bearer {server_key}", "client": TEST_CONFIG["client"]},
        params={
            "client": TEST_CONFIG["client"],
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
    """Enable at least one LL model for testing

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
    """Enable at least one embedding model for testing

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
    """Create a mock for st.tabs that captures what tabs are created

    This is a helper function to reduce code duplication in tests that need
    to verify which tabs are created by the application.

    Args:
        monkeypatch: pytest monkeypatch fixture

    Returns:
        A list that will be populated with tab names as they are created
    """
    import streamlit as st

    tabs_created = []
    original_tabs = st.tabs

    def mock_tabs(tab_list):
        tabs_created.extend(tab_list)
        return original_tabs(tab_list)

    monkeypatch.setattr(st, "tabs", mock_tabs)
    return tabs_created


@contextmanager
def temporary_sys_path(path):
    """Temporarily add a path to sys.path and remove it when done

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
    """Helper to run a Streamlit test and verify no exceptions

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


def get_test_db_payload():
    """Get standard test database payload for integration tests

    Returns:
        dict: Database configuration payload with test credentials
    """
    return {
        "user": TEST_CONFIG["db_username"],
        "password": TEST_CONFIG["db_password"],
        "dsn": TEST_CONFIG["db_dsn"],
    }


def get_sample_oci_config():
    """Get sample OCI configuration for unit tests

    Returns:
        OracleCloudSettings: Sample OCI configuration object
    """
    from common.schema import OracleCloudSettings

    return OracleCloudSettings(
        auth_profile="DEFAULT",
        compartment_id="ocid1.compartment.oc1..test",
        genai_region="us-ashburn-1",
        user="ocid1.user.oc1..testuser",
        fingerprint="test-fingerprint",
        tenancy="ocid1.tenancy.oc1..testtenant",
        key_file="/path/to/key.pem",
    )


#################################################
# Container for DB Tests
#################################################
def wait_for_container_ready(container: Container, ready_output: str, since: Optional[int] = None) -> None:
    """Wait for container to be ready by checking its logs with exponential backoff."""
    start_time = time.time()
    retry_interval = 2

    while time.time() - start_time < 60:
        try:
            logs = container.logs(tail=100, since=since).decode("utf-8")
            if ready_output in logs:
                return
        except DockerException as e:
            container.remove(force=True)
            raise DockerException(f"Failed to get container logs: {str(e)}") from e

        time.sleep(retry_interval)
        retry_interval = min(retry_interval * 2, 60)  # Exponential backoff, max 10 seconds

    container.remove(force=True)
    raise TimeoutError("Container did not become ready timeout")


@contextmanager
def temp_sql_setup():
    """Context manager for temporary SQL setup files."""
    temp_dir = Path("tests/db_startup_temp")
    try:
        temp_dir.mkdir(exist_ok=True)
        sql_content = f"""
        alter system set vector_memory_size=512M scope=spfile;

        alter session set container=FREEPDB1;
        CREATE TABLESPACE IF NOT EXISTS USERS DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/users_01.dbf' SIZE 100M;
        CREATE USER IF NOT EXISTS "{TEST_CONFIG["db_username"]}" IDENTIFIED BY {TEST_CONFIG["db_password"]}
            DEFAULT TABLESPACE "USERS"
            TEMPORARY TABLESPACE "TEMP";
        GRANT "DB_DEVELOPER_ROLE" TO "{TEST_CONFIG["db_username"]}";
        ALTER USER "{TEST_CONFIG["db_username"]}" DEFAULT ROLE ALL;
        ALTER USER "{TEST_CONFIG["db_username"]}" QUOTA UNLIMITED ON USERS;

        EXIT;
        """

        temp_sql_file = temp_dir / "01_db_user.sql"
        temp_sql_file.write_text(sql_content, encoding="UTF-8")
        yield temp_dir
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


@pytest.fixture(scope="session")
def db_container() -> Generator[Container, None, None]:
    """Create and manage an Oracle database container for testing."""
    db_client = docker.from_env()
    container = None

    try:
        with temp_sql_setup() as temp_dir:
            container = db_client.containers.run(
                "container-registry.oracle.com/database/free:latest-lite",
                environment={
                    "ORACLE_PWD": TEST_CONFIG["db_password"],
                    "ORACLE_PDB": TEST_CONFIG["db_dsn"].split("/")[3],
                },
                ports={"1521/tcp": int(TEST_CONFIG["db_dsn"].split("/")[2].split(":")[1])},
                volumes={str(temp_dir.absolute()): {"bind": "/opt/oracle/scripts/startup", "mode": "ro"}},
                detach=True,
            )

            # Wait for database to be ready
            wait_for_container_ready(container, "DATABASE IS READY TO USE!")

            # Restart container to apply vector_memory_size
            container.restart()
            restart_time = int(time.time())
            wait_for_container_ready(container, "DATABASE IS READY TO USE!", since=restart_time)

            yield container

    except DockerException as e:
        if container:
            container.remove(force=True)
        raise DockerException(f"Docker operation failed: {str(e)}") from e

    finally:
        if container:
            try:
                container.stop(timeout=30)
                container.remove()
            except DockerException as e:
                print(f"Warning: Failed to cleanup database container: {str(e)}")


#################################################
# Shared Test Data for Vector Store Tests
#################################################
@pytest.fixture
def sample_vector_store_data():
    """Sample vector store data for testing - standard configuration"""
    return {
        "alias": "test_alias",
        "model": "openai/text-embed-3",
        "chunk_size": 1000,
        "chunk_overlap": 200,
        "distance_metric": "cosine",
        "index_type": "IVF",
        "vector_store": "vs_test"
    }


@pytest.fixture
def sample_vector_store_data_alt():
    """Alternative sample vector store data for testing - different configuration"""
    return {
        "alias": "alias2",
        "model": "openai/text-embed-3",
        "chunk_size": 500,
        "chunk_overlap": 100,
        "distance_metric": "euclidean",
        "index_type": "HNSW",
        "vector_store": "vs2"
    }


@pytest.fixture
def sample_vector_stores_list(sample_vector_store_data, sample_vector_store_data_alt):  # pylint: disable=redefined-outer-name
    """List of sample vector stores with different aliases for filtering tests"""
    vs1 = sample_vector_store_data.copy()
    vs1["alias"] = "vs1"
    vs1.pop("vector_store", None)  # Remove vector_store field for filtering tests

    vs2 = sample_vector_store_data_alt.copy()
    vs2["alias"] = "vs2"
    vs2.pop("vector_store", None)  # Remove vector_store field for filtering tests

    return [vs1, vs2]
