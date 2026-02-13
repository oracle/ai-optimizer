"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared database fixtures and utilities for tests.

This module provides Oracle database container management and connection
fixtures for both unit and integration tests.

FIXTURES (choose based on your test needs):

    db_container (session)
        Raw Docker container. Rarely needed directly.

    db_connection (session)
        Shared connection for the entire test session.
        Use when you need low-level connection access.

    db_transaction (function)
        Connection with savepoint-based isolation.
        Best for DML tests (INSERT/UPDATE/DELETE).
        WARNING: DDL operations (CREATE TABLE) invalidate savepoints!

    db_cursor (function)
        Convenience cursor with automatic cleanup.
        No transaction isolation - use for simple queries.

    db_clean (function)
        For tests with DDL operations (CREATE TABLE, etc.).
        Tracks and drops tables after test completes.
        Usage: table = db_clean.register("MY_TABLE")

    db_module_connection (module)
        Module-scoped connection for tests sharing state.
        Use when multiple tests need the same tables/data.

FIXTURE SELECTION GUIDE:

    Test Type                    | Recommended Fixture
    -----------------------------|--------------------
    Simple SELECT queries        | db_cursor
    INSERT/UPDATE/DELETE         | db_transaction
    CREATE TABLE / DDL           | db_clean
    Multiple related tests       | db_module_connection
    Custom connection handling   | db_connection

Tests using any of these fixtures are automatically marked with
'db' and 'slow' markers, enabling:

    pytest -m "not db"      # Skip database tests
    pytest -m "not slow"    # Skip slow tests (includes DB tests)
    pytest -m "db"          # Run only database tests
