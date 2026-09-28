"""Contract tests for the shared principal authentication ASGI boundary."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

from server.app.api.deps import require_administrator
from server.app.auth.models import AccessToken, PrincipalRecord
from server.app.core.auth import Principal, PrincipalAuthMiddleware, authenticated_client
from server.app.core.sessions import OwnedSession

pytestmark = pytest.mark.anyio


async def _principal_echo(scope, receive, send):
    principal = scope["state"]["aio_principal"]
    await JSONResponse({"principal_id": principal.principal_id, "roles": sorted(principal.roles)})(scope, receive, send)


async def test_api_key_is_accepted_when_no_principal_adapter_is_configured():
    app = PrincipalAuthMiddleware(_principal_echo)
    with patch("server.app.core.auth.settings") as mock_settings:
        mock_settings.auth_mode = None
        mock_settings.api_key = "api-key"
        mock_settings.auth_admin_claim_values = ["aio.admin"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/settings", headers={"X-API-Key": "api-key"})

    assert response.status_code == 200
    assert response.json()["principal_id"] == "api-key:shared"


async def test_gateway_access_token_resolves_current_durable_principal():
    app = PrincipalAuthMiddleware(_principal_echo)
    token = AccessToken(
        digest="unused",
        principal_id="principal-1",
        client_id="client",
        scope="openid",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    principal = PrincipalRecord("principal-1", "Alice", "alice@example.test", True, frozenset({"aio.user"}))
    with (
        patch("server.app.core.auth.settings") as mock_settings,
        patch("server.app.core.auth.OracleAuthStore.get_access_token", new=AsyncMock(return_value=token)),
        patch("server.app.core.auth.OracleAuthStore.get_principal", new=AsyncMock(return_value=principal)),
    ):
        mock_settings.auth_mode = "local"
        mock_settings.auth_admin_claim_values = ["aio.admin"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/settings", headers={"Authorization": "Bearer opaque-token"})

    assert response.status_code == 200
    assert response.json() == {"principal_id": "principal-1", "roles": ["aio.user"]}


@pytest.mark.parametrize("mode", ["local", "github", "oidc", "proxy"])
async def test_principal_authentication_never_accepts_the_api_key(mode: str):
    app = PrincipalAuthMiddleware(_principal_echo)
    with patch("server.app.core.auth.settings") as mock_settings:
        mock_settings.auth_mode = mode
        mock_settings.api_key = "api-key"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/settings", headers={"X-API-Key": "api-key"})

    assert response.status_code == 401


async def test_authenticated_request_uses_the_owned_mcp_client():
    """The MCP client accessor uses the ASGI-owned session, not a tool thread ID."""

    async def client_echo(scope, receive, send):
        await JSONResponse({"client": authenticated_client("CONFIGURED")})(scope, receive, send)

    session = OwnedSession(Principal("principal-1", frozenset(), "gateway"), "session-1")
    with patch("server.app.core.auth.select_owned_session", new=AsyncMock(return_value=session)):
        app = PrincipalAuthMiddleware(client_echo)
        token = AccessToken(
            digest="unused",
            principal_id="principal-1",
            client_id="client",
            scope="openid",
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        record = PrincipalRecord("principal-1", "Alice", None, True)
        with (
            patch("server.app.core.auth.settings") as mock_settings,
            patch("server.app.core.auth.OracleAuthStore.get_access_token", new=AsyncMock(return_value=token)),
            patch("server.app.core.auth.OracleAuthStore.get_principal", new=AsyncMock(return_value=record)),
        ):
            mock_settings.auth_mode = "local"
            mock_settings.auth_admin_claim_values = ["aio.admin"]
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/mcp/", headers={"Authorization": "Bearer opaque-token"})

    assert response.status_code == 200
    assert response.json()["client"] != "CONFIGURED"


def test_owned_session_client_key_fits_the_client_identifier_limit():
    principal = Principal("a" * 36, frozenset(), "gateway")
    assert len(OwnedSession(principal, "x" * 255).client_key) <= 255


async def test_administrator_guard_rejects_authenticated_non_administrator():
    principal = Principal("principal-1", frozenset({"analyst"}), "gateway")
    with pytest.raises(HTTPException) as exc_info:
        await require_administrator(principal)
    assert exc_info.value.status_code == 403
