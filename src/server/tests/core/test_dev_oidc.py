"""Contract tests for the built-in development OIDC provider."""

import base64
import hashlib
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import jwt
import oracledb
import pytest
from httpx import ASGITransport, AsyncClient

from server.app.api.dev_oidc import create_application
from server.app.core.dev_oidc import (
    AuthorizationCode,
    DevelopmentOidcService,
    InMemoryDevelopmentOidcStore,
    LoginSession,
    OracleDevelopmentOidcStore,
    _decode_json_array,
)
from server.app.core.settings import _validate_issuer_url

pytestmark = pytest.mark.anyio

ADMIN_USERNAME = "admin@example.test"
SEED_PASSWORDS = {ADMIN_USERNAME: "admin-password"}
WEB_CLIENT_SECRET = "web-client-secret"


def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def test_issuer_configuration_only_allows_plain_http_on_loopback():
    _validate_issuer_url("http://127.0.0.1:8765")
    _validate_issuer_url("https://auth.example.test")

    with pytest.raises(ValueError, match="loopback"):
        _validate_issuer_url("http://auth.example.test")
    with pytest.raises(ValueError, match="root path"):
        _validate_issuer_url("https://auth.example.test/oidc")

    _validate_issuer_url("https://idp.example.test/realms/team", require_root_path=False)


def test_oracle_json_arrays_can_be_text_or_native_values():
    assert _decode_json_array('["openid", "aio.api"]') == ["openid", "aio.api"]
    assert _decode_json_array(["openid", "aio.api"]) == ["openid", "aio.api"]


async def test_oracle_store_filters_expired_login_sessions_in_the_database():
    """Oracle, rather than Python, determines whether durable sessions are expired."""
    expiry = datetime(2026, 8, 28, 12, 0)
    store = OracleDevelopmentOidcStore()
    store._query = AsyncMock(
        side_effect=[
            [
                (
                    "code",
                    "client",
                    "user",
                    "https://example.test/callback",
                    "openid",
                    "nonce",
                    "challenge",
                    expiry,
                    False,
                )
            ],
            [("session", "user", expiry, False)],
        ]
    )

    code = await store.get_code("code")
    session = await store.get_login_session("session")

    assert code is not None
    assert session is not None
    assert code.expires_at is expiry
    assert session.expires_at is expiry
    assert "expires_at > SYSTIMESTAMP" in store._query.await_args_list[1].args[0]


async def test_oracle_store_generates_durable_expiry_timestamps_from_its_own_clock():
    """Oracle must not receive host-clock timestamps for durable OIDC expiry."""
    store = OracleDevelopmentOidcStore()
    store._execute = AsyncMock()
    host_expiry = datetime(2026, 8, 28, 15, 0)

    await store.save_code(
        AuthorizationCode(
            "code",
            "client",
            "user",
            "https://example.test/callback",
            "openid",
            "nonce",
            "challenge",
            host_expiry,
        )
    )
    await store.save_login_session(LoginSession("session", "user", host_expiry))

    code_sql, code_binds = store._execute.await_args_list[0].args
    session_sql, session_binds = store._execute.await_args_list[1].args
    assert "SYSTIMESTAMP + NUMTODSINTERVAL(:expires_in_seconds, 'SECOND')" in code_sql
    assert code_binds["expires_in_seconds"] == 300
    assert "expires_at" not in code_binds
    assert "SYSTIMESTAMP + NUMTODSINTERVAL(:expires_in_seconds, 'SECOND')" in session_sql
    assert session_binds["expires_in_seconds"] == 28_800
    assert "expires_at" not in session_binds


async def test_development_provider_issues_distinct_id_and_api_access_tokens():
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
        web_client_secret=WEB_CLIENT_SECRET,
    )
    await service.initialize()
    verifier = "A" * 64
    code = await service.create_authorization_code(
        username=ADMIN_USERNAME,
        client_id="platform-web-client",
        redirect_uri="http://localhost:8501/oauth2callback",
        scope="openid profile email aio.api aio.admin",
        nonce="nonce-value",
        code_challenge=_pkce_challenge(verifier),
    )

    tokens = await service.exchange_code(
        client_id="platform-web-client",
        client_secret=WEB_CLIENT_SECRET,
        code=code,
        redirect_uri="http://localhost:8501/oauth2callback",
        code_verifier=verifier,
    )

    access_token = tokens["access_token"]
    id_token = tokens["id_token"]
    assert isinstance(access_token, str)
    assert isinstance(id_token, str)
    access_header = jwt.get_unverified_header(access_token)
    access_claims = jwt.decode(access_token, options={"verify_signature": False})
    id_claims = jwt.decode(id_token, options={"verify_signature": False})
    assert access_header["typ"] == "at+jwt"
    assert access_claims["aud"] == "aio-api"
    assert set(access_claims["scope"].split()) == {"openid", "profile", "email", "aio.api", "aio.admin"}
    assert access_claims["roles"] == ["aio.admin"]
    assert id_claims["aud"] == "platform-web-client"
    assert id_claims["nonce"] == "nonce-value"
    assert access_claims["sub"] == id_claims["sub"]


