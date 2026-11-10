"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/upl.

Real-Oracle validation for client-managed local server bootstrap.
"""

import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import oracledb
import pytest
from pydantic import SecretStr

from client.app.core import api
from client.app.core.local_bootstrap import LocalCoreConfig
from tests.oracle import TEST_DB_CONFIG

pytestmark = [pytest.mark.db, pytest.mark.integration]

_ADMIN_USERNAME = "AIO_LOCAL_ADMIN"
_ADMIN_PASSWORD = TEST_DB_CONFIG["db_password"]


def _unused_local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_local_bootstrap_starts_server_with_real_core(oracle_db_container, tmp_path):
    """The server stays live and unready until its authenticator is installed."""
    del oracle_db_container
    core = LocalCoreConfig(
        username=TEST_DB_CONFIG["db_username"],
        password=SecretStr(TEST_DB_CONFIG["db_password"]),
        dsn=TEST_DB_CONFIG["db_dsn"],
    )
    local_settings = SimpleNamespace(
        server_url="http://localhost",
        server_address="127.0.0.1",
        server_port=_unused_local_port(),
        server_ssl=False,
        server_ssl_cert_file="",
        server_ssl_key_file="",
        server_url_prefix="",
        api_key=None,
    )
    server_state = {"process": None, "log_file": None}
    original_spawn = api._spawn_server
    child_environment = {
        **os.environ,
        **core.child_environment(),
        "AIO_AUTH_MODE": "single_user",
        "AIO_INSTALLATION_ID": "local-bootstrap-integration",
        "AIO_ADMIN_DATABASE_USERNAME": _ADMIN_USERNAME,
    }

    with (
        oracledb.connect(
            user=TEST_DB_CONFIG["db_username"],
            password=TEST_DB_CONFIG["db_password"],
            dsn=TEST_DB_CONFIG["db_dsn"],
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(f'CREATE END USER "{_ADMIN_USERNAME}" IDENTIFIED BY "{_ADMIN_PASSWORD}"')

    setup_environment = {
        **child_environment,
        "AIO_AUTH_ADMIN_PASSWORD": _ADMIN_PASSWORD,
    }
    setup_environment.pop("AIO_API_KEY", None)
    setup = subprocess.run(
        [sys.executable, "-m", "server.app.auth.setup"],
        cwd=Path(__file__).resolve().parents[3],
        env=setup_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert setup.returncode == 0, setup.stderr

    def _spawn_with_test_log(port, environment, _log_path):
        return original_spawn(port, environment, tmp_path / "local-server.log")

    with (
        patch.object(api, "settings", local_settings),
        patch.object(api, "_SERVER", server_state),
        patch.object(api, "_spawn_server", side_effect=_spawn_with_test_log),
        patch.dict(api.os.environ, {}, clear=False),
    ):
        try:
            assert api.start_server(child_environment) is True
            readiness = httpx.get(
                f"http://127.0.0.1:{local_settings.server_port}/v1/readiness",
                timeout=5,
            )
            assert readiness.status_code == 503
            assert readiness.json() == {
                "detail": "Authentication authority is unavailable: "
                "Authentication for the configured mode is not initialized"
            }
        finally:
            api.stop_server()
