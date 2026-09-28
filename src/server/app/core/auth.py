"""Canonical-principal authentication shared by REST and MCP transports."""

from __future__ import annotations

import hmac
import ipaddress
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlencode

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from server.app.auth.models import AuthenticatedIdentity
from server.app.auth.store import OracleAuthStore
from server.app.auth.tokens import digest
from server.app.core.secrets import reveal
from server.app.core.sessions import OwnedSession, select_owned_session
from server.app.core.settings import settings

PRINCIPAL_SCOPE_KEY = "aio_principal"
INTERNAL_PROXY_TOKEN = secrets.token_urlsafe(32)
_owned_session_context: ContextVar[OwnedSession | None] = ContextVar("aio_owned_session", default=None)
_NO_AUTH_PATHS = frozenset({"/v1/liveness", "/v1/readiness", "/v1/healthz", "/mcp/healthz", "/v1/docs"})
GATEWAY_AUTH_MODES = frozenset({"local", "github", "oidc"})


def authenticated_client(thread_id: str) -> str:
    """Return the principal-owned client for MCP work, when one is active."""
    owned_session = _owned_session_context.get()
    return owned_session.client_key if owned_session is not None else thread_id


@dataclass(frozen=True, slots=True)
class Principal:
    """Validated durable identity; the sole authority for ownership checks."""

    principal_id: str
    roles: frozenset[str]
    authentication_method: Literal["gateway", "proxy", "api_key"]

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


async def _proxy_principal(scope: Scope) -> Principal:
    if not _is_trusted_proxy(scope):
        raise AuthenticationError("Request did not arrive from a trusted identity proxy")
    subject = _header(scope, settings.auth_proxy_subject_header)
    if not subject:
        raise AuthenticationError("Trusted proxy did not provide an authenticated subject")
    raw_roles = _header(scope, settings.auth_proxy_roles_header) or ""
    record = await OracleAuthStore().resolve_identity(
        AuthenticatedIdentity(
            issuer=settings.auth_proxy_issuer,
            subject=subject,
            display_name=subject,
            roles=frozenset(role.strip() for role in raw_roles.split(",") if role.strip()),
        ),
        "proxy",
    )
    if not record.active:
        raise AuthenticationError("Account is disabled")
    return Principal(record.principal_id, record.roles, "proxy")


async def _internal_proxy_principal(scope: Scope) -> Principal | None:
    """Accept a loopback identity forwarded only by this process."""
    client = scope.get("client")
    principal_id = _header(scope, "x-aio-internal-principal")
    token = _header(scope, "x-aio-internal-token")
    if (
        not principal_id
        or not client
        or client[0] not in {"127.0.0.1", "::1"}
        or not token
        or not hmac.compare_digest(token, INTERNAL_PROXY_TOKEN)
    ):
        return None
    record = await OracleAuthStore().get_principal(principal_id)
    if record is None or not record.active:
        return None
    return Principal(record.principal_id, record.roles, "proxy")


async def _gateway_principal(raw_token: str) -> Principal:
    """Resolve an opaque gateway access token and current principal through CORE."""
    store = OracleAuthStore()
    token = await store.get_access_token(digest(raw_token))
    if token is None or token.revoked:
        raise AuthenticationError("Bearer token is invalid")
    record = await store.get_principal(token.principal_id)
    if record is None or not record.active:
        raise AuthenticationError("Account is disabled")
    return Principal(record.principal_id, record.roles, "gateway")


async def authenticate_scope(scope: Scope) -> Principal:
    """Authenticate once and return the canonical principal for an HTTP scope."""
    mode = settings.auth_mode
    authorization = _header(scope, "authorization")
    if mode in GATEWAY_AUTH_MODES and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("Expected a bearer token")
        return await _gateway_principal(token)
    if mode == "proxy":
        internal_principal = await _internal_proxy_principal(scope)
        if internal_principal is not None:
            return internal_principal
        return await _proxy_principal(scope)
    if mode is None:
        api_key = _header(scope, "x-api-key")
        configured_key = reveal(settings.api_key)
        if api_key and configured_key and hmac.compare_digest(api_key, configured_key):
            return Principal("api-key:shared", frozenset(settings.auth_admin_claim_values), "api_key")
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
        except (AuthenticationError, UnicodeDecodeError, RuntimeError):
            await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
            return
        scope.setdefault("state", {})[PRINCIPAL_SCOPE_KEY] = principal
        if principal.authentication_method == "api_key":
            await self.app(scope, receive, send)
            return
        try:
            owned_session = await select_owned_session(principal, _header(scope, "x-aio-session"))
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
            return
        scope["state"]["aio_owned_session"] = owned_session
        headers = [(key, value) for key, value in scope.get("headers", []) if key.lower() != b"client"]
        headers.append((b"client", owned_session.client_key.encode("ascii")))
        scope["headers"] = headers
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