async def test_development_provider_rejects_an_invalid_web_client_secret():
    """The Streamlit client secret is checked before consuming the code."""
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
        web_client_secret=WEB_CLIENT_SECRET,
    )
    await service.initialize()
    verifier = "C" * 64
    code = await service.create_authorization_code(
        username=ADMIN_USERNAME,
        client_id="platform-web-client",
        redirect_uri="http://localhost:8501/oauth2callback",
        scope="openid profile email aio.api",
        nonce="nonce-value",
        code_challenge=_pkce_challenge(verifier),
    )

    with pytest.raises(ValueError, match="Invalid client credentials"):
        await service.exchange_code(
            client_id="platform-web-client",
            client_secret="wrong-secret",
            code=code,
            redirect_uri="http://localhost:8501/oauth2callback",
            code_verifier=verifier,
        )


async def test_development_provider_seeds_only_the_administrator():
    store = InMemoryDevelopmentOidcStore()
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=store,
        seed_passwords=SEED_PASSWORDS,
    )

    await service.initialize()

    administrator = await service.authenticate(ADMIN_USERNAME, "admin-password")
    assert administrator is not None
    assert administrator.display_name == "ADMIN"
    assert administrator.scopes == frozenset({"openid", "profile", "email", "aio.api", "aio.admin"})
    assert [user.username for user in store.users.values()] == [ADMIN_USERNAME]


async def test_configured_bootstrap_password_synchronizes_an_existing_administrator():
    """The configured development password remains authoritative for the bootstrap user."""
    store = InMemoryDevelopmentOidcStore()
    old_service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=store,
        seed_passwords={ADMIN_USERNAME: "old-generated-password"},
    )
    await old_service.initialize()

    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=store,
        seed_passwords={ADMIN_USERNAME: "durable-launcher-password"},
    )
    await service.initialize()

    assert await service.authenticate(ADMIN_USERNAME, "old-generated-password") is None
    assert await service.authenticate(ADMIN_USERNAME, "durable-launcher-password") is not None


async def test_seed_user_accepts_the_winner_of_a_concurrent_unique_insert():
    """Replica startup remains idempotent when another replica seeds the user first."""
    existing = MagicMock()
    store = MagicMock()
    store.get_user_by_username = AsyncMock(side_effect=[None, existing])
    store.save_user = AsyncMock(side_effect=oracledb.IntegrityError())
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=store,
        seed_passwords=SEED_PASSWORDS,
    )

    await service._seed_user(ADMIN_USERNAME, "ADMIN", {"aio.admin"})

    store.save_user.assert_awaited_once()


async def test_development_provider_registers_the_configured_streamlit_callback():
    callback = "https://optimizer.example.test/oauth2callback"
    service = DevelopmentOidcService(
        issuer="https://auth.example.test",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
        web_client_redirect_uri=callback,
    )
    await service.initialize()

    code = await service.create_authorization_code(
        username=ADMIN_USERNAME,
        client_id="platform-web-client",
        redirect_uri=callback,
        scope="openid profile email aio.api",
        nonce="nonce-value",
        code_challenge=_pkce_challenge("E" * 64),
    )

    assert code


async def test_authorization_codes_are_single_use_and_bound_to_pkce():
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
    )
    await service.initialize()
    verifier = "B" * 64
    code = await service.create_authorization_code(
        username=ADMIN_USERNAME,
        client_id="platform-web-client",
        redirect_uri="http://localhost:8501/oauth2callback",
        scope="openid profile email aio.api",
        nonce="nonce-value",
        code_challenge=_pkce_challenge(verifier),
    )

    with pytest.raises(ValueError, match="PKCE"):
        await service.exchange_code(
            client_id="platform-web-client",
            code=code,
            redirect_uri="http://localhost:8501/oauth2callback",
            code_verifier="C" * 64,
        )

    await service.exchange_code(
        client_id="platform-web-client",
        code=code,
        redirect_uri="http://localhost:8501/oauth2callback",
        code_verifier=verifier,
    )
    with pytest.raises(ValueError, match="authorization code"):
        await service.exchange_code(
            client_id="platform-web-client",
            code=code,
            redirect_uri="http://localhost:8501/oauth2callback",
            code_verifier=verifier,
        )


