"""Embedded OIDC gateway orchestration and durable principal resolution."""

from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from datetime import timedelta

from net_addressing import client_web_redirect_uri
from server.app.auth.models import (
    AccessToken,
    AuthClient,
    AuthenticatedIdentity,
    AuthorizationCode,
    LocalAccount,
    LoginSession,
    LoginTransaction,
    PrincipalRecord,
)
from server.app.auth.store import AuthStore, utc_now
from server.app.auth.tokens import (
    PKCE_VALUE,
    digest,
    generate_signing_key,
    hash_password,
    issue_id_token,
    jwks_document,
    pkce_challenge,
    random_token,
    verify_password,
)

WEB_CLIENT_ID = "platform-web-client"
MCP_CLIENT_METADATA_PATH = "/mcp-client-metadata.json"
STANDARD_SCOPES = frozenset({"openid", "profile", "email"})
API_SCOPES = frozenset({"aio.api", "aio.admin"})
SUPPORTED_SCOPES = STANDARD_SCOPES | API_SCOPES


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    """Runtime configuration shared by every gateway authentication source."""

    issuer: str
    mode: str
    web_client_secret: str
    web_redirect_uri: str
    local_admin_username: str
    local_admin_password: str
    access_token_minutes: int = 15
    login_session_hours: int = 8


