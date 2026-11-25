"""Browser-session persistence for local Streamlit authentication."""

import secrets
from functools import lru_cache
from pathlib import Path

import httpx
import streamlit as st
import streamlit.components.v1 as components
from starlette.requests import Request
from starlette.responses import JSONResponse

from client.app.core.api import _base_url
from net_addressing import verify_for_url

COOKIE_NAME = "aio_local_session"
_ROUTE_SUFFIX = "/auth/local/session"


@lru_cache(maxsize=1)
def _local_session_component():
    """Register the component from the active Streamlit script context."""
    return components.declare_component(
        "aio_local_session",
        path=str(Path(__file__).resolve().parents[1] / "components" / "local_session"),
    )


def route_paths() -> tuple[str, str]:
    """Return root and prefixed forms of the local-session route."""
    return _ROUTE_SUFFIX, f"/{{base:path}}{_ROUTE_SUFFIX}"


def _cookie_path(request: Request) -> str:
    """Scope the cookie to the active Streamlit base path."""
    return request.url.path.removesuffix(_ROUTE_SUFFIX) or "/"


def browser_token() -> str | None:
    """Read the HttpOnly local-session token from the initial browser request."""
    return st.context.cookies.get(COOKIE_NAME)


def sync_browser_cookie(action: str, token: str | None = None) -> bool | None:
    """Ask the browser to set or clear its HttpOnly local-session cookie."""
    return _local_session_component()(
        action=action,
        endpoint=_ROUTE_SUFFIX.lstrip("/"),
        token=token,
        default=None,
        key=f"local-session-{action}",
        tab_index=-1,
    )


def _cookie_check_response(request: Request, token: object) -> JSONResponse:
    cookie = request.cookies.get(COOKIE_NAME)
    if not isinstance(token, str) or cookie is None or not secrets.compare_digest(cookie, token):
        return JSONResponse({"detail": "Session cookie unavailable"}, status_code=401)
    return JSONResponse({"ok": True})


async def session_cookie_route(request: Request) -> JSONResponse:
    """Set or clear the local bearer cookie through the Streamlit origin."""
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"detail": "Invalid request"}, status_code=400)

    action = payload.get("action")
    response = JSONResponse({"ok": True})
    if action == "clear":
        response.delete_cookie(COOKIE_NAME, path=_cookie_path(request), samesite="strict")
        return response
    if action == "check":
        return _cookie_check_response(request, payload.get("token"))
    if action != "set" or not isinstance(payload.get("token"), str):
        return JSONResponse({"detail": "Invalid request"}, status_code=400)

    token = payload["token"]
    base = _base_url()
    try:
        async with httpx.AsyncClient(timeout=5, verify=verify_for_url(base)) as client:
            auth_response = await client.get(
                f"{base}/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            auth_response.raise_for_status()
    except httpx.HTTPError:
        return JSONResponse({"detail": "Invalid session"}, status_code=401)

    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="strict",
        path=_cookie_path(request),
    )
    return response
