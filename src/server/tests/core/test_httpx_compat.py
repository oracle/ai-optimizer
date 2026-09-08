"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for HTTPX compatibility helpers.
"""

import httpx
from httpx import _client

from server.app.core.httpx_compat import disable_zstd_response_compression


def test_disable_zstd_response_compression_removes_zstd(monkeypatch):
    monkeypatch.setattr(httpx, "__version__", "0.28.1")
    monkeypatch.setattr(_client, "ACCEPT_ENCODING", "gzip, deflate, zstd")

    assert disable_zstd_response_compression() is True
    assert _client.ACCEPT_ENCODING == "gzip, deflate"

    with httpx.Client() as client:
        assert client.headers["accept-encoding"] == "gzip, deflate"


def test_disable_zstd_response_compression_is_noop_for_other_httpx_versions(monkeypatch):
    monkeypatch.setattr(httpx, "__version__", "0.29.0")
    monkeypatch.setattr(_client, "ACCEPT_ENCODING", "gzip, deflate, zstd")

    assert disable_zstd_response_compression() is False
    assert _client.ACCEPT_ENCODING == "gzip, deflate, zstd"
