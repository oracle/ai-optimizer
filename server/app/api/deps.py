"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared FastAPI dependencies.
"""

import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from server.app.core.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Depends(_api_key_header),
) -> str:
    """Validate the X-API-Key header against the configured API key.

    Rejects all requests when no API key is configured (fail-secure).
    """
    configured_key = settings.api_key
    if api_key is None or configured_key is None or not hmac.compare_digest(api_key, configured_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return api_key
