"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error
# pylint: disable=wrong-import-position
# pylint: disable=import-outside-toplevel

import os

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
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

# For Database Container
import docker
from docker.errors import DockerException
from docker.models.containers import Container


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

    server_process = subprocess.Popen(cmd, cwd="src")  # pylint: disable=consider-using-with

    # Wait for server to be ready (up to 30 seconds)
    max_wait = 30
    start_time = time.time()
    while not is_port_in_use(8015):
        if time.time() - start_time > max_wait:
            server_process.terminate()
            server_process.wait()
            raise TimeoutError("Server failed to start within 30 seconds")
        time.sleep(0.5)

    yield server_process

    # Terminate the server after tests
    server_process.terminate()
    server_process.wait()


@pytest.fixture
def app_test(auth_headers):
    """Establish Streamlit State for Client to Operate"""

    def _app_test(page):
        at = AppTest.from_file(page, default_timeout=30)
        at.session_state.server = {
            "key": os.environ.get("API_SERVER_KEY"),
            "url": os.environ.get("API_SERVER_URL"),
            "port": int(os.environ.get("API_SERVER_PORT")),
            "control": True 
        }
        response = requests.get(
            url=f"{at.session_state.server['url']}:{at.session_state.server['port']}/v1/settings",
            headers=auth_headers["valid_auth"],
            params={"client": TEST_CONFIG["client"]},
            timeout=120,
        )
        at.session_state.client_settings = response.json()
        return at

    return _app_test


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
