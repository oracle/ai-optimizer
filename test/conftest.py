"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for unit tests with real Oracle database.
Adapts the Docker container pattern from tests/conftest.py.
"""

# pylint: disable=consider-using-with
# pylint: disable=redefined-outer-name
# Pytest fixtures use parameter injection where fixture names match parameters

import time
import shutil
from pathlib import Path
from typing import Generator, Optional
from contextlib import contextmanager

import pytest
import oracledb
import docker
from docker.errors import DockerException
from docker.models.containers import Container


# Test database configuration - matches tests/conftest.py
TEST_CONFIG = {
    "db_username": "PYTEST",
    "db_password": "OrA_41_3xPl0d3r",
    "db_dsn": "//localhost:1525/FREEPDB1",
}


def wait_for_container_ready(container: Container, ready_output: str, since: Optional[int] = None) -> None:
    """Wait for container to be ready by checking its logs with exponential backoff."""
    start_time = time.time()
    retry_interval = 2

    while time.time() - start_time < 120:  # 2 minute timeout
        try:
            logs = container.logs(tail=100, since=since).decode("utf-8")
            if ready_output in logs:
                return
        except DockerException as e:
            container.remove(force=True)
            raise DockerException(f"Failed to get container logs: {str(e)}") from e

        time.sleep(retry_interval)
        retry_interval = min(retry_interval * 2, 10)  # Exponential backoff, max 10 seconds

    container.remove(force=True)
    raise TimeoutError("Container did not become ready within timeout")


@contextmanager
def temp_sql_setup():
    """Context manager for temporary SQL setup files."""
    temp_dir = Path("test/db_startup_temp")
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
                    "ORACLE_PDB": TEST_CONFIG["db_dsn"].rsplit("/", maxsplit=1)[-1],  # FREEPDB1
                },
                ports={"1521/tcp": int(TEST_CONFIG["db_dsn"].split(":")[1].split("/")[0])},  # 1525
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


@pytest.fixture(scope="session")
def db_connection(db_container) -> Generator[oracledb.Connection, None, None]:
    """Session-scoped real Oracle database connection.

    Depends on db_container to ensure database is running.
    Fails explicitly if connection cannot be established.
    """
    # pylint: disable=unused-argument
    conn = oracledb.connect(
        user=TEST_CONFIG["db_username"],
        password=TEST_CONFIG["db_password"],
        dsn=TEST_CONFIG["db_dsn"],
    )
    yield conn
    conn.close()


@pytest.fixture
def db_transaction(db_connection) -> Generator[oracledb.Connection, None, None]:
    """Transaction isolation for each test using savepoints.

    Creates a savepoint before each test and rolls back after,
    ensuring tests don't affect each other's database state.

    Note: This is NOT autouse - tests must explicitly request it
    to get transaction isolation. This allows tests that don't
    need database access to run without the overhead.
    """
    cursor = db_connection.cursor()
    cursor.execute("SAVEPOINT test_savepoint")

    yield db_connection

    cursor.execute("ROLLBACK TO SAVEPOINT test_savepoint")
    cursor.close()
