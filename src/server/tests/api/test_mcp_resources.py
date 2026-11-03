"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for MCP resources endpoint.
"""
# spell-checker: disable

from unittest.mock import patch

import pytest
from mcp.types import Resource

pytestmark = pytest.mark.anyio


@pytest.mark.unit
async def test_list_resources_no_auth(app_client):
    """GET /mcp/resources without auth returns 403."""
    resp = await app_client.get("/mcp/resources")
    assert resp.status_code == 403


@pytest.mark.unit
async def test_list_resources_returns_registered_resource_payload(app_client, auth_headers):
    """GET /mcp/resources returns serialized registered resource metadata."""

    class FakeClient:
        def __init__(self, mcp):
            self.mcp = mcp

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def list_resources(self):
            return [
                Resource(
                    uri="optimizer://settings",
                    name="settings",
                    mime_type="application/json",
                    _meta={"owner": "optimizer"},
                )
            ]

    with patch("server.app.api.mcp.endpoints.resources.Client", FakeClient):
        resp = await app_client.get("/mcp/resources", headers=auth_headers)

    assert resp.status_code == 200
    resource = resp.json()[0]
    assert resource["uri"] == "optimizer://settings"
    assert resource["name"] == "settings"
    assert resource["mimeType"] == "application/json"
    assert resource["_meta"] == {"owner": "optimizer"}
    assert "mime_type" not in resource
    assert "meta" not in resource
