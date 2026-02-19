"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared test fixtures.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from server.app.main import app
from server.app.core.settings import settings


@pytest.fixture
async def app_client():
    """Async HTTP client wired to the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url='http://test',
    ) as client:
        yield client


@pytest.fixture
def auth_headers():
    """Headers dict with a valid API key."""
    return {'X-API-Key': settings.api_key}
