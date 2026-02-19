"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared helpers for API test modules.
"""
# pylint: disable=redefined-outer-name import-outside-toplevel

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

MODULES_TO_RELOAD = (
    "server.app.main",
    "server.app.core.config",
    "server.app.api.deps",
    "server.app.api.v1.router",
    "server.app.api.v1.endpoints",
    "server.app.api.v1.endpoints.probes",
    "server.app.api.v1.endpoints.settings",
    "server.app.api.v1.schemas",
    "server.app.api.v1.schemas.settings",
    "server.app.database",
    "server.app.database.config",
    "server.app.database.settings",
    "server.app.oci",
    "server.app.oci.config",
    "server.app.oci.settings",
)


@pytest.fixture
def app_client(monkeypatch):
    """Build a TestClient after setting env vars and reloading the app."""

    def _make(env_vars: dict | None = None):
        for key in ("AIO_DB_USERNAME", "AIO_DB_PASSWORD", "AIO_DB_DSN"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv("AIO_API_KEY", raising=False)
        monkeypatch.delenv("AIO_SERVER_URL_PREFIX", raising=False)

        if env_vars:
            for key, value in env_vars.items():
                monkeypatch.setenv(key, value)

        for mod in MODULES_TO_RELOAD:
            sys.modules.pop(mod, None)

        main = importlib.import_module("server.app.main")
        return TestClient(main.app)

    return _make
