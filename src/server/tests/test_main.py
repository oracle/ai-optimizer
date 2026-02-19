"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.main configuration and routing.
"""
# spell-checker: disable
# pylint: disable=redefined-outer-name

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

MODULE_PATH = "server.app.main"


@pytest.fixture
def load_app(monkeypatch):
    """Reload the FastAPI app with an optional URL_PREFIX."""

    def _loader(root_path: str | None = None):
        if root_path is None:
            monkeypatch.delenv("AIO_SERVER_URL_PREFIX", raising=False)
        else:
            monkeypatch.setenv("AIO_SERVER_URL_PREFIX", root_path)

        # Prevent real DB connections during unit tests
        for key in ("AIO_DB_USERNAME", "AIO_DB_PASSWORD", "AIO_DB_DSN"):
            monkeypatch.delenv(key, raising=False)

        # Clear all dependent modules so settings/BASE_PATH are recreated
        for mod in (MODULE_PATH, "server.app.core.config", "server.app.database", "server.app.database.config"):
            sys.modules.pop(mod, None)
        return importlib.import_module(MODULE_PATH)

    return _loader


def test_liveness_without_root_path(load_app):
    """Responds on /v1 when URL_PREFIX unset."""
    main = load_app()
    with TestClient(main.app) as client:
        response = client.get("/v1/liveness")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert main.app.root_path == ""
    assert main.app.docs_url == f"{main.API_PREFIX}/docs"
    assert main.app.openapi_url == f"{main.API_PREFIX}/openapi.json"


def test_liveness_with_root_path(load_app):
    """Routes work and root_path is set when URL_PREFIX is configured."""
    main = load_app("demo")
    with TestClient(main.app, root_path="/demo") as client:
        response = client.get("/v1/liveness")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert main.app.root_path == "/demo"
