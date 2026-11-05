"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/upl.

Real-Oracle validation for client-managed local server bootstrap.
"""

import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from client.app.core import api
from client.app.core.local_bootstrap import LocalCoreConfig
from tests.oracle import TEST_DB_CONFIG

pytestmark = [pytest.mark.db, pytest.mark.integration]


def _unused_local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_local_bootstrap_starts_server_with_real_core(oracle_db_container, tmp_path):
    """Submitted local credentials pass the normal server lifespan gate."""
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

    def _spawn_with_test_log(port, environment, _log_path):
        return original_spawn(port, environment, tmp_path / "local-server.log")

    with (
        patch.object(api, "settings", local_settings),
        patch.object(api, "_SERVER", server_state),
        patch.object(api, "_spawn_server", side_effect=_spawn_with_test_log),
        patch.dict(api.os.environ, {}, clear=False),
    ):
        try:
            assert api.start_server(core.child_environment()) is True
            loaded = api.get_server_settings("local-bootstrap-test")
            assert loaded is not None
            assert any(database["alias"] == "CORE" for database in loaded["database_configs"])
        finally:
            api.stop_server()
