"""Canonical-principal authentication shared by REST and MCP transports."""

import asyncio
import hmac
import ipaddress
import json
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode
from urllib.request import urlopen

import jwt
from fastapi import HTTPException
from jwt import PyJWKClient
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from server.app.core.dev_oidc import API_AUDIENCE
from server.app.core.secrets import reveal
from server.app.core.sessions import OwnedSession, select_owned_session
from server.app.core.settings import settings

PRINCIPAL_SCOPE_KEY = "aio_principal"
INTERNAL_PROXY_TOKEN = secrets.token_urlsafe(32)
_owned_session_context: ContextVar[OwnedSession | None] = ContextVar("aio_owned_session", default=None)


def authenticated_client(thread_id: str) -> str:
    """Return the principal-owned client for MCP work, when one is active."""
    owned_session = _owned_session_context.get()
    return owned_session.client_key if owned_session is not None else thread_id


_NO_AUTH_PATHS = frozenset({"/v1/liveness", "/v1/readiness", "/v1/healthz", "/mcp/healthz", "/v1/docs"})


@dataclass(frozen=True, slots=True)
class Principal:
    """Validated authenticated identity; the only authority for ownership checks."""

    issuer: str
    subject: str
    roles: frozenset[str]
    authentication_method: Literal["oidc", "proxy", "api_key"]

    @property
    def ownership_key(self) -> tuple[str, str]:
        """Stable persisted owner key, independent of transport-local state."""
        return (self.issuer, self.subject)

    @property
    def is_administrator(self) -> bool:
        return bool(self.roles.intersection(settings.auth_admin_claim_values))


class AuthenticationError(Exception):
    """Raised when a request cannot produce a valid principal."""


def _header(scope: Scope, name: str) -> str | None:
    wanted = name.lower().encode("ascii")
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return value.decode("utf-8", errors="strict").strip()
    return None


def _is_trusted_proxy(scope: Scope) -> bool:
    client = scope.get("client")
    if not client:
        return False
    try:
        peer = ipaddress.ip_address(client[0])
        return any(peer in ipaddress.ip_network(cidr, strict=False) for cidr in settings.auth_proxy_trusted_cidrs)
    except ValueError:
        return False


def _proxy_principal(scope: Scope) -> Principal:
    if not _is_trusted_proxy(scope):
        raise AuthenticationError("Request did not arrive from a trusted identity proxy")
    subject = _header(scope, settings.auth_proxy_subject_header)
    if not subject:
        raise AuthenticationError("Trusted proxy did not provide an authenticated subject")
    raw_roles = _header(scope, settings.auth_proxy_roles_header) or ""
    roles = frozenset(role.strip() for role in raw_roles.split(",") if role.strip())
    return Principal(
        issuer=settings.auth_proxy_issuer,
        subject=subject,
        roles=roles,
        authentication_method="proxy",
    )


def _internal_proxy_principal(scope: Scope) -> Principal | None:
    """Accept a proxy identity forwarded only by this process over loopback."""
    client = scope.get("client")
    subject = _header(scope, "x-aio-internal-subject")
    token = _header(scope, "x-aio-internal-token")
    if (
        not subject
        or not client
        or client[0] not in {"127.0.0.1", "::1"}
        or not token
        or not hmac.compare_digest(token, INTERNAL_PROXY_TOKEN)
    ):
        return None
    roles = frozenset((_header(scope, "x-aio-internal-roles") or "").split())
    return Principal(settings.auth_proxy_issuer, subject, roles, "proxy")


@lru_cache(maxsize=16)
def _discover_jwks_url(issuer: str) -> str:
    """Return the JWKS endpoint published by an OpenID Connect issuer."""
    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        with urlopen(discovery_url, timeout=5) as response:
            document = json.loads(response.read())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthenticationError("OIDC discovery document could not be retrieved") from exc
    jwks_url = document.get("jwks_uri") if isinstance(document, dict) else None
    if not isinstance(jwks_url, str) or not jwks_url:
        raise AuthenticationError("OIDC discovery document has no JWKS URI")
    return jwks_url


