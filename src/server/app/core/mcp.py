"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP server definition and transport middleware.
"""
# spell-checker: ignore asgi fastmcp

from fastmcp import FastMCP
from fastmcp import settings as fastmcp_settings
from fastmcp.server.auth import AccessToken, TokenVerifier
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from server.app.auth.dependencies import AUTHORITY_STATE
from server.app.auth.models import RequestCredential
from server.app.auth.service import AuthAuthorityUnavailable, AuthenticationError, authenticate_credential
from server.app.core.settings import settings
from server.app.mcp.transforms import DeterministicCatalogTransform

fastmcp_settings.mcp_camelcase_compat = False


class _ProjectTokenVerifier(TokenVerifier):
    """Apply the project authentication authority to native MCP requests."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not AUTHORITY_STATE.ready:
            return None
        try:
            principal = await authenticate_credential(RequestCredential(kind="bearer", value=token))
        except (AuthenticationError, AuthAuthorityUnavailable):
            return None
        return AccessToken(
            token=token,
            client_id=str(principal.user_id),
            scopes=sorted(principal.scopes),
            subject=principal.subject,
            resource=settings.oidc_public_server_url,
            claims={"roles": sorted(principal.roles), "username": principal.username},
        )


def _create_mcp_server(cache_ttl_seconds: int) -> FastMCP:
    """Create the shared MCP server with its catalog and cache policy."""
    return FastMCP(
        "Oracle AI Optimizer",
        auth=_ProjectTokenVerifier(),
        transforms=[DeterministicCatalogTransform()],
        cache_ttl=cache_ttl_seconds or None,
        cache_scope="private" if cache_ttl_seconds else None,
    )


mcp = _create_mcp_server(settings.mcp_cache_ttl_seconds)


class MCPOriginMiddleware:
    """Reject requests carrying an Origin header on the MCP transport."""

    def __init__(self, app: ASGIApp, path: str) -> None:
        self.app = app
        self.path = path.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_path = scope.get("path", "").rstrip("/")
        root_path = scope.get("root_path", "").rstrip("/")
        if root_path and request_path.startswith(f"{root_path}/"):
            request_path = request_path.removeprefix(root_path)

        if scope["type"] == "http" and request_path == self.path and Headers(scope=scope).get("origin") is not None:
            response = PlainTextResponse("Forbidden Origin", status_code=403)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
