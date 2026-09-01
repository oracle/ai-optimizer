"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared FastAPI dependencies.
"""

import hmac

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from server.app.core.auth import PRINCIPAL_SCOPE_KEY, Principal
from server.app.core.secrets import reveal
from server.app.core.settings import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Depends(_api_key_header),
) -> str:
    """Validate the X-API-Key header against the configured API key.

    Rejects requests when no API key is configured.
    """
    configured_key = reveal(settings.api_key)
    if api_key is None or configured_key is None or not hmac.compare_digest(api_key, configured_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return api_key


async def require_principal(request: Request) -> Principal:
    """Return the principal authenticated by the shared outer ASGI middleware."""
    principal = request.scope.get("state", {}).get(PRINCIPAL_SCOPE_KEY)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return principal


async def require_administrator(principal: Principal = Depends(require_principal)) -> Principal:
    """Require administrator authority sourced from validated identity claims."""
    if not principal.is_administrator:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return principal
