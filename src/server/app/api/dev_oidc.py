"""ASGI routes for the built-in development OpenID Connect provider."""

from __future__ import annotations

import logging
from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from html import escape
from pathlib import Path
from urllib.parse import quote

import jwt
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from server.app.core.dev_oidc import DevelopmentOidcService

LOGGER = logging.getLogger(__name__)
_BRAND_LOGO_PATH = Path(__file__).resolve().parents[3] / "client" / "assets" / "logo.png"


def _brand_logo_data_uri() -> str:
    """Return the application wordmark as an embeddable image."""
    try:
        encoded_logo = b64encode(_BRAND_LOGO_PATH.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:image/png;base64,{encoded_logo}"


def _login_page(continue_to: str, *, error: str | None = None, status_code: int = 200) -> HTMLResponse:
    """Render the branded development sign-in page."""
    continuation_value = escape(continue_to, quote=True)
    logo_data_uri = escape(_brand_logo_data_uri(), quote=True)
    error_message = f'<p class="form-error" role="alert">{escape(error)}</p>' if error else ""
    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Oracle AI Optimizer and Toolkit - Sign in</title>
            <style>
              :root {{
                color-scheme: light;
                font-family: "Source Sans 3", "Segoe UI", sans-serif;
                color: #262626;
                background: #f7f8fa;
              }}
              * {{ box-sizing: border-box; }}
              body {{
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                margin: 0;
                padding: 2rem 1rem;
                background: radial-gradient(circle at top, #ffffff 0, #f7f8fa 55%, #eef1f5 100%);
              }}
              .auth-shell {{ width: min(100%, 28rem); }}
              .brand {{ margin-bottom: 1.75rem; text-align: center; }}
              .brand-logo {{ display: block; width: min(100%, 24rem); height: auto; margin: 0 auto; }}
              .auth-card {{
                padding: 2rem;
                border: 1px solid #e2e5e9;
                border-radius: 0.8rem;
                background: #ffffff;
                box-shadow: 0 0.75rem 2.5rem rgb(38 38 38 / 10%);
              }}
              h1 {{ margin: 0; font-size: 1.65rem; font-weight: 600; }}
              .intro {{ margin: 0.55rem 0 1.5rem; color: #606770; line-height: 1.5; }}
              label {{ display: block; margin: 1rem 0 0.4rem; font-weight: 600; }}
              input {{
                width: 100%;
                padding: 0.7rem 0.8rem;
                border: 1px solid #b9bec7;
                border-radius: 0.35rem;
                color: #262626;
                background: #ffffff;
                font: inherit;
                font-size: 1rem;
              }}
              input:focus {{ border-color: #1476b8; outline: 0.15rem solid rgb(20 118 184 / 20%); }}
              button {{
                width: 100%;
                margin-top: 1.5rem;
                padding: 0.75rem 1rem;
                border: 0;
                border-radius: 0.35rem;
                color: #ffffff;
                background: #1476b8;
                cursor: pointer;
                font: inherit;
                font-weight: 600;
              }}
              button:hover {{ background: #0f5f96; }}
              .form-error {{
                margin: 0 0 1rem;
                padding: 0.75rem;
                border: 1px solid #e0a7a0;
                border-radius: 0.35rem;
                color: #8d2116;
                background: #fff4f2;
              }}
            </style>
          </head>
          <body>
            <main class="auth-shell">
              <header class="brand" aria-label="Oracle AI Optimizer and Toolkit">
                <img class="brand-logo" src="{logo_data_uri}" alt="Oracle AI Optimizer and Toolkit">
              </header>
              <section class="auth-card">
                <h1>Sign in</h1>
                <p class="intro">Sign in to continue to Oracle AI Optimizer and Toolkit.</p>
                {error_message}
                <form method="post" action="/login">
                  <label for="username">Email</label>
                  <input id="username" name="username" type="email" autocomplete="username" required>
                  <label for="password">Password</label>
                  <input id="password" name="password" type="password" autocomplete="current-password" required>
                  <input name="continue_to" type="hidden" value="{continuation_value}">
                  <button type="submit">Sign in</button>
                </form>
              </section>
            </main>
          </body>
        </html>
        """,
        status_code=status_code,
    )


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
        return _login_page(continue_to)

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
            return _login_page(continue_to, error="Invalid username or password", status_code=401)
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