class GatewayService:
    """OIDC provider for AI Optimizer clients and identity bridge for providers."""

    def __init__(self, config: GatewayConfig, store: AuthStore):
        self.config = config
        self.issuer = config.issuer.rstrip("/")
        self.store = store

    @property
    def mcp_client_id(self) -> str:
        """Return the stable URL client identifier used by MCP clients."""
        return f"{self.issuer}{MCP_CLIENT_METADATA_PATH}"

    @property
    def local_issuer(self) -> str:
        """Return the per-installation namespace for locally managed accounts."""
        return f"{self.issuer}/local"

    @property
    def callback_uri(self) -> str:
        """Return the shared upstream provider callback URI."""
        return f"{self.issuer}/callback"

    async def initialize(self) -> None:
        """Persist gateway clients, key material, and the local bootstrap account."""
        await self.store.save_client(
            AuthClient(
                WEB_CLIENT_ID,
                frozenset({self.config.web_redirect_uri or client_web_redirect_uri()}),
                SUPPORTED_SCOPES,
                public=False,
            )
        )
        await self.store.save_client(
            AuthClient(
                self.mcp_client_id,
                frozenset({"http://127.0.0.1:8766/callback"}),
                SUPPORTED_SCOPES,
            )
        )
        if await self.store.get_signing_key() is None:
            await self.store.save_signing_key(generate_signing_key())
        if self.config.mode == "local":
            await self.bootstrap_local_administrator()

    async def bootstrap_local_administrator(self) -> PrincipalRecord:
        """Create the configured local administrator only when it is missing."""
        username = self.config.local_admin_username.strip()
        password = self.config.local_admin_password
        if not username or not password:
            raise ValueError("Local authentication requires an administrator username and password")
        existing = await self.store.get_local_account(username)
        if existing is not None:
            principal = await self.store.get_principal(existing.principal_id)
            if principal is None:
                raise RuntimeError("Local administrator account has no principal")
            return principal
        return await self.create_local_account(
            username=username,
            password=password,
            display_name="Administrator",
            email=username if "@" in username else None,
            administrator=True,
        )

    async def create_local_account(
        self, *, username: str, password: str, display_name: str, email: str | None, administrator: bool = False
    ) -> PrincipalRecord:
        """Create one local account and its durable principal identity."""
        normalized_username = username.strip()
        if not normalized_username or not password or not display_name.strip():
            raise ValueError("Username, password, and display name are required")
        if await self.store.get_local_account(normalized_username) is not None:
            raise ValueError("A user with that username already exists")
        roles = {"aio.user"}
        if administrator:
            roles.add("aio.admin")
        identity = AuthenticatedIdentity(
            issuer=self.local_issuer,
            subject=str(uuid.uuid4()),
            display_name=display_name.strip(),
            email=email,
            roles=frozenset(roles),
        )
        principal = await self.store.resolve_identity(identity, "local")
        await self.store.save_local_account(
            LocalAccount(principal.principal_id, normalized_username, hash_password(password))
        )
        return principal

    async def authenticate_local(self, username: str, password: str) -> PrincipalRecord | None:
        """Authenticate a local account without revealing password-hash details."""
        account = await self.store.get_local_account(username.strip())
        if account is None or not verify_password(password, account.password_hash):
            return None
        principal = await self.store.get_principal(account.principal_id)
        return principal if principal is not None and principal.active else None

    async def set_local_password(self, username: str, password: str) -> None:
        """Replace a local account password through the administrative CLI."""
        account = await self.store.get_local_account(username.strip())
        if account is None:
            raise ValueError("Unknown local user")
        if not password:
            raise ValueError("Password is required")
        await self.store.save_local_account(
            LocalAccount(account.principal_id, account.username, hash_password(password))
        )

    async def local_principal(self, username: str) -> PrincipalRecord | None:
        """Resolve a local account for administrative account operations."""
        account = await self.store.get_local_account(username.strip())
        return await self.store.get_principal(account.principal_id) if account is not None else None

    async def create_login_session(self, principal: PrincipalRecord) -> str:
        """Create an opaque gateway browser session for an active principal."""
        raw_session = random_token()
        await self.store.save_login_session(
            LoginSession(
                digest(raw_session),
                principal.principal_id,
                utc_now() + timedelta(hours=self.config.login_session_hours),
            )
        )
        return raw_session

    async def get_login_session_principal(self, raw_session: str) -> PrincipalRecord | None:
        """Resolve a live browser session to its current principal status and roles."""
        session = await self.store.get_login_session(digest(raw_session))
        if session is None or session.revoked:
            return None
        principal = await self.store.get_principal(session.principal_id)
        return principal if principal is not None and principal.active else None

    async def revoke_login_session(self, raw_session: str) -> None:
        """Invalidate one browser session and all of that principal's API tokens."""
        session = await self.store.get_login_session(digest(raw_session))
        await self.store.revoke_login_session(digest(raw_session))
        if session is not None:
            await self.store.revoke_access_tokens(session.principal_id)

    async def create_authorization_code(
        self,
        *,
        principal: PrincipalRecord,
        client_id: str,
        redirect_uri: str,
        scope: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        """Create a downstream authorization code after a completed login."""
        requested_scopes = await self._validated_client_request(
            client_id=client_id, redirect_uri=redirect_uri, scope=scope, nonce=nonce, code_challenge=code_challenge
        )
        raw_code = random_token()
        await self.store.save_code(
            AuthorizationCode(
                digest(raw_code),
                client_id,
                principal.principal_id,
                redirect_uri,
                " ".join(sorted(requested_scopes)),
                nonce,
                code_challenge,
                utc_now() + timedelta(minutes=5),
            )
        )
        return raw_code

    async def create_login_transaction(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scope: str,
        nonce: str,
        code_challenge: str,
        downstream_state: str,
    ) -> LoginTransaction:
        """Persist the original downstream request before an upstream redirect."""
        await self._validated_client_request(
            client_id=client_id, redirect_uri=redirect_uri, scope=scope, nonce=nonce, code_challenge=code_challenge
        )
        transaction = LoginTransaction(
            state=random_token(),
            downstream_state=downstream_state,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            nonce=nonce,
            code_challenge=code_challenge,
            upstream_nonce=random_token(),
            upstream_verifier=random_token()[:64],
            expires_at=utc_now() + timedelta(minutes=5),
        )
        await self.store.save_transaction(transaction)
        return transaction

    async def consume_login_transaction(self, state: str) -> LoginTransaction | None:
        """Consume the single-use upstream callback transaction."""
        return await self.store.consume_transaction(state)

    async def complete_external_login(self, identity: AuthenticatedIdentity) -> str:
        """Resolve an upstream identity, record current role mapping, and create a session."""
        principal = await self.store.resolve_identity(identity, self.config.mode)
        if not principal.active:
            raise ValueError("Account is disabled")
        return await self.create_login_session(principal)

    async def exchange_code(
        self, *, client_id: str, client_secret: str, code: str, redirect_uri: str, code_verifier: str
    ) -> dict[str, str | int]:
        """Redeem a downstream code for an opaque API token and signed ID token."""
        if not PKCE_VALUE.fullmatch(code_verifier):
            raise ValueError("Invalid PKCE verifier")
        authorization_code = await self.store.get_code(digest(code))
        if authorization_code is None or authorization_code.used:
            raise ValueError("Invalid authorization code")
        if authorization_code.client_id != client_id or authorization_code.redirect_uri != redirect_uri:
            raise ValueError("Invalid authorization code")
        if not hmac.compare_digest(pkce_challenge(code_verifier), authorization_code.code_challenge):
            raise ValueError("Invalid PKCE verifier")
        client = await self.store.get_client(client_id)
        if client is None or (
            not client.public and not hmac.compare_digest(client_secret, self.config.web_client_secret)
        ):
            raise ValueError("Invalid client credentials")
        if not await self.store.mark_code_used(authorization_code.digest):
            raise ValueError("Invalid authorization code")
        principal = await self.store.get_principal(authorization_code.principal_id)
        signing_key = await self.store.get_signing_key()
        if principal is None or not principal.active or signing_key is None:
            raise ValueError("Authentication session is unavailable")
        raw_access_token = random_token()
        lifetime = self.config.access_token_minutes * 60
        await self.store.save_access_token(
            AccessToken(
                digest(raw_access_token),
                principal.principal_id,
                client_id,
                authorization_code.scope,
                utc_now() + timedelta(seconds=lifetime),
            )
        )
        return {
            "access_token": raw_access_token,
            "id_token": issue_id_token(
                issuer=self.issuer,
                client_id=client_id,
                principal=principal,
                nonce=authorization_code.nonce,
                signing_key=signing_key,
                lifetime=lifetime,
            ),
            "token_type": "Bearer",
            "expires_in": lifetime,
            "scope": authorization_code.scope,
        }

    async def principal_for_access_token(self, raw_token: str) -> PrincipalRecord | None:
        """Resolve a bearer token through CORE and load current account state."""
        token = await self.store.get_access_token(digest(raw_token))
        if token is None or token.revoked:
            return None
        principal = await self.store.get_principal(token.principal_id)
        return principal if principal is not None and principal.active else None

    async def user_info(self, raw_token: str) -> dict[str, object]:
        """Return UserInfo for a current opaque gateway access token."""
        principal = await self.principal_for_access_token(raw_token)
        if principal is None:
            raise ValueError("Access token is invalid")
        result: dict[str, object] = {"sub": principal.principal_id, "name": principal.display_name}
        if principal.email:
            result.update({"email": principal.email, "email_verified": True})
        return result

    async def discovery_document(self) -> dict[str, object]:
        """Publish OIDC discovery metadata for Streamlit and MCP clients."""
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "end_session_endpoint": f"{self.issuer}/logout",
            "userinfo_endpoint": f"{self.issuer}/userinfo",
            "jwks_uri": f"{self.issuer}/jwks.json",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": sorted(SUPPORTED_SCOPES),
            "code_challenge_methods_supported": ["S256"],
        }

    async def jwks_document(self) -> dict[str, list[dict[str, object]]]:
        """Publish the public signing key required to validate ID tokens."""
        key = await self.store.get_signing_key()
        if key is None:
            raise RuntimeError("Authentication gateway is not initialized")
        return jwks_document(key)

    async def mcp_client_metadata_document(self) -> dict[str, object]:
        """Publish fixed client metadata for MCP client-initiated authorization."""
        client = await self.store.get_client(self.mcp_client_id)
        if client is None:
            raise RuntimeError("Authentication gateway is not initialized")
        return {
            "client_id": client.client_id,
            "redirect_uris": sorted(client.redirect_uris),
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": " ".join(sorted(client.allowed_scopes)),
        }

    async def session_secret(self) -> str:
        """Derive a durable cookie-signing secret from the gateway signing key."""
        key = await self.store.get_signing_key()
        if key is None:
            raise RuntimeError("Authentication gateway is not initialized")
        return digest(key.private_key_pem.decode())

    async def _validated_client_request(
        self, *, client_id: str, redirect_uri: str, scope: str, nonce: str, code_challenge: str
    ) -> frozenset[str]:
        client = await self.store.get_client(client_id)
        requested_scopes = frozenset(scope.split())
        if (
            client is None
            or redirect_uri not in client.redirect_uris
            or "openid" not in requested_scopes
            or not requested_scopes.issubset(client.allowed_scopes)
            or not nonce
            or not PKCE_VALUE.fullmatch(code_challenge)
        ):
            raise ValueError("Invalid authorization request")
        return requested_scopes
