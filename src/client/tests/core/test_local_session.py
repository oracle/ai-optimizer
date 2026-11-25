"""Tests for the Streamlit local-session cookie bridge."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.requests import Request

from client.app.core import local_session

pytestmark = pytest.mark.unit


def _request(payload: dict, *, scheme: str = "http", path: str = "/auth/local/session") -> Request:
    body = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "scheme": scheme,
            "server": ("example.test", 443 if scheme == "https" else 80),
            "client": ("127.0.0.1", 1234),
        },
        receive,
    )


async def test_valid_session_sets_httponly_cookie():
    api_response = MagicMock()
    api_response.raise_for_status.return_value = None
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.get.return_value = api_response

    with patch(f"{local_session.__name__}.httpx.AsyncClient", return_value=client):
        response = await local_session.session_cookie_route(_request({"action": "set", "token": "opaque"}))

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "aio_local_session=opaque" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert "Max-Age" not in cookie
    client.get.assert_awaited_once()


async def test_invalid_session_is_not_stored():
    request = httpx.Request("GET", "https://example.test/v1/auth/me")
    api_response = MagicMock()
    api_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "unauthorized",
        request=request,
        response=httpx.Response(401, request=request),
    )
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.get.return_value = api_response

    with patch(f"{local_session.__name__}.httpx.AsyncClient", return_value=client):
        response = await local_session.session_cookie_route(_request({"action": "set", "token": "opaque"}))

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


async def test_clear_deletes_session_cookie():
    response = await local_session.session_cookie_route(
        _request({"action": "clear"}, path="/optimizer/auth/local/session")
    )

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "aio_local_session=" in cookie
    assert "Max-Age=0" in cookie
    assert "Path=/optimizer" in cookie