"""

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


# Database fixture names that trigger auto-marking
DB_FIXTURE_NAMES = {
    "db_container",
    "db_connection",
    "db_transaction",
    "db_cursor",
    "db_clean",
    "db_module_connection",
}


def pytest_collection_modifyitems(items):
    """Automatically mark tests using database fixtures with 'db' and 'slow' markers.

    This hook inspects each test's fixture requirements and adds markers
    to tests that use db_container, db_connection, or db_transaction fixtures.
    """
    for item in items:
        # Get the fixture names this test uses
        try:
            fixture_names = set(item.fixturenames)
        except AttributeError:
            continue

        # If test uses any DB fixture, mark it
        if fixture_names & DB_FIXTURE_NAMES:
            item.add_marker(pytest.mark.db)
            item.add_marker(pytest.mark.slow)


# Test database configuration - shared across all tests
TEST_DB_CONFIG = {
    "db_username": "PYTEST",
    "db_password": "OrA_41_3xPl0d3r",
    "db_dsn": "//localhost:1525/FREEPDB1",
}


def wait_for_container_ready(
    container: Container,
    ready_output: str,
    since: Optional[int] = None,
    timeout: int = 120,
) -> None:
    """Wait for container to be ready by checking its logs with exponential backoff.

    Args:
        container: Docker container to monitor
        ready_output: String to look for in logs indicating readiness
        since: Unix timestamp to filter logs from (optional)
        timeout: Maximum seconds to wait (default 120)

    Raises:
        TimeoutError: If container doesn't become ready within timeout
        DockerException: If there's an error getting container logs
    """
    start_time = time.time()
    retry_interval = 2

    while time.time() - start_time < timeout:
        try:
            logs = container.logs(tail=100, since=since).decode("utf-8")
            if ready_output in logs:
                return
        except DockerException as e:
            container.remove(force=True)
            raise DockerException(f"Failed to get container logs: {str(e)}") from e

        time.sleep(retry_interval)
        retry_interval = min(retry_interval * 2, 10)

    container.remove(force=True)
    raise TimeoutError("Container did not become ready within timeout")


@contextmanager
def temp_sql_setup(temp_dir_path: str = "tests/db_startup_temp"):
    """Context manager for temporary SQL setup files.

    Creates a temporary directory with SQL initialization scripts
    for the Oracle container.

    Args:
        temp_dir_path: Path for temporary directory

    Yields:
        Path object to the temporary directory
    """
    temp_dir = Path(temp_dir_path)
    try:
        temp_dir.mkdir(exist_ok=True)
        sql_content = f"""
        alter system set vector_memory_size=512M scope=spfile;

        alter session set container=FREEPDB1;
        CREATE TABLESPACE IF NOT EXISTS USERS DATAFILE '/opt/oracle/oradata/FREE/FREEPDB1/users_01.dbf' SIZE 100M;
        CREATE USER IF NOT EXISTS "{TEST_DB_CONFIG["db_username"]}" IDENTIFIED BY {TEST_DB_CONFIG["db_password"]}
            DEFAULT TABLESPACE "USERS"
            TEMPORARY TABLESPACE "TEMP";
        GRANT "DB_DEVELOPER_ROLE" TO "{TEST_DB_CONFIG["db_username"]}";
        ALTER USER "{TEST_DB_CONFIG["db_username"]}" DEFAULT ROLE ALL;
        ALTER USER "{TEST_DB_CONFIG["db_username"]}" QUOTA UNLIMITED ON USERS;

        EXIT;
        """

        temp_sql_file = temp_dir / "01_db_user.sql"
        temp_sql_file.write_text(sql_content, encoding="UTF-8")
        yield temp_dir
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def create_db_container(temp_dir_name: str = "tests/db_startup_temp") -> Generator[Container, None, None]:
    """Create and manage an Oracle database container for testing.

    This generator function handles the full lifecycle of a Docker-based
    Oracle database container for testing purposes.

    Args:
        temp_dir_name: Path for temporary SQL setup files

    Yields:
        Docker Container object for the running database

    Raises:
        DockerException: If Docker operations fail
    """
    db_client = docker.from_env()
    container = None

    try:
        with temp_sql_setup(temp_dir_name) as temp_dir:
            container = db_client.containers.run(
                "container-registry.oracle.com/database/free:latest-lite",
                environment={
                    "ORACLE_PWD": TEST_DB_CONFIG["db_password"],
                    "ORACLE_PDB": TEST_DB_CONFIG["db_dsn"].rsplit("/", maxsplit=1)[-1],
                },
                ports={"1521/tcp": int(TEST_DB_CONFIG["db_dsn"].split(":")[1].split("/")[0])},
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
def db_container() -> Generator[Container, None, None]:
    """Pytest fixture for Oracle database container.

    Session-scoped fixture that creates and manages an Oracle database
    container for the duration of the test session.
    """
    yield from create_db_container()


@pytest.fixture(scope="session")
def db_connection(db_container) -> Generator[oracledb.Connection, None, None]:
    """Session-scoped real Oracle database connection.

    Depends on db_container to ensure database is running.
    """
    _ = db_container  # Ensure container is running
    conn = oracledb.connect(
        user=TEST_DB_CONFIG["db_username"],
        password=TEST_DB_CONFIG["db_password"],
        dsn=TEST_DB_CONFIG["db_dsn"],
    )
    yield conn
    conn.close()


@pytest.fixture
def db_transaction(db_connection) -> Generator[oracledb.Connection, None, None]:
    """Transaction isolation for each test using savepoints.

    Creates a savepoint before each test and rolls back after,
    ensuring tests don't affect each other's database state.

    Note: DDL operations (CREATE TABLE, etc.) cause implicit commits
    in Oracle, which will invalidate the savepoint. Tests with DDL
    should use db_clean instead.

    Usage:
        def test_something(db_transaction):
            cursor = db_transaction.cursor()
            cursor.execute("INSERT INTO ...")
            # Changes are automatically rolled back after test
    """
    cursor = db_connection.cursor()
    cursor.execute("SAVEPOINT test_savepoint")

    yield db_connection

    cursor.execute("ROLLBACK TO SAVEPOINT test_savepoint")
    cursor.close()


@pytest.fixture
def db_cursor(db_connection) -> Generator[oracledb.Cursor, None, None]:
    """Provides a database cursor with automatic cleanup.

    Convenience fixture that creates a cursor and ensures it's closed
    after the test completes. Does not provide transaction isolation -
    use db_transaction for that.

    Usage:
        def test_something(db_cursor):
            db_cursor.execute("SELECT * FROM dual")
            result = db_cursor.fetchone()
    """
    cursor = db_connection.cursor()
    yield cursor
    cursor.close()


class TableTracker:
    """Helper class to track and clean up tables created during tests.

    This class provides methods to register tables for cleanup and
    automatically drops them when cleanup() is called.
    """

    def __init__(self, connection: oracledb.Connection):
        self.connection = connection
        self.tables: list[str] = []

    def register(self, table_name: str) -> str:
        """Register a table for cleanup after test.

        Args:
            table_name: Name of the table to track

        Returns:
            The table name (for convenience in chaining)
        """
        if table_name.upper() not in [t.upper() for t in self.tables]:
            self.tables.append(table_name)
        return table_name

    def cleanup(self) -> None:
        """Drop all registered tables.

        Silently ignores errors if tables don't exist.
        """
        cursor = self.connection.cursor()
        for table_name in reversed(self.tables):  # Reverse order for dependencies
            try:
                cursor.execute(f"DROP TABLE {table_name} PURGE")
            except oracledb.DatabaseError:
                pass  # Table might not exist or have dependencies
        try:
            self.connection.commit()
        except oracledb.DatabaseError:
            pass
        cursor.close()
        self.tables.clear()


@pytest.fixture
def db_clean(db_connection) -> Generator[TableTracker, None, None]:
    """Fixture for tests that perform DDL operations (CREATE TABLE, etc.).

    Unlike db_transaction which uses savepoints (invalidated by DDL),
    this fixture tracks tables created during the test and drops them
    during cleanup.

    Usage:
        def test_create_table(db_clean):
            cursor = db_clean.connection.cursor()

            # Register table BEFORE creating it
            table_name = db_clean.register("MY_TEST_TABLE")
            cursor.execute(f"CREATE TABLE {table_name} (id NUMBER)")

            # ... test logic ...

            # Table is automatically dropped after test

    For multiple tables with dependencies, register parent tables first:
        def test_with_foreign_key(db_clean):
            db_clean.register("PARENT_TABLE")
            db_clean.register("CHILD_TABLE")  # Will be dropped first
            # ...
    """
    tracker = TableTracker(db_connection)
    yield tracker
    tracker.cleanup()


@pytest.fixture(scope="module")
def db_module_connection(db_container) -> Generator[oracledb.Connection, None, None]:
    """Module-scoped database connection.

    Use this when multiple tests in a module need to share database state
    or when connection setup is expensive. Each module gets its own connection.

    Note: Tests using this fixture should be careful about state isolation.
    Consider using unique table names or cleaning up after each test.

    Usage:
        # In a test module
        def test_first(db_module_connection):
            # Uses shared connection for this module
            pass

        def test_second(db_module_connection):
            # Same connection as test_first
            pass
    """
    _ = db_container  # Ensure container is running
    conn = oracledb.connect(
        user=TEST_DB_CONFIG["db_username"],
        password=TEST_DB_CONFIG["db_password"],
        dsn=TEST_DB_CONFIG["db_dsn"],
    )
    yield conn
    conn.close()
