"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared fixtures for client.app.core tests.
"""
# spell-checker: disable

import json
from unittest.mock import MagicMock

import httpx
import pytest


@pytest.fixture
def mock_settings():
    """MagicMock with default ClientSettings attributes."""
    m = MagicMock()
    m.api_key = "test-key"
    m.server_url = "http://localhost"
    m.server_port = 8000
    m.server_url_prefix = ""
    m.client_address = "localhost"
    m.client_port = 8501
    m.client_url_prefix = ""
    return m


def _build_httpx_response(
    status_code: int = 200,
    json_data=None,
    content: bytes | None = None,
    _text: str = "",
):
    """Build a real ``httpx.Response`` suitable for tests."""
    headers = {}
    if json_data is not None:
        content = json.dumps(json_data).encode()
        headers["content-type"] = "application/json"
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("GET", "http://test"),
        content=content or b"",
        headers=headers,
    )


@pytest.fixture
def make_httpx_response():
    """Factory fixture to build httpx.Response objects."""
    return _build_httpx_response


@pytest.fixture
def make_httpx_client():
    """Factory fixture returning a MagicMock that mimics ``httpx.Client`` as a context manager."""

    def _make(response=None, side_effect=None):
        client_instance = MagicMock()
        if side_effect:
            for method in ("get", "post", "put", "patch", "delete"):
                getattr(client_instance, method).side_effect = side_effect
        elif response is not None:
            for method in ("get", "post", "put", "patch", "delete"):
                getattr(client_instance, method).return_value = response
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=client_instance)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx, client_instance

    return _make