async def test_login_sessions_are_durable_and_can_be_revoked():
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
    )
    await service.initialize()
    user = await service.authenticate(ADMIN_USERNAME, "admin-password")
    assert user is not None

    session_id = await service.create_login_session(user)
    session_user = await service.get_login_session_user(session_id)
    assert session_user is not None
    assert session_user.username == ADMIN_USERNAME

    await service.revoke_login_session(session_id)
    assert await service.get_login_session_user(session_id) is None


async def test_administrator_can_provision_an_additional_development_user():
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
    )
    await service.initialize()

    await service.provision_user(
        username="carol@example.test",
        email="carol@example.test",
        display_name="Carol",
        password="carol-password",
    )

    assert await service.authenticate("carol@example.test", "carol-password") is not None


async def test_discovery_advertises_the_default_root_issuer_endpoints():
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
    )
    document = await service.discovery_document()

    assert document["issuer"] == "http://127.0.0.1:8765"
    assert document["jwks_uri"] == "http://127.0.0.1:8765/jwks.json"
    assert document["authorization_endpoint"] == "http://127.0.0.1:8765/authorize"
    assert document["token_endpoint"] == "http://127.0.0.1:8765/token"
    assert document["token_endpoint_auth_methods_supported"] == ["client_secret_basic", "client_secret_post"]
    assert document["scopes_supported"] == ["openid", "profile", "email", "aio.api", "aio.admin"]


async def test_fixed_mcp_client_has_a_client_id_metadata_document():
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
    )
    await service.initialize()

    metadata = await service.mcp_client_metadata_document()

    assert metadata["client_id"] == "http://127.0.0.1:8765/mcp-client-metadata.json"
    assert metadata["token_endpoint_auth_method"] == "none"
    assert metadata["grant_types"] == ["authorization_code"]


async def test_authorization_code_flow_uses_login_and_returns_api_access_token():
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
        web_client_secret=WEB_CLIENT_SECRET,
    )
    app = await create_application(service)
    verifier = "D" * 64
    params = {
        "response_type": "code",
        "client_id": "platform-web-client",
        "redirect_uri": "http://localhost:8501/oauth2callback",
        "scope": "openid profile email aio.api",
        "state": "opaque-state",
        "nonce": "nonce-value",
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login_redirect = await client.get("/authorize", params=params, follow_redirects=False)
        assert login_redirect.status_code == 303
        assert login_redirect.headers["location"].startswith("/login?")
        login = await client.post(
            login_redirect.headers["location"],
            data={
                "username": ADMIN_USERNAME,
                "password": "admin-password",
                "continue_to": parse_qs(urlparse(login_redirect.headers["location"]).query)["continue_to"][0],
            },
            follow_redirects=False,
        )
        assert login.status_code == 303
        authorize = await client.get(login.headers["location"], follow_redirects=False)
        redirect = authorize.headers["location"]
        code = parse_qs(urlparse(redirect).query)["code"][0]
        token = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:8501/oauth2callback",
                "code_verifier": verifier,
            },
            headers={
                "Authorization": "Basic "
                + base64.b64encode(f"platform-web-client:{WEB_CLIENT_SECRET}".encode()).decode()
            },
        )

    assert token.status_code == 200
    access_claims = jwt.decode(token.json()["access_token"], options={"verify_signature": False})
    assert access_claims["aud"] == "aio-api"


async def test_login_form_escapes_its_continuation_value():
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
    )
    app = await create_application(service)
    continuation = '/authorize?state="<script>alert(1)</script>'

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/login", params={"continue_to": continuation})

    assert response.status_code == 200
    assert "&quot;&lt;script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text


async def test_login_form_matches_the_application_branding():
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
    )
    app = await create_application(service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/login", params={"continue_to": "/authorize?state=opaque-state"})

    assert response.status_code == 200
    assert "<title>Oracle AI Optimizer and Toolkit - Sign in</title>" in response.text
    assert '<main class="auth-shell">' in response.text
    assert '<section class="auth-card">' in response.text
    assert 'aria-label="Oracle AI Optimizer and Toolkit"' in response.text
    assert '<img class="brand-logo" src="data:image/png;base64,' in response.text
    assert 'name="username"' in response.text
    assert 'type="password"' in response.text
    assert 'name="continue_to"' in response.text


async def test_failed_login_renders_the_form_with_an_error():
    service = DevelopmentOidcService(
        issuer="http://127.0.0.1:8765",
        store=InMemoryDevelopmentOidcStore(),
        seed_passwords=SEED_PASSWORDS,
    )
    app = await create_application(service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/login",
            data={
                "username": ADMIN_USERNAME,
                "password": "wrong-password",
                "continue_to": "/authorize?state=opaque-state",
            },
        )

    assert response.status_code == 401
    assert '<p class="form-error" role="alert">Invalid username or password</p>' in response.text
    assert '<main class="auth-shell">' in response.text
    assert 'name="continue_to"' in response.text
