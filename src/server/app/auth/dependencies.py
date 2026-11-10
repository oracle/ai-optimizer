"""Fail-closed FastAPI authentication dependencies."""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from server.app.auth.models import AuthContext
from server.app.auth.service import AuthAuthorityUnavailable, AuthenticationError, request_auth_context


@dataclass
class _AuthorityState:
    ready: bool = False
    error: str = "Authentication authority has not passed preflight"


AUTHORITY_STATE = _AuthorityState()
_BEARER = HTTPBearer(auto_error=False)


def set_authority_state(ready: bool, error: str = "") -> None:
    """Publish authentication preflight state for probes and dependencies."""
    AUTHORITY_STATE.ready = ready
    AUTHORITY_STATE.error = error or ("" if ready else "Authentication authority is unavailable")


async def require_authenticated(
    request: Request,
    _credential: HTTPAuthorizationCredentials | None = Depends(_BEARER),
) -> AuthContext:
    """Require a verified principal and fail closed before authority preflight."""
    try:
        if not AUTHORITY_STATE.ready:
            raise AuthAuthorityUnavailable(AUTHORITY_STATE.error)
        return await request_auth_context(request)
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except AuthAuthorityUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication authority is unavailable",
        ) from None


async def require_admin(context: AuthContext = Depends(require_authenticated)) -> AuthContext:
    """Require the reserved administrator role."""
    if "admin" not in context.principal.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return context
