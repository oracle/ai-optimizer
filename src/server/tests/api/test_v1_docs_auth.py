"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the /v1/docs Swagger UI gate page and the authenticated
/v1/openapi.json endpoint. Also verifies the default unauthenticated doc
surfaces (/redoc, /docs/oauth2-redirect) are no longer exposed.
"""
# spell-checker: disable

import pytest
from httpx import ASGITransport, AsyncClient

from server.app.core.settings import settings
from server.app.main import app


@pytest.mark.unit
@pytest.mark.anyio
async def test_openapi_json_requires_auth(app_client):
    """GET /v1/openapi.json without X-API-Key is rejected."""
    resp = await app_client.get("/v1/openapi.json")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_openapi_json_with_valid_key(app_client, auth_headers):
    """GET /v1/openapi.json with a valid key returns the OpenAPI schema."""
    resp = await app_client.get("/v1/openapi.json", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "openapi" in body
    assert "paths" in body
    assert "/v1/liveness" in body["paths"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_openapi_json_wrong_key(app_client):
    """GET /v1/openapi.json with a wrong key is rejected."""
    resp = await app_client.get("/v1/openapi.json", headers={"X-API-Key": "not-the-key"})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_openapi_json_injects_root_path_servers():
    """Under a non-empty root_path, the schema's servers include that prefix.

    Matches FastAPI's built-in /openapi.json behavior so Swagger UI and
    generated clients target the prefixed deployment correctly.
    """
    assert settings.api_key is not None
    async with AsyncClient(
        transport=ASGITransport(app=app, root_path="/api"),
        base_url="http://test",
    ) as client:
        resp = await client.get("/v1/openapi.json", headers={"X-API-Key": settings.api_key})
    assert resp.status_code == 200
    servers = resp.json().get("servers", [])
    assert {"url": "/api"} in servers


@pytest.mark.unit
@pytest.mark.anyio
async def test_openapi_json_no_root_path_no_server_injection(app_client, auth_headers):
    """With no root_path, we do not spuriously add a servers entry."""
    resp = await app_client.get("/v1/openapi.json", headers=auth_headers)
    assert resp.status_code == 200
    servers = resp.json().get("servers", [])
    assert not any(s.get("url", "") == "" for s in servers)


@pytest.mark.unit
@pytest.mark.anyio
async def test_swagger_docs_shell_is_public(app_client):
    """GET /v1/docs is a public gate page: 200 without auth, with a key input."""
    resp = await app_client.get("/v1/docs")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    # Page includes the Swagger UI bundle and a key input form.
    assert "SwaggerUIBundle" in body
    assert "swagger-ui" in body
    assert 'id="api-key"' in body
    # Gate page fetches the spec relative to the doc URL so prefixed deployments
    # resolve correctly without server-side templating.
    assert "./openapi.json" in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_swagger_docs_shell_does_not_leak_spec(app_client):
    """The shell must not inline the OpenAPI spec — it is fetched post-auth."""
    resp = await app_client.get("/v1/docs")
    assert resp.status_code == 200
    body = resp.text
    # No schema keys or endpoint paths baked into the unauthenticated HTML.
    assert '"openapi":' not in body
    assert '"paths":' not in body
    assert "/v1/liveness" not in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_default_redoc_disabled(app_client):
    """FastAPI's default /redoc route must not be exposed."""
    resp = await app_client.get("/redoc")
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_oauth2_redirect_disabled(app_client):
    """FastAPI's default /docs/oauth2-redirect route must not be exposed."""
    resp = await app_client.get("/docs/oauth2-redirect")
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_liveness_still_unauth(app_client):
    """Regression: liveness probe remains unauthenticated."""
    resp = await app_client.get("/v1/liveness")
    assert resp.status_code == 200


@pytest.mark.unit
@pytest.mark.anyio
async def test_readiness_still_unauth(app_client):
    """Regression: readiness probe remains unauthenticated."""
    resp = await app_client.get("/v1/readiness")
    assert resp.status_code == 200


@pytest.mark.unit
@pytest.mark.anyio
async def test_healthz_still_unauth(app_client):
    """Regression: healthz probe remains unauthenticated."""
    resp = await app_client.get("/v1/healthz")
    assert resp.status_code == 200
