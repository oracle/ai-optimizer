"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Smoke tests for authentication applied to protected API routers.
"""
# spell-checker: disable

import pytest

_PROTECTED_ROUTES = [
    ("GET", "/v1/settings"),
    ("GET", "/v1/databases"),
    ("GET", "/v1/models"),
    ("GET", "/v1/oci"),
    ("POST", "/v1/prompts/reset"),
    ("GET", "/v1/agentspec/specs"),
    ("GET", "/v1/help"),
    ("GET", "/v1/chat/history"),
    ("GET", "/v1/testbed/testsets"),
    ("GET", "/v1/embed/jobs"),
    ("GET", "/v1/deepsec/status"),
    ("GET", "/v1/openapi.json"),
    ("GET", "/mcp/prompts"),
    ("GET", "/mcp/tools"),
    ("GET", "/mcp/resources"),
    ("GET", "/mcp/client-config"),
]


@pytest.mark.unit
@pytest.mark.anyio
async def test_protected_router_routes_require_authentication(app_client):
    """Every protected router has a representative route rejecting anonymous requests."""
    for method, path in _PROTECTED_ROUTES:
        response = await app_client.request(method, path)
        assert response.status_code == 401, f"{method} {path} returned {response.status_code}"
