"""OIDC access-token validation and principal provisioning."""

import asyncio

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientConnectionError, PyJWKClientError

from server.app.auth import repository
from server.app.auth.models import Principal, RequestCredential
from server.app.auth.service import AuthAuthorityUnavailable, AuthenticationError, register_authenticator
from server.app.core.settings import settings

_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA")
_DISCOVERY_TIMEOUT_SECONDS = 10.0
_JWKS_CACHE_SECONDS = 300


def _required_string(claims: dict, name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value:
        raise AuthenticationError("Invalid bearer credential")
    return value


def _optional_string(claims: dict, name: str) -> str | None:
    value = claims.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise AuthenticationError("Invalid bearer credential")
    return value or None


def _claim_scopes(claims: dict) -> frozenset[str]:
    value = claims.get("scope", claims.get("scp", ""))
    if isinstance(value, str):
        return frozenset(value.split())
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    raise AuthenticationError("Invalid bearer credential")


class OIDCAuthenticator:
    """Validate signed access tokens from one configured issuer."""

    def __init__(self, jwks_uri: str) -> None:
        self._jwk_client = PyJWKClient(
            jwks_uri,
            cache_keys=False,
            lifespan=_JWKS_CACHE_SECONDS,
            timeout=_DISCOVERY_TIMEOUT_SECONDS,
        )

    async def authenticate(self, credential: RequestCredential) -> Principal:
        try:
            signing_key = await asyncio.to_thread(self._jwk_client.get_signing_key_from_jwt, credential.value)
            claims = jwt.decode(
                credential.value,
                signing_key.key,
                algorithms=_ALGORITHMS,
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except PyJWKClientConnectionError:
            raise AuthAuthorityUnavailable("OIDC signing-key authority is unavailable") from None
        except (InvalidTokenError, PyJWKClientError, ValueError, TypeError):
            raise AuthenticationError("Invalid bearer credential") from None

        subject = _required_string(claims, "sub")
        scopes = _claim_scopes(claims)
        if not set(settings.oidc_required_scopes).issubset(scopes):
            raise AuthenticationError("Invalid bearer credential")
        email = _optional_string(claims, "email")
        username = _optional_string(claims, "preferred_username") or email or subject

        try:
            user = await repository.resolve_oidc_user(
                issuer=settings.oidc_issuer or "",
                subject=subject,
                username=username,
                display_name=_optional_string(claims, "name"),
                email=email,
            )
        except Exception as exc:
            raise AuthAuthorityUnavailable("OIDC user authority is unavailable") from exc
        if user.status != "active":
            raise AuthenticationError("Invalid bearer credential")
        return Principal(
            user_id=user.user_id,
            subject=subject,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            auth_source="oidc",
            roles=frozenset({user.role}),
            scopes=scopes,
        )


async def discover_oidc_jwks_uri() -> str:
    """Validate provider metadata and return its signing-key endpoint."""
    issuer = settings.oidc_issuer or ""
    discovery_url = settings.effective_oidc_discovery_url
    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT_SECONDS) as client:
            response = await client.get(discovery_url)
            response.raise_for_status()
            metadata = response.json()
    except (httpx.HTTPError, ValueError):
        raise AuthAuthorityUnavailable("OIDC discovery authority is unavailable") from None
    if metadata.get("issuer") != issuer:
        raise AuthAuthorityUnavailable("OIDC discovery issuer does not match configuration")
    jwks_uri = metadata.get("jwks_uri")
    if not isinstance(jwks_uri, str) or not jwks_uri.startswith("https://"):
        if settings.env not in {"dev", "test"} or not isinstance(jwks_uri, str):
            raise AuthAuthorityUnavailable("OIDC discovery metadata has no trusted signing-key endpoint")
    return jwks_uri


async def initialize_oidc_authenticator() -> None:
    """Discover the configured issuer and install its token verifier."""
    jwks_uri = await discover_oidc_jwks_uri()
    register_authenticator("oidc", OIDCAuthenticator(jwks_uri))
