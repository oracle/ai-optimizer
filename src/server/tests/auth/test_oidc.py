"""OIDC access-token authentication tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from server.app.auth import oidc, repository
from server.app.auth.models import AuthUser, RequestCredential
from server.app.auth.service import AuthenticationError

pytestmark = pytest.mark.unit


def _user() -> AuthUser:
    now = datetime.now(UTC)
    return AuthUser(
        user_id=repository.ADMIN_USER_ID,
        username="Admin",
        auth_source="oidc",
        issuer="https://issuer.example.test",
        subject="admin-subject",
        role="admin",
        status="active",
        created=now,
        updated=now,
    )


async def test_oidc_discovery_url_is_independent_from_token_issuer(monkeypatch):
    response = Mock()
    response.json.return_value = {
        "issuer": "https://identity.oraclecloud.com/",
        "jwks_uri": "https://idcs-example.identity.oraclecloud.com/admin/v1/SigningCert/jwk",
    }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url):
            assert url == ("https://idcs-example.identity.oraclecloud.com/.well-known/openid-configuration")
            return response

    register = Mock()
    monkeypatch.setattr(oidc.settings, "oidc_issuer", "https://identity.oraclecloud.com/")
    monkeypatch.setattr(
        oidc.settings,
        "oidc_discovery_url",
        "https://idcs-example.identity.oraclecloud.com/.well-known/openid-configuration",
    )
    monkeypatch.setattr(oidc.httpx, "AsyncClient", lambda **_kwargs: Client())
    monkeypatch.setattr(oidc, "register_authenticator", register)

    await oidc.initialize_oidc_authenticator()

    response.raise_for_status.assert_called_once_with()
    register.assert_called_once()


async def test_oidc_discovery_url_defaults_to_token_issuer(monkeypatch):
    response = Mock()
    response.json.return_value = {
        "issuer": "https://issuer.example.test",
        "jwks_uri": "https://issuer.example.test/jwks",
    }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url):
            assert url == "https://issuer.example.test/.well-known/openid-configuration"
            return response

    monkeypatch.setattr(oidc.settings, "oidc_issuer", "https://issuer.example.test")
    monkeypatch.setattr(oidc.settings, "oidc_discovery_url", None)
    monkeypatch.setattr(oidc.httpx, "AsyncClient", lambda **_kwargs: Client())

    assert await oidc.discover_oidc_jwks_uri() == "https://issuer.example.test/jwks"


async def test_oidc_authenticator_validates_scopes_and_resolves_principal(monkeypatch):
    authenticator = oidc.OIDCAuthenticator("https://issuer.example.test/jwks")
    monkeypatch.setattr(
        authenticator._jwk_client,
        "get_signing_key_from_jwt",
        lambda _token: SimpleNamespace(key="public-key"),
    )
    monkeypatch.setattr(
        oidc.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "iss": "https://issuer.example.test",
            "sub": "admin-subject",
            "scope": "openid profile",
            "preferred_username": "admin@example.test",
        },
    )
    monkeypatch.setattr(oidc.settings, "oidc_required_scopes", ["openid"])
    monkeypatch.setattr(oidc.repository, "resolve_oidc_user", AsyncMock(return_value=_user()))

    principal = await authenticator.authenticate(RequestCredential(kind="bearer", value="signed.jwt.token"))

    assert principal.user_id == repository.ADMIN_USER_ID
    assert principal.roles == frozenset({"admin"})
    assert principal.scopes == frozenset({"openid", "profile"})


async def test_oidc_authenticator_rejects_missing_scope(monkeypatch):
    authenticator = oidc.OIDCAuthenticator("https://issuer.example.test/jwks")
    monkeypatch.setattr(
        authenticator._jwk_client,
        "get_signing_key_from_jwt",
        lambda _token: SimpleNamespace(key="public-key"),
    )
    monkeypatch.setattr(
        oidc.jwt,
        "decode",
        lambda *_args, **_kwargs: {"iss": "https://issuer.example.test", "sub": "member", "scope": "openid"},
    )
    monkeypatch.setattr(oidc.settings, "oidc_required_scopes", ["openid", "profile"])

    with pytest.raises(AuthenticationError):
        await authenticator.authenticate(RequestCredential(kind="bearer", value="signed.jwt.token"))


async def test_oidc_authenticator_rejects_wrong_profile_claim_type(monkeypatch):
    authenticator = oidc.OIDCAuthenticator("https://issuer.example.test/jwks")
    monkeypatch.setattr(
        authenticator._jwk_client,
        "get_signing_key_from_jwt",
        lambda _token: SimpleNamespace(key="public-key"),
    )
    monkeypatch.setattr(
        oidc.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "iss": "https://issuer.example.test",
            "sub": "member",
            "scope": "openid",
            "email": ["not", "a", "string"],
        },
    )
    monkeypatch.setattr(oidc.settings, "oidc_required_scopes", ["openid"])

    with pytest.raises(AuthenticationError):
        await authenticator.authenticate(RequestCredential(kind="bearer", value="signed.jwt.token"))
