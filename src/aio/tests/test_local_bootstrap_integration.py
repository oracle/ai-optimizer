"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/upl.

Real-Oracle validation for client-managed local server bootstrap.
"""

import socket
from contextlib import suppress
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

_ADMIN_USERNAME = TEST_DB_CONFIG["db_username"]
_ADMIN_PASSWORD = TEST_DB_CONFIG["db_password"]


def _unused_local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_local_bootstrap_starts_server_with_real_core(oracle_db_container, tmp_path):
    """The CORE database user authenticates as Admin through the local server lifecycle."""
    del oracle_db_container
    core = LocalCoreConfig(
        username=TEST_DB_CONFIG["db_username"],
        password=SecretStr(TEST_DB_CONFIG["db_password"]),
        dsn=TEST_DB_CONFIG["db_dsn"],
    )
    local_settings = SimpleNamespace(
        server_url="https://localhost",
        server_address="127.0.0.1",
        server_port=_unused_local_port(),
        server_ssl_cert_file="",
        server_ssl_key_file="",
        server_url_prefix="",
        api_key=None,
    )
    server_state = {"process": None, "log_file": None}
    original_spawn = api._spawn_server
    child_environment = core.child_environment()

    with (
        oracledb.connect(
            user=TEST_DB_CONFIG["db_username"],
            password=TEST_DB_CONFIG["db_password"],
            dsn=TEST_DB_CONFIG["db_dsn"],
        ) as connection,
        connection.cursor() as cursor,
    ):
        for table in ("AIO_AUTH_AUDIT", "AIO_AUTH_SESSIONS", "AIO_USERS", "AIO_AUTH_AUTHORITY"):
            with suppress(oracledb.DatabaseError):
                cursor.execute(f"DELETE FROM {table}")
        connection.commit()

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
                f"https://127.0.0.1:{local_settings.server_port}/v1/readiness",
                verify=False,
                timeout=5,
            )
            assert readiness.status_code == 200
            first_login = httpx.post(
                f"https://127.0.0.1:{local_settings.server_port}/v1/auth/login",
                verify=False,
                json={"username": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD},
                timeout=5,
            )
            assert first_login.status_code == 200, first_login.text
            first = first_login.json()
            headers = {"Authorization": f"Bearer {first['access_token']}"}
            profile = httpx.get(
                f"https://127.0.0.1:{local_settings.server_port}/v1/auth/me",
                verify=False,
                headers=headers,
                timeout=5,
            )
            assert profile.status_code == 200
            assert profile.json()["user_id"] == "f4304c28-4bf6-5e7d-a284-33cc0a5a6c01"
            logout = httpx.post(
                f"https://127.0.0.1:{local_settings.server_port}/v1/auth/logout",
                verify=False,
                headers=headers,
                timeout=5,
            )
            assert logout.status_code == 200
            assert (
                httpx.get(
                    f"https://127.0.0.1:{local_settings.server_port}/v1/auth/me",
                    verify=False,
                    headers=headers,
                    timeout=5,
                ).status_code
                == 401
            )
            api.stop_server()
            assert api.start_server(child_environment) is True
            second_login = httpx.post(
                f"https://127.0.0.1:{local_settings.server_port}/v1/auth/login",
                verify=False,
                json={"username": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD},
                timeout=5,
            )
            assert second_login.status_code == 200
            assert second_login.json()["principal"]["user_id"] == first["principal"]["user_id"]
        finally:
            api.stop_server()
