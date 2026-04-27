"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for shared FastAPI dependencies (verify_api_key).
"""
# spell-checker: disable

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from server.app.api.deps import verify_api_key

pytestmark = pytest.mark.anyio


@pytest.mark.unit
async def test_verify_api_key_valid():
    """Returns the API key string when it matches the configured key."""
    with patch("server.app.api.deps.settings") as mock_settings:
        mock_settings.api_key = "test-key"
        result = await verify_api_key("test-key")
    assert result == "test-key"


@pytest.mark.unit
async def test_verify_api_key_none_provided():
    """Raises 403 when no API key is provided in the request."""
    with patch("server.app.api.deps.settings") as mock_settings:
        mock_settings.api_key = "test-key"
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(None)
    assert exc_info.value.status_code == 403


@pytest.mark.unit
async def test_verify_api_key_none_configured():
    """Raises 403 when no API key is configured."""
    with patch("server.app.api.deps.settings") as mock_settings:
        mock_settings.api_key = None
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key("some-key")
    assert exc_info.value.status_code == 403


@pytest.mark.unit
async def test_verify_api_key_both_none():
    """Raises 403 when both provided and configured keys are None."""
    with patch("server.app.api.deps.settings") as mock_settings:
        mock_settings.api_key = None
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(None)
    assert exc_info.value.status_code == 403


@pytest.mark.unit
async def test_verify_api_key_mismatch():
    """Raises 403 when provided key does not match configured key."""
    with patch("server.app.api.deps.settings") as mock_settings:
        mock_settings.api_key = "correct-key"
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key("wrong-key")
    assert exc_info.value.status_code == 403
