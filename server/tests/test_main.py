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
    """Reload the FastAPI app with an optional ROOT_PATH."""

    def _loader(root_path: str | None = None):
        if root_path is None:
            monkeypatch.delenv("ROOT_PATH", raising=False)
        else:
            monkeypatch.setenv("ROOT_PATH", root_path)

        sys.modules.pop(MODULE_PATH, None)
        return importlib.import_module(MODULE_PATH)

    return _loader


def test_liveness_without_root_path(load_app):
    """Responds on /v1 when ROOT_PATH unset."""
    main = load_app()
    with TestClient(main.app) as client:
        response = client.get("/v1/liveness")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert main.app.root_path == ""
    assert main.app.docs_url == f"{main.API_PREFIX}/docs"
    assert main.app.openapi_url == f"{main.API_PREFIX}/openapi.json"


def test_liveness_with_root_path(load_app):
    """Supports prefixed and direct access when ROOT_PATH set."""
    main = load_app("demo")
    with TestClient(main.app) as client:
        with_root = client.get("/demo/v1/liveness")
        direct = client.get("/v1/liveness")

    assert with_root.status_code == 200
    assert with_root.json() == {"status": "alive"}
    assert direct.status_code == 200
    assert direct.json() == {"status": "alive"}
    assert main.app.root_path == "/demo"
