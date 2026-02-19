"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=redefined-outer-name

import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import docker
from docker.errors import DockerException
import oracledb
import pytest


TEST_DB_CONFIG = {
    "db_username": "PYTEST",
    "db_password": "OrA_41_3xPl0d3r",
    "db_dsn": "//localhost:1525/FREEPDB1",
}

ORACLE_IMAGE = "container-registry.oracle.com/database/free:latest-lite"
CONTAINER_NAME = "server-test-oracle"
READY_LOG_MARKER = "DATABASE IS READY TO USE!"


def _write_startup_scripts(temp_dir: Path) -> None:
    """Write SQL setup files into the temp directory."""
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


def _wait_for_ready(container, timeout: int = 300) -> None:
    start = time.time()
    while time.time() - start < timeout:
        logs = container.logs(tail=200).decode("utf-8", errors="ignore")
        if READY_LOG_MARKER in logs:
            return
        time.sleep(5)
    raise TimeoutError("Oracle container did not become ready in time")


def _remove_existing(client) -> None:
    try:
        existing = client.containers.list(all=True, filters={"name": CONTAINER_NAME})
    except DockerException:
        return
    for container in existing:
        try:
            container.remove(force=True)
        except DockerException:
            pass
        time.sleep(1)


@contextmanager
def _oracle_container() -> Generator:
    try:
        client = docker.from_env()
    except DockerException as exc:  # pragma: no cover - unit tests mock this
        pytest.skip(f"Docker not available: {exc}", allow_module_level=True)

    _remove_existing(client)

    temp_dir = Path(tempfile.mkdtemp(prefix="server_db_startup_"))
    temp_dir.chmod(0o755)
    container = None
    try:
        _write_startup_scripts(temp_dir)
        container = client.containers.run(
            ORACLE_IMAGE,
            name=CONTAINER_NAME,
            environment={
                "ORACLE_PWD": TEST_DB_CONFIG["db_password"],
                "ORACLE_PDB": TEST_DB_CONFIG["db_dsn"].rsplit("/", maxsplit=1)[-1],
            },
            ports={"1521/tcp": int(TEST_DB_CONFIG["db_dsn"].split(":")[1].split("/")[0])},
            volumes={str(temp_dir.absolute()): {"bind": "/opt/oracle/scripts/startup", "mode": "ro"}},
            detach=True,
        )
        _wait_for_ready(container)
        yield container
    finally:
        if container is not None:
            try:
                container.stop(timeout=60)
                container.remove()
            except DockerException:
                pass
            time.sleep(1)
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def oracle_db_container() -> Generator:
    """Session-scoped Oracle container for integration tests."""
    with _oracle_container() as container:
        yield container


@pytest.fixture(scope="session")
def oracle_connection(oracle_db_container):
    """Provide a real Oracle connection for integration tests."""
    del oracle_db_container
    conn: oracledb.Connection | None = None
    retries = 6
    for attempt in range(retries):
        try:
            conn = oracledb.connect(
                user=TEST_DB_CONFIG["db_username"],
                password=TEST_DB_CONFIG["db_password"],
                dsn=TEST_DB_CONFIG["db_dsn"],
            )
            break
        except oracledb.DatabaseError:
            if attempt == retries - 1:
                raise
            time.sleep(5)
    assert conn is not None
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def configure_db_env(monkeypatch, oracle_db_container):
    """Set database environment variables for the server during tests."""
    del oracle_db_container
    monkeypatch.setenv("AIO_DB_USERNAME", TEST_DB_CONFIG["db_username"])
    monkeypatch.setenv("AIO_DB_PASSWORD", TEST_DB_CONFIG["db_password"])
    monkeypatch.setenv("AIO_DB_DSN", TEST_DB_CONFIG["db_dsn"])
    monkeypatch.delenv("AIO_DB_WALLET_PASSWORD", raising=False)
    yield
