"""Focused tests for durable-principal gateway behavior."""

from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient

from server.app.auth.gateway import create_application
from server.app.auth.models import InMemoryAuthStore
from server.app.auth.service import WEB_CLIENT_ID, GatewayConfig, GatewayService
from server.app.auth.tokens import pkce_challenge

pytestmark = pytest.mark.anyio


def _service() -> GatewayService:
    return GatewayService(
        GatewayConfig(
            issuer="http://127.0.0.1:8765",
            mode="local",
            web_client_secret="web-secret",
            web_redirect_uri="http://localhost:8501/oauth2callback",
            local_admin_username="admin@example.test",
            local_admin_password="admin-password",
        ),
        InMemoryAuthStore(),
    )


async def test_local_account_issues_opaque_access_token_for_durable_principal():
    service = _service()
    await service.initialize()
    principal = await service.authenticate_local("admin@example.test", "admin-password")
    assert principal is not None
    assert principal.principal_id
    assert principal.roles == frozenset({"aio.user", "aio.admin"})

    verifier = "v" * 64
    code = await service.create_authorization_code(
        principal=principal,
        client_id=WEB_CLIENT_ID,
        redirect_uri="http://localhost:8501/oauth2callback",
        scope="openid profile email",
        nonce="nonce",
        code_challenge=pkce_challenge(verifier),
    )
    tokens = await service.exchange_code(
        client_id=WEB_CLIENT_ID,
        client_secret="web-secret",
        code=code,
        redirect_uri="http://localhost:8501/oauth2callback",
        code_verifier=verifier,
    )

    access_token = tokens["access_token"]
    assert isinstance(access_token, str)
    assert access_token.count(".") == 0
    resolved = await service.principal_for_access_token(access_token)
    assert resolved is not None
    assert resolved.principal_id == principal.principal_id


async def test_disabling_a_principal_revokes_current_gateway_access():
    service = _service()
    await service.initialize()
    principal = await service.authenticate_local("admin@example.test", "admin-password")
    assert principal is not None
    verifier = "v" * 64
    code = await service.create_authorization_code(
        principal=principal,
        client_id=WEB_CLIENT_ID,
        redirect_uri="http://localhost:8501/oauth2callback",
        scope="openid profile email",
        nonce="nonce",
        code_challenge=pkce_challenge(verifier),
    )
    tokens = await service.exchange_code(
        client_id=WEB_CLIENT_ID,
        client_secret="web-secret",
        code=code,
        redirect_uri="http://localhost:8501/oauth2callback",
        code_verifier=verifier,
    )
    access_token = tokens["access_token"]
    assert isinstance(access_token, str)

    await service.store.set_principal_active(principal.principal_id, False)
    assert await service.principal_for_access_token(access_token) is None


async def test_upstream_transaction_preserves_downstream_state():
    service = _service()
    await service.initialize()
    transaction = await service.create_login_transaction(
        client_id=WEB_CLIENT_ID,
        redirect_uri="http://localhost:8501/oauth2callback",
        scope="openid profile email",
        nonce="downstream-nonce",
        code_challenge=pkce_challenge("v" * 64),
        downstream_state="streamlit-state",
    )

    consumed = await service.consume_login_transaction(transaction.state)
    assert consumed is not None
    assert consumed.downstream_state == "streamlit-state"
    assert await service.consume_login_transaction(transaction.state) is None


async def test_local_gateway_completes_authorization_code_login():
    service = _service()
    app = await create_application(service)
    verifier = "v" * 64
    params = {
        "response_type": "code",
        "client_id": WEB_CLIENT_ID,
        "redirect_uri": "http://localhost:8501/oauth2callback",
        "scope": "openid profile email",
        "state": "client-state",
        "nonce": "client-nonce",
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8765") as client:
        authorize = await client.get("/authorize", params=params, follow_redirects=False)
        assert authorize.status_code == 303
        continue_to = parse_qs(urlparse(authorize.headers["location"]).query)["continue_to"][0]
        login = await client.post(
            authorize.headers["location"],
            data={
                "username": "admin@example.test",
                "password": "admin-password",
                "continue_to": continue_to,
            },
            follow_redirects=False,
        )
        assert login.status_code == 303
        authorized = await client.get(login.headers["location"], follow_redirects=False)
        assert authorized.status_code == 302
        code = authorized.headers["location"].split("code=", 1)[1].split("&", 1)[0]
        token = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": WEB_CLIENT_ID,
                "client_secret": "web-secret",
                "code": code,
                "redirect_uri": "http://localhost:8501/oauth2callback",
                "code_verifier": verifier,
            },
        )

    assert token.status_code == 200
    assert token.json()["access_token"].count(".") == 0