@lru_cache(maxsize=16)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    """Cache the JWKS client as well as the discovered endpoint URL."""
    return PyJWKClient(jwks_url)


def _decode_oidc_token(token: str) -> Principal:
    """Verify a bearer JWT with the configured issuer's published signing keys."""
    issuer = (settings.auth_dev_issuer if settings.auth_mode == "dev" else settings.auth_oidc_issuer).rstrip("/")
    audience = API_AUDIENCE if settings.auth_mode == "dev" else settings.auth_oidc_audience
    if not issuer or not audience:
        raise AuthenticationError("OIDC authentication is not fully configured")
    try:
        if jwt.get_unverified_header(token).get("typ") != "at+jwt":
            raise AuthenticationError("ID tokens are not API credentials")
        jwks_url = _discover_jwks_url(issuer)
        key = _jwks_client(jwks_url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Bearer token validation failed") from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AuthenticationError("Bearer token has no subject")
    raw_roles = claims.get(settings.auth_oidc_roles_claim, [])
    if isinstance(raw_roles, str):
        roles = frozenset(raw_roles.replace(",", " ").split())
    elif isinstance(raw_roles, list) and all(isinstance(role, str) for role in raw_roles):
        roles = frozenset(raw_roles)
    else:
        roles = frozenset()
    scopes = claims.get("scope", "")
    if not isinstance(scopes, str):
        raise AuthenticationError("Bearer token has invalid scopes")
    roles = roles | frozenset(scopes.split())
    required_scopes = frozenset(settings.auth_oidc_required_scopes)
    if not required_scopes.issubset(roles):
        raise AuthenticationError("Bearer token lacks required API scope")
    return Principal(issuer=issuer, subject=subject, roles=roles, authentication_method="oidc")


async def authenticate_scope(scope: Scope) -> Principal:
    """Authenticate once and return the canonical principal for an HTTP scope."""
    mode = settings.auth_mode
    authorization = _header(scope, "authorization")
    if mode in {"dev", "oidc"} and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("Expected a bearer token")
        return await asyncio.to_thread(_decode_oidc_token, token)
    if mode == "proxy":
        internal_principal = _internal_proxy_principal(scope)
        if internal_principal is not None:
            return internal_principal
        return _proxy_principal(scope)

    if mode is None:
        api_key = _header(scope, "x-api-key")
        configured_key = reveal(settings.api_key)
        if api_key and configured_key and hmac.compare_digest(api_key, configured_key):
            return Principal(
                issuer="api-key",
                subject="shared",
                roles=frozenset(settings.auth_admin_claim_values),
                authentication_method="api_key",
            )
    raise AuthenticationError("Authentication required")


class PrincipalAuthMiddleware:
    """Authenticate non-probe HTTP requests before FastAPI or FastMCP consumes them."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in _NO_AUTH_PATHS:
            await self.app(scope, receive, send)
            return
        try:
            principal = await authenticate_scope(scope)
        except (AuthenticationError, UnicodeDecodeError):
            await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
            return
        scope.setdefault("state", {})[PRINCIPAL_SCOPE_KEY] = principal
        if principal.authentication_method != "api_key":
            try:
                owned_session = await select_owned_session(principal, _header(scope, "x-aio-session"))
            except HTTPException as exc:
                await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
                return
            scope["state"]["aio_owned_session"] = owned_session
            headers = [(key, value) for key, value in scope.get("headers", []) if key.lower() != b"client"]
            headers.append((b"client", owned_session.client_key.encode("ascii")))
            scope["headers"] = headers
            # ``client`` is the session selector for API endpoints, but it is
            # the output-format selector on the MCP client-config endpoint.
            # Do not replace the latter or every principal request becomes the
            # unsupported internal client-key variant.
            if scope.get("path") != "/mcp/client-config":
                query = [
                    (key, value)
                    for key, value in parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
                    if key != "client"
                ]
                query.append(("client", owned_session.client_key))
                scope["query_string"] = urlencode(query).encode("ascii")
            context_token = _owned_session_context.set(owned_session)
            try:
                await self.app(scope, receive, send)
            finally:
                _owned_session_context.reset(context_token)
            return
        await self.app(scope, receive, send)
