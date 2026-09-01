"""ASGI routes for the built-in development OpenID Connect provider."""

from __future__ import annotations

import logging
from base64 import b64decode
from binascii import Error as BinasciiError
from html import escape
from urllib.parse import quote

import jwt
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from server.app.core.dev_oidc import DevelopmentOidcService

LOGGER = logging.getLogger(__name__)


def _client_credentials(request: Request, client_id: str, client_secret: str) -> tuple[str, str]:
    """Read client credentials from HTTP Basic or form-post authentication."""
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return client_id, client_secret
    if client_id or client_secret:
        raise ValueError("Multiple client authentication methods")
    try:
        decoded = b64decode(encoded, validate=True).decode("utf-8")
    except (BinasciiError, UnicodeDecodeError):
        raise ValueError("Invalid client credentials") from None
    basic_client_id, separator, basic_client_secret = decoded.partition(":")
    if not separator or not basic_client_id:
        raise ValueError("Invalid client credentials")
    return basic_client_id, basic_client_secret


async def create_application(service: DevelopmentOidcService) -> FastAPI:
    """Create the dedicated-origin ASGI application for one provider service."""
    await service.initialize()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=await service.session_secret(),
        session_cookie="aio_dev_oidc",
        https_only=service.issuer.startswith("https://"),
        same_site="lax",
    )

    @app.get("/.well-known/openid-configuration")
    async def discovery():
        return await service.discovery_document()

    @app.get("/jwks.json")
    async def jwks():
        return await service.jwks_document()

    @app.get("/mcp-client-metadata.json")
    async def mcp_client_metadata():
        return await service.mcp_client_metadata_document()

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(continue_to: str = "/"):
        if not continue_to.startswith("/authorize?"):
            return HTMLResponse("Invalid login continuation", status_code=400)
        return HTMLResponse(
            """
            <!doctype html><title>Development sign in</title>
            <form method="post" action="/login">
              <label>Email <input name="username" autocomplete="username" required></label>
              <label>Password <input name="password" type="password" autocomplete="current-password" required></label>
              <input name="continue_to" type="hidden" value="%s">
              <button type="submit">Sign in</button>
            </form>
            """
            % escape(continue_to, quote=True),
        )

    @app.post("/login")
    async def login(
        request: Request,
        username: str = Form(),
        password: str = Form(),
        continue_to: str = Form(),
    ):
        if not continue_to.startswith("/authorize?"):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        user = await service.authenticate(username, password)
        if user is None:
            return HTMLResponse("Invalid username or password", status_code=401)
        request.session["login_session"] = await service.create_login_session(user)
        return RedirectResponse(continue_to, status_code=303)

    @app.get("/authorize")
    async def authorize(
        request: Request,
        response_type: str,
        client_id: str,
        redirect_uri: str,
        scope: str,
        state: str = "",
        nonce: str = "",
        code_challenge: str = "",
        code_challenge_method: str = "",
    ):
        if response_type != "code" or code_challenge_method != "S256":
            return JSONResponse({"error": "unsupported_response_type"}, status_code=400)
        login_session = request.session.get("login_session")
        user = await service.get_login_session_user(login_session) if isinstance(login_session, str) else None
        if user is None:
            continuation = f"/authorize?{request.url.query}"
            return RedirectResponse(f"/login?continue_to={quote(continuation, safe='')}", status_code=303)
        try:
            code = await service.create_authorization_code(
                username=user.username,
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=scope,
                nonce=nonce,
                code_challenge=code_challenge,
            )
        except ValueError as exc:
            return JSONResponse({"error": "invalid_request", "error_description": str(exc)}, status_code=400)
        separator = "&" if "?" in redirect_uri else "?"
        location = f"{redirect_uri}{separator}code={quote(code)}"
        if state:
            location += f"&state={quote(state)}"
        return RedirectResponse(location, status_code=302)

    @app.post("/token")
    async def token(
        request: Request,
        grant_type: str = Form(),
        client_id: str = Form(default=""),
        client_secret: str = Form(default=""),
        code: str = Form(),
        redirect_uri: str = Form(),
        code_verifier: str = Form(),
    ):
        if grant_type != "authorization_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        try:
            client_id, client_secret = _client_credentials(request, client_id, client_secret)
            return await service.exchange_code(
                client_id=client_id,
                client_secret=client_secret,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
        except ValueError as exc:
            LOGGER.warning("Development OIDC token exchange rejected: %s", exc)
            return JSONResponse({"error": "invalid_grant", "error_description": str(exc)}, status_code=400)

    @app.get("/userinfo")
    async def userinfo(request: Request):
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse({"error": "invalid_token"}, status_code=401)
        try:
            return await service.user_info(token)
        except (ValueError, jwt.PyJWTError):
            return JSONResponse({"error": "invalid_token"}, status_code=401)

    @app.post("/logout", status_code=204)
    async def logout(request: Request):
        login_session = request.session.get("login_session")
        if isinstance(login_session, str):
            await service.revoke_login_session(login_session)
        request.session.clear()
        return Response(status_code=204)

    return app
