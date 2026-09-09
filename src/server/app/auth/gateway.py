"""ASGI routes exposed by the embedded AI Optimizer OIDC gateway."""

from __future__ import annotations

import logging
from base64 import b64decode
from binascii import Error as BinasciiError
from html import escape
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from server.app.auth.providers import GitHubProvider, OidcProvider, ProviderError
from server.app.auth.service import GatewayService

LOGGER = logging.getLogger(__name__)
GatewayProvider = GitHubProvider | OidcProvider | None


def _local_login_page(continue_to: str, error: str | None = None) -> HTMLResponse:
    """Render the local-account sign-in form."""
    continuation = escape(continue_to, quote=True)
    message = f'<p role="alert">{escape(error)}</p>' if error else ""
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><title>Sign in</title>
        <style>body{{font-family:sans-serif;max-width:28rem;margin:5rem auto}}
        input,button{{box-sizing:border-box;width:100%;padding:.7rem;margin:.3rem 0}}
        p[role=alert]{{color:#a00}}</style>
        </head><body><h1>Sign in</h1>{message}<form method="post" action="/login">
        <label>Username<input name="username" autocomplete="username" required></label>
        <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
        <input name="continue_to" type="hidden" value="{continuation}"><button>Sign in</button></form></body></html>""",
        status_code=401 if error else 200,
    )


def _client_credentials(request: Request, client_id: str, client_secret: str) -> tuple[str, str]:
    """Read OAuth client credentials from HTTP Basic or the request form."""
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return client_id, client_secret
    if client_id or client_secret:
        raise ValueError("Multiple client authentication methods")
    try:
        decoded = b64decode(encoded, validate=True).decode("utf-8")
    except (BinasciiError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid client credentials") from exc
    basic_client_id, separator, basic_client_secret = decoded.partition(":")
    if not separator or not basic_client_id:
        raise ValueError("Invalid client credentials")
    return basic_client_id, basic_client_secret


async def _logout_parameters(request: Request) -> tuple[str | None, str | None]:
    """Read optional RP-initiated logout parameters."""
    client_id = request.query_params.get("client_id")
    redirect_uri = request.query_params.get("post_logout_redirect_uri")
    if request.method == "POST":
        form = await request.form()
        form_client_id = form.get("client_id")
        form_redirect_uri = form.get("post_logout_redirect_uri")
        if isinstance(form_client_id, str):
            client_id = form_client_id
        if isinstance(form_redirect_uri, str):
            redirect_uri = form_redirect_uri
    return client_id, redirect_uri


def _redirect_with_code(redirect_uri: str, code: str, state: str) -> RedirectResponse:
    """Return to a downstream client only after a successful authorization."""
    separator = "&" if "?" in redirect_uri else "?"
    location = f"{redirect_uri}{separator}code={quote(code)}"
    if state:
        location += f"&state={quote(state)}"
    return RedirectResponse(location, status_code=302)


async def create_application(service: GatewayService, provider: GatewayProvider = None) -> FastAPI:  # noqa: PLR0915
    """Create an embedded OIDC provider with one selected identity source."""
    await service.initialize()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=await service.session_secret(),
        session_cookie="aio_auth",
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
        if service.config.mode != "local":
            return Response(status_code=404)
        if not continue_to.startswith("/authorize?"):
            return HTMLResponse("Invalid login continuation", status_code=400)
        return _local_login_page(continue_to)

    @app.post("/login")
    async def login(request: Request, username: str = Form(), password: str = Form(), continue_to: str = Form()):
        if service.config.mode != "local" or not continue_to.startswith("/authorize?"):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        principal = await service.authenticate_local(username, password)
        if principal is None:
            return _local_login_page(continue_to, "Invalid username or password")
        request.session["login_session"] = await service.create_login_session(principal)
        return RedirectResponse(continue_to, status_code=303)

    @app.get("/authorize")
    async def authorize(  # noqa: PLR0911
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
        raw_session = request.session.get("login_session")
        principal = await service.get_login_session_principal(raw_session) if isinstance(raw_session, str) else None
        if principal is not None:
            try:
                code = await service.create_authorization_code(
                    principal=principal,
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    scope=scope,
                    nonce=nonce,
                    code_challenge=code_challenge,
                )
            except ValueError as exc:
                return JSONResponse({"error": "invalid_request", "error_description": str(exc)}, status_code=400)
            return _redirect_with_code(redirect_uri, code, state)
        if service.config.mode == "local":
            continuation = f"/authorize?{request.url.query}"
            return RedirectResponse(f"/login?continue_to={quote(continuation, safe='')}", status_code=303)
        if provider is None:
            return JSONResponse({"error": "server_error"}, status_code=500)
        try:
            transaction = await service.create_login_transaction(
                client_id=client_id,
                redirect_uri=redirect_uri,
                scope=scope,
                nonce=nonce,
                code_challenge=code_challenge,
                downstream_state=state,
            )
            if isinstance(provider, GitHubProvider):
                destination = provider.authorization_url(
                    redirect_uri=service.callback_uri, state=transaction.state, verifier=transaction.upstream_verifier
                )
            else:
                destination = await provider.authorization_url(
                    redirect_uri=service.callback_uri,
                    state=transaction.state,
                    nonce=transaction.upstream_nonce,
                    verifier=transaction.upstream_verifier,
                )
        except (ProviderError, ValueError) as exc:
            return JSONResponse({"error": "invalid_request", "error_description": str(exc)}, status_code=400)
        return RedirectResponse(destination, status_code=302)

    @app.get("/callback")
    async def callback(request: Request, state: str, code: str = "", error: str = ""):
        transaction = await service.consume_login_transaction(state)
        if transaction is None:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if error or not code or provider is None:
            return JSONResponse({"error": "access_denied"}, status_code=400)
        try:
            if isinstance(provider, GitHubProvider):
                identity = await provider.complete(
                    code=code, verifier=transaction.upstream_verifier, redirect_uri=service.callback_uri
                )
            else:
                identity = await provider.complete(
                    code=code,
                    verifier=transaction.upstream_verifier,
                    nonce=transaction.upstream_nonce,
                    redirect_uri=service.callback_uri,
                )
            raw_session = await service.complete_external_login(identity)
            principal = await service.get_login_session_principal(raw_session)
            if principal is None:
                raise ValueError("Account is disabled")
            request.session["login_session"] = raw_session
            downstream_code = await service.create_authorization_code(
                principal=principal,
                client_id=transaction.client_id,
                redirect_uri=transaction.redirect_uri,
                scope=transaction.scope,
                nonce=transaction.nonce,
                code_challenge=transaction.code_challenge,
            )
        except (ProviderError, ValueError) as exc:
            LOGGER.warning("Authentication callback rejected: %s", exc)
            return JSONResponse({"error": "access_denied"}, status_code=400)
        return _redirect_with_code(transaction.redirect_uri, downstream_code, transaction.downstream_state)

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
            LOGGER.warning("Gateway token exchange rejected: %s", exc)
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

    @app.get("/userinfo")
    async def userinfo(request: Request):
        scheme, _, raw_token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not raw_token:
            return JSONResponse({"error": "invalid_token"}, status_code=401)
        try:
            return await service.user_info(raw_token)
        except ValueError:
            return JSONResponse({"error": "invalid_token"}, status_code=401)

    @app.api_route("/logout", methods=["GET", "POST"])
    async def logout(request: Request):
        raw_session = request.session.get("login_session")
        if isinstance(raw_session, str):
            await service.revoke_login_session(raw_session)
        request.session.clear()
        client_id, redirect_uri = await _logout_parameters(request)
        if redirect_uri:
            client = await service.store.get_client(client_id) if client_id else None
            if client is None or redirect_uri not in client.redirect_uris:
                return JSONResponse({"error": "invalid_request"}, status_code=400)
            return RedirectResponse(redirect_uri, status_code=302)
        return Response(status_code=204)

    return app
