"""Credential parsing and authentication provider registry."""

from contextvars import ContextVar
from typing import Protocol

from fastapi import Request

from server.app.auth.models import AuthContext, AuthMode, Principal, RequestCredential, workspace_key
from server.app.core.settings import settings


class AuthenticationError(ValueError):
    """Raised when a credential cannot establish an identity."""


class AuthAuthorityUnavailable(RuntimeError):
    """Raised when the selected credential authority is unavailable."""


class Authenticator(Protocol):
    async def authenticate(self, credential: RequestCredential) -> Principal: ...


class _PendingAuthenticator:
    async def authenticate(self, credential: RequestCredential) -> Principal:
        del credential
        raise AuthAuthorityUnavailable("Authentication for the configured mode is not initialized")


AUTHENTICATORS: dict[AuthMode, Authenticator] = {
    "local_users": _PendingAuthenticator(),
    "oidc": _PendingAuthenticator(),
}
_CURRENT_CREDENTIAL: ContextVar[RequestCredential | None] = ContextVar("auth_credential", default=None)


def register_authenticator(mode: AuthMode, authenticator: Authenticator) -> None:
    """Register the validated credential provider for a mode."""
    AUTHENTICATORS[mode] = authenticator


def authenticator_ready(mode: AuthMode | None = None) -> bool:
    """Return whether the selected mode has an installed credential provider."""
    authenticator = AUTHENTICATORS.get(mode or settings.auth_mode)
    return authenticator is not None and not isinstance(authenticator, _PendingAuthenticator)


def extract_bearer(request: Request) -> RequestCredential | None:
    """Extract an Authorization bearer credential without trusting its value."""
    scheme, separator, value = request.headers.get("Authorization", "").partition(" ")
    if separator and scheme.casefold() == "bearer" and value.strip():
        return RequestCredential(kind="bearer", value=value.strip())
    return None


async def authenticate_credential(credential: RequestCredential | None) -> Principal:
    """Authenticate a parsed credential through the selected authority."""
    if credential is None:
        raise AuthenticationError("Authentication required")
    authenticator = AUTHENTICATORS.get(settings.auth_mode)
    if authenticator is None:
        raise AuthAuthorityUnavailable("Authentication authority is unavailable")
    return await authenticator.authenticate(credential)


async def request_auth_context(request: Request) -> AuthContext:
    """Authenticate a request and derive its server-owned workspace."""
    credential = extract_bearer(request)
    if credential is None:
        raise AuthenticationError("Authentication required")
    principal = await authenticate_credential(credential)
    _CURRENT_CREDENTIAL.set(credential)
    return AuthContext(
        principal=principal,
        credential=credential,
        workspace_key=workspace_key(principal.user_id),
    )


def current_bearer() -> str:
    """Return the verified bearer credential for in-request server calls."""
    credential = _CURRENT_CREDENTIAL.get()
    if credential is None:
        raise AuthAuthorityUnavailable("No authenticated request credential is available")
    return credential.value
