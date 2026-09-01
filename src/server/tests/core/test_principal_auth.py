"""Contract tests for the shared principal authentication ASGI boundary."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

from server.app.api.deps import require_administrator
from server.app.core.auth import (
    AuthenticationError,
    Principal,
    PrincipalAuthMiddleware,
    _decode_oidc_token,
    _discover_jwks_url,
    authenticated_client,
)
from server.app.core.sessions import OwnedSession

pytestmark = pytest.mark.anyio


async def _principal_echo(scope, receive, send):
    principal = scope["state"]["aio_principal"]
    await JSONResponse({"issuer": principal.issuer, "subject": principal.subject, "roles": sorted(principal.roles)})(
        scope, receive, send
    )


async def test_api_key_is_accepted_when_no_principal_adapter_is_configured():
    app = PrincipalAuthMiddleware(_principal_echo)
    with patch("server.app.core.auth.settings") as mock_settings:
        mock_settings.auth_mode = None
        mock_settings.api_key = "api-key"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/settings", headers={"X-API-Key": "api-key"})

    assert response.status_code == 200
    assert response.json()["issuer"] == "api-key"


def test_oidc_jwks_url_is_read_from_issuer_discovery_document():
    response = MagicMock()
    response.read.return_value = b'{"jwks_uri": "https://identity.example.test/keys"}'
    opener = MagicMock()
    opener.__enter__.return_value = response

    with patch("server.app.core.auth.urlopen", return_value=opener) as urlopen:
        jwks_url = _discover_jwks_url("https://identity.example.test/tenant/")

    assert jwks_url == "https://identity.example.test/keys"
    assert urlopen.call_args.args[0] == "https://identity.example.test/tenant/.well-known/openid-configuration"


def test_oidc_resource_server_rejects_id_tokens_before_key_lookup():
    with (
        patch("server.app.core.auth.settings") as mock_settings,
        patch("server.app.core.auth.PyJWKClient") as jwk_client,
        pytest.raises(AuthenticationError, match="ID tokens"),
    ):
        mock_settings.auth_mode = "dev"
        mock_settings.auth_dev_issuer = "http://127.0.0.1:8765"
        _decode_oidc_token("eyJ0eXAiOiJKV1QifQ.eyJzdWIiOiJhbGljZSJ9.c2lnbmF0dXJl")

    jwk_client.assert_not_called()


def test_external_oidc_rejects_a_jwt_that_is_not_marked_as_an_access_token():
    signing_key = MagicMock()
    signing_key.key = "public-key"
    with (
        patch("server.app.core.auth.settings") as mock_settings,
        patch("server.app.core.auth._discover_jwks_url", return_value="https://idp.example.test/jwks"),
        patch("server.app.core.auth.PyJWKClient") as jwk_client,
        patch("server.app.core.auth.jwt.get_unverified_header", return_value={"typ": "JWT"}),
        patch(
            "server.app.core.auth.jwt.decode",
            return_value={"sub": "alice", "scope": "openid profile aio.api"},
        ),
    ):
        mock_settings.auth_mode = "oidc"
        mock_settings.auth_oidc_issuer = "https://idp.example.test"
        mock_settings.auth_oidc_audience = "aio-api"
        mock_settings.auth_oidc_roles_claim = "roles"
        mock_settings.auth_oidc_required_scopes = ["aio.api"]
        jwk_client.return_value.get_signing_key_from_jwt.return_value = signing_key

        with pytest.raises(AuthenticationError, match="ID tokens"):
            _decode_oidc_token("external-id-token")


async def test_proxy_principal_requires_a_trusted_peer_and_configured_headers():
    app = PrincipalAuthMiddleware(_principal_echo)
    with patch("server.app.core.auth.settings") as mock_settings:
        mock_settings.auth_mode = "proxy"
        mock_settings.auth_proxy_trusted_cidrs = ["127.0.0.0/8"]
        mock_settings.auth_proxy_subject_header = "X-Authenticated-Subject"
        mock_settings.auth_proxy_roles_header = "X-Authenticated-Roles"
        mock_settings.auth_proxy_issuer = "test-proxy"
        mock_settings.auth_admin_claim_values = ["optimizer-admin"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/settings",
                headers={
                    "X-Authenticated-Subject": "alice",
                    "X-Authenticated-Roles": "optimizer-admin, analyst",
                },
            )

    assert response.status_code == 200
    assert response.json() == {
        "issuer": "test-proxy",
        "subject": "alice",
        "roles": ["analyst", "optimizer-admin"],
    }


@pytest.mark.parametrize("mode", ["dev", "oidc", "proxy"])
async def test_principal_authentication_never_accepts_the_api_key(mode: str):
    app = PrincipalAuthMiddleware(_principal_echo)
    with patch("server.app.core.auth.settings") as mock_settings:
        mock_settings.auth_mode = mode
        mock_settings.api_key = "api-key"
        mock_settings.auth_proxy_trusted_cidrs = ["127.0.0.0/8"]
        mock_settings.auth_proxy_subject_header = "X-Authenticated-Subject"
        mock_settings.auth_proxy_roles_header = "X-Authenticated-Roles"
        mock_settings.auth_proxy_issuer = "test-proxy"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/settings", headers={"X-API-Key": "api-key"})

    assert response.status_code == 401


async def test_owned_session_cannot_be_reused_by_a_different_principal():
    app = PrincipalAuthMiddleware(_principal_echo)
    with patch("server.app.core.auth.settings") as mock_settings:
        mock_settings.auth_mode = "proxy"
        mock_settings.auth_proxy_trusted_cidrs = ["127.0.0.0/8"]
        mock_settings.auth_proxy_subject_header = "X-Authenticated-Subject"
        mock_settings.auth_proxy_roles_header = "X-Authenticated-Roles"
        mock_settings.auth_proxy_issuer = "test-proxy"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.get(
                "/v1/settings",
                headers={"X-Authenticated-Subject": "alice", "X-AIO-Session": "owned-test-session"},
            )
            second = await client.get(
                "/v1/settings",
                headers={"X-Authenticated-Subject": "bob", "X-AIO-Session": "owned-test-session"},
            )

    assert first.status_code == 200
    assert second.status_code == 403


async def test_authenticated_request_cannot_override_the_owned_mcp_client_with_thread_id():
    """The MCP client accessor uses the ASGI-owned session, not a tool thread ID."""

    async def client_echo(scope, receive, send):
        await JSONResponse({"client": authenticated_client("CONFIGURED")})(scope, receive, send)

    app = PrincipalAuthMiddleware(client_echo)
    with patch("server.app.core.auth.settings") as mock_settings:
        mock_settings.auth_mode = "proxy"
        mock_settings.auth_proxy_trusted_cidrs = ["127.0.0.0/8"]
        mock_settings.auth_proxy_subject_header = "X-Authenticated-Subject"
        mock_settings.auth_proxy_roles_header = "X-Authenticated-Roles"
        mock_settings.auth_proxy_issuer = "test-proxy"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/mcp/", headers={"X-Authenticated-Subject": "alice"})

    assert response.status_code == 200
    assert response.json()["client"] != "CONFIGURED"


def test_owned_session_client_key_fits_the_client_identifier_limit():
    principal = Principal("https://issuer.example.test", "alice", frozenset(), "oidc")

    client_key = OwnedSession(principal, "x" * 255).client_key

    assert len(client_key) <= 255


async def test_administrator_guard_rejects_authenticated_non_administrator():
    principal = Principal("issuer", "alice", frozenset({"analyst"}), "proxy")
    with pytest.raises(HTTPException) as exc_info:
        await require_administrator(principal)
    assert exc_info.value.status_code == 403
