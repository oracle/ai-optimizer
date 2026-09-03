"""Built-in development OpenID Connect provider primitives.

The provider deliberately exposes only the Authorization Code + PKCE
surface required by the platform. Persistence is supplied by a store so the
protocol rules do not depend on a request-local or transport-local identity.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

import jwt
import oracledb
from authlib.common.security import generate_token
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from server.app.database.config import get_core_pool
from server.app.database.sql import execute_sql

DEFAULT_ISSUER = "http://127.0.0.1:8765"
API_AUDIENCE = "aio-api"
WEB_CLIENT_ID = "platform-web-client"
MCP_CLIENT_METADATA_PATH = "/mcp-client-metadata.json"
DEFAULT_WEB_CLIENT_REDIRECT_URI = "http://localhost:8501/oauth2callback"
STANDARD_SCOPES = frozenset({"openid", "profile", "email"})
API_SCOPES = frozenset({"aio.api", "aio.admin"})
SUPPORTED_SCOPES = STANDARD_SCOPES | API_SCOPES
_CODE_LIFETIME = timedelta(minutes=5)
_LOGIN_SESSION_LIFETIME = timedelta(hours=8)
_TOKEN_LIFETIME = timedelta(minutes=15)
_PASSWORD_N = 2**14
_PASSWORD_R = 8
_PASSWORD_P = 1
_PKCE_VALUE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


@dataclass(frozen=True, slots=True)
class DevelopmentUser:
    """Durable local identity used to derive the OIDC subject."""

    user_id: str
    username: str
    email: str
    display_name: str
    password_hash: str
    scopes: frozenset[str]
    active: bool = True


@dataclass(frozen=True, slots=True)
class DevelopmentClient:
    """A first-party OIDC client with fixed redirect URIs and scopes."""

    client_id: str
    redirect_uris: frozenset[str]
    allowed_scopes: frozenset[str]
    public: bool = True


@dataclass(slots=True)
class AuthorizationCode:
    """Short-lived, single-use authorization-code grant."""

    digest: str
    client_id: str
    user_id: str
    redirect_uri: str
    scope: str
    nonce: str
    code_challenge: str
    expires_at: datetime
    used: bool = False


@dataclass(frozen=True, slots=True)
class LoginSession:
    """Durable browser-login session referenced by an opaque cookie value."""

    digest: str
    user_id: str
    expires_at: datetime
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class SigningKey:
    """The private signing key and public JWKS key identifier."""

    key_id: str
    private_key_pem: bytes


def _decode_json_array(value: str | list[object]) -> list[str]:
    """Normalize Oracle JSON values returned as text or native Python lists."""
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise ValueError("Expected a JSON array of strings")
    return [item for item in decoded if isinstance(item, str)]


class DevelopmentOidcStore(Protocol):
    """Persistence contract for development identities and grants."""

    async def get_user_by_username(self, username: str) -> DevelopmentUser | None: ...

    async def get_user_by_id(self, user_id: str) -> DevelopmentUser | None: ...

    async def save_user(self, user: DevelopmentUser) -> None: ...

    async def get_client(self, client_id: str) -> DevelopmentClient | None: ...

    async def save_client(self, client: DevelopmentClient) -> None: ...

    async def get_signing_key(self) -> SigningKey | None: ...

    async def save_signing_key(self, key: SigningKey) -> None: ...

    async def save_code(self, code: AuthorizationCode) -> None: ...

    async def get_code(self, digest: str) -> AuthorizationCode | None: ...

    async def mark_code_used(self, digest: str) -> bool: ...

    async def save_login_session(self, session: LoginSession) -> None: ...

    async def get_login_session(self, digest: str) -> LoginSession | None: ...

    async def revoke_login_session(self, digest: str) -> None: ...


@dataclass
class InMemoryDevelopmentOidcStore:
    """Test-only store; development runtime uses Oracle-backed storage."""

    users: dict[str, DevelopmentUser] = field(default_factory=dict)
    clients: dict[str, DevelopmentClient] = field(default_factory=dict)
    codes: dict[str, AuthorizationCode] = field(default_factory=dict)
    login_sessions: dict[str, LoginSession] = field(default_factory=dict)
    signing_key: SigningKey | None = None

    async def get_user_by_username(self, username: str) -> DevelopmentUser | None:
        return next((user for user in self.users.values() if user.username == username), None)

    async def get_user_by_id(self, user_id: str) -> DevelopmentUser | None:
        return self.users.get(user_id)

    async def save_user(self, user: DevelopmentUser) -> None:
        self.users[user.user_id] = user

    async def get_client(self, client_id: str) -> DevelopmentClient | None:
        return self.clients.get(client_id)

    async def save_client(self, client: DevelopmentClient) -> None:
        self.clients[client.client_id] = client

    async def get_signing_key(self) -> SigningKey | None:
        return self.signing_key

    async def save_signing_key(self, key: SigningKey) -> None:
        self.signing_key = key

    async def save_code(self, code: AuthorizationCode) -> None:
        self.codes[code.digest] = code

    async def get_code(self, digest: str) -> AuthorizationCode | None:
        return self.codes.get(digest)

    async def mark_code_used(self, digest: str) -> bool:
        code = self.codes.get(digest)
        if code is None or code.used or code.expires_at <= datetime.now(UTC):
            return False
        code.used = True
        return True

    async def save_login_session(self, session: LoginSession) -> None:
        self.login_sessions[session.digest] = session

    async def get_login_session(self, digest: str) -> LoginSession | None:
        session = self.login_sessions.get(digest)
        if session is None or session.expires_at <= datetime.now(UTC):
            return None
        return session

    async def revoke_login_session(self, digest: str) -> None:
        session = self.login_sessions.get(digest)
        if session is not None:
            self.login_sessions[digest] = LoginSession(
                digest=session.digest,
                user_id=session.user_id,
                expires_at=session.expires_at,
                revoked=True,
            )


class OracleDevelopmentOidcStore:
    """Oracle-backed store used whenever the built-in provider is active."""

    @staticmethod
    def _pool():
        pool = get_core_pool()
        if pool is None:
            raise RuntimeError("Development OIDC requires an available CORE database")
        return pool

    async def get_user_by_username(self, username: str) -> DevelopmentUser | None:
        return await self._get_user("username", username)

    async def get_user_by_id(self, user_id: str) -> DevelopmentUser | None:
        return await self._get_user("user_id", user_id)

    async def _get_user(self, column: str, value: str) -> DevelopmentUser | None:
        rows = await self._query(
            f"""
            SELECT user_id, username, email, display_name, password_hash, scopes, active
              FROM aio_dev_oidc_users
             WHERE {column} = :value
            """,
            {"value": value},
        )
        if not rows:
            return None
        user_id, username, email, display_name, password_hash, scopes, active = rows[0]
        return DevelopmentUser(
            user_id=user_id,
            username=username,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            scopes=frozenset(_decode_json_array(scopes)),
            active=bool(active),
        )

    async def save_user(self, user: DevelopmentUser) -> None:
        await self._execute(
            """
            MERGE INTO aio_dev_oidc_users target
            USING (SELECT :user_id AS user_id FROM dual) source
               ON (target.user_id = source.user_id)
            WHEN MATCHED THEN UPDATE SET
                username = :username, email = :email, display_name = :display_name,
                password_hash = :password_hash, scopes = :scopes, active = :active,
                updated = SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT
                (user_id, username, email, display_name, password_hash, scopes, active, created, updated)
                VALUES (:user_id, :username, :email, :display_name, :password_hash, :scopes, :active,
                        SYSTIMESTAMP, SYSTIMESTAMP)
            """,
            {
                "user_id": user.user_id,
                "username": user.username,
                "email": user.email,
                "display_name": user.display_name,
                "password_hash": user.password_hash,
                "scopes": json.dumps(sorted(user.scopes)),
                "active": user.active,
            },
        )

    async def get_client(self, client_id: str) -> DevelopmentClient | None:
        rows = await self._query(
            """
            SELECT client_id, redirect_uris, allowed_scopes, is_public
              FROM aio_dev_oidc_clients
             WHERE client_id = :client_id
            """,
            {"client_id": client_id},
        )
        if not rows:
            return None
        client_id, redirect_uris, scopes, is_public = rows[0]
        return DevelopmentClient(
            client_id=client_id,
            redirect_uris=frozenset(_decode_json_array(redirect_uris)),
            allowed_scopes=frozenset(_decode_json_array(scopes)),
            public=bool(is_public),
        )

    async def save_client(self, client: DevelopmentClient) -> None:
        await self._execute(
            """
            MERGE INTO aio_dev_oidc_clients target
            USING (SELECT :client_id AS client_id FROM dual) source
               ON (target.client_id = source.client_id)
            WHEN MATCHED THEN UPDATE SET
                redirect_uris = :redirect_uris, allowed_scopes = :allowed_scopes, is_public = :is_public,
                updated = SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT
                (client_id, redirect_uris, allowed_scopes, is_public, created, updated)
                VALUES (:client_id, :redirect_uris, :allowed_scopes, :is_public, SYSTIMESTAMP, SYSTIMESTAMP)
            """,
            {
                "client_id": client.client_id,
                "redirect_uris": json.dumps(sorted(client.redirect_uris)),
                "allowed_scopes": json.dumps(sorted(client.allowed_scopes)),
                "is_public": client.public,
            },
        )

    async def get_signing_key(self) -> SigningKey | None:
        rows = await self._query(
            "SELECT key_id, private_key_pem FROM aio_dev_oidc_signing_keys WHERE active = TRUE ORDER BY created",
        )
        if not rows:
            return None
        key_id, private_key_pem = rows[0]
        return SigningKey(key_id=key_id, private_key_pem=private_key_pem.encode())

    async def save_signing_key(self, key: SigningKey) -> None:
        """Store the initial signing key while serializing concurrent startup replicas."""
        pool = self._pool()
        async with pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute("LOCK TABLE aio_dev_oidc_signing_keys IN EXCLUSIVE MODE")
            rows = await execute_sql(
                conn,
                "SELECT key_id FROM aio_dev_oidc_signing_keys WHERE active = TRUE",
            )
            if not rows:
                await execute_sql(
                    conn,
                    """
                    INSERT INTO aio_dev_oidc_signing_keys (key_id, private_key_pem, active, created)
                    VALUES (:key_id, :private_key_pem, TRUE, SYSTIMESTAMP)
                    """,
                    {"key_id": key.key_id, "private_key_pem": key.private_key_pem.decode()},
                )
            await conn.commit()

    async def save_code(self, code: AuthorizationCode) -> None:
        await self._execute(
            """
            INSERT INTO aio_dev_oidc_codes
                (code_digest, client_id, user_id, redirect_uri, scope, nonce, code_challenge, expires_at, used, created)
            VALUES
                (:digest, :client_id, :user_id, :redirect_uri, :scope, :nonce, :code_challenge,
                 SYSTIMESTAMP + NUMTODSINTERVAL(:expires_in_seconds, 'SECOND'), FALSE, SYSTIMESTAMP)
            """,
            {
                "digest": code.digest,
                "client_id": code.client_id,
                "user_id": code.user_id,
                "redirect_uri": code.redirect_uri,
                "scope": code.scope,
                "nonce": code.nonce,
                "code_challenge": code.code_challenge,
                "expires_in_seconds": int(_CODE_LIFETIME.total_seconds()),
            },
        )

    async def get_code(self, digest: str) -> AuthorizationCode | None:
        rows = await self._query(
            """
            SELECT code_digest, client_id, user_id, redirect_uri, scope, nonce, code_challenge, expires_at, used
              FROM aio_dev_oidc_codes
             WHERE code_digest = :digest
            """,
            {"digest": digest},
        )
        if not rows:
            return None
        return AuthorizationCode(*rows[0])

    async def mark_code_used(self, digest: str) -> bool:
        pool = self._pool()
        async with pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(
                """
                UPDATE aio_dev_oidc_codes
                   SET used = TRUE
                 WHERE code_digest = :digest
                   AND used = FALSE
                   AND expires_at > SYSTIMESTAMP
                """,
                {"digest": digest},
            )
            changed = cursor.rowcount == 1
            await conn.commit()
        return changed

    async def save_login_session(self, session: LoginSession) -> None:
        await self._execute(
            """
            INSERT INTO aio_dev_oidc_sessions (session_digest, user_id, expires_at, revoked, created)
            VALUES (:digest, :user_id, SYSTIMESTAMP + NUMTODSINTERVAL(:expires_in_seconds, 'SECOND'), FALSE,
                    SYSTIMESTAMP)
            """,
            {
                "digest": session.digest,
                "user_id": session.user_id,
                "expires_in_seconds": int(_LOGIN_SESSION_LIFETIME.total_seconds()),
            },
        )

    async def get_login_session(self, digest: str) -> LoginSession | None:
        rows = await self._query(
            """
            SELECT session_digest, user_id, expires_at, revoked
              FROM aio_dev_oidc_sessions
             WHERE session_digest = :digest
               AND expires_at > SYSTIMESTAMP
            """,
            {"digest": digest},
        )
        if not rows:
            return None
        return LoginSession(*rows[0])

    async def revoke_login_session(self, digest: str) -> None:
        await self._execute(
            "UPDATE aio_dev_oidc_sessions SET revoked = TRUE WHERE session_digest = :digest",
            {"digest": digest},
        )

    async def _query(self, sql: str, binds: dict | None = None) -> list:
        pool = self._pool()
        async with pool.acquire() as conn:
            return await execute_sql(conn, sql, binds) or []

    async def _execute(self, sql: str, binds: dict | None = None) -> None:
        pool = self._pool()
        async with pool.acquire() as conn:
            await execute_sql(conn, sql, binds)
            await conn.commit()


class DevelopmentOidcService:
    """Authorization Code + PKCE OIDC service for the built-in provider."""

    def __init__(
        self,
        issuer: str,
        store: DevelopmentOidcStore,
        seed_passwords: dict[str, str],
        web_client_secret: str = "",
        web_client_redirect_uri: str = DEFAULT_WEB_CLIENT_REDIRECT_URI,
    ):
        self.issuer = issuer.rstrip("/")
        self.store = store
        self.seed_passwords = seed_passwords
        self.web_client_secret = web_client_secret
        self.web_client_redirect_uri = web_client_redirect_uri

    @property
    def mcp_client_id(self) -> str:
        """Stable URL client identifier for the fixed MCP metadata document."""
        return f"{self.issuer}{MCP_CLIENT_METADATA_PATH}"

    async def initialize(self) -> None:
        """Provision the administrator, first-party clients, and a signing key."""
        await self._seed_user("admin@example.test", "ADMIN", {"aio.admin"})
        await self._seed_client(
            DevelopmentClient(
                client_id=WEB_CLIENT_ID,
                redirect_uris=frozenset({self.web_client_redirect_uri}),
                allowed_scopes=SUPPORTED_SCOPES,
            )
        )
        await self._seed_client(
            DevelopmentClient(
                client_id=self.mcp_client_id,
                redirect_uris=frozenset({"http://127.0.0.1:8766/callback"}),
                allowed_scopes=SUPPORTED_SCOPES,
            )
        )
        if await self.store.get_signing_key() is None:
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            pem = private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            await self.store.save_signing_key(SigningKey(key_id=f"dev-{uuid.uuid4().hex}", private_key_pem=pem))

    async def _seed_user(self, email: str, display_name: str, elevated_scopes: set[str]) -> None:
        existing = await self.store.get_user_by_username(email)
        if existing is not None:
            await self.store.save_user(
                DevelopmentUser(
                    user_id=existing.user_id,
                    username=existing.username,
                    email=existing.email,
                    display_name=existing.display_name,
                    password_hash=_hash_password(self.seed_passwords[email]),
                    scopes=existing.scopes,
                    active=existing.active,
                )
            )
            return
        password = self.seed_passwords[email]
        user = DevelopmentUser(
            user_id=str(uuid.uuid4()),
            username=email,
            email=email,
            display_name=display_name,
            password_hash=_hash_password(password),
            scopes=frozenset(STANDARD_SCOPES | {"aio.api"} | elevated_scopes),
        )
        try:
            await self.store.save_user(user)
        except oracledb.IntegrityError:
            if await self.store.get_user_by_username(email) is None:
                raise

    async def _seed_client(self, client: DevelopmentClient) -> None:
        """Persist a fixed client, tolerating the winner of a concurrent startup."""
        try:
            await self.store.save_client(client)
        except oracledb.IntegrityError:
            if await self.store.get_client(client.client_id) is None:
                raise

    async def authenticate(self, username: str, password: str) -> DevelopmentUser | None:
        """Authenticate a local user without exposing password-hash details."""
        user = await self.store.get_user_by_username(username)
        if user is None or not user.active or not _verify_password(password, user.password_hash):
            return None
        return user

    async def provision_user(
        self,
        *,
        username: str,
        email: str,
        display_name: str,
        password: str,
        administrator: bool = False,
    ) -> None:
        """Create one explicitly requested development identity."""
        if not username or not email or not display_name or not password:
            raise ValueError("Username, email, display name, and password are required")
        if await self.store.get_user_by_username(username) is not None:
            raise ValueError("A user with that username already exists")
        scopes = set(STANDARD_SCOPES | {"aio.api"})
        if administrator:
            scopes.add("aio.admin")
        await self.store.save_user(
            DevelopmentUser(
                user_id=str(uuid.uuid4()),
                username=username,
                email=email,
                display_name=display_name,
                password_hash=_hash_password(password),
                scopes=frozenset(scopes),
            )
        )

    async def create_login_session(self, user: DevelopmentUser) -> str:
        """Persist a browser-login session and return its opaque cookie value."""
        raw_session_id = generate_token(48)
        await self.store.save_login_session(
            LoginSession(
                digest=_digest(raw_session_id),
                user_id=user.user_id,
                expires_at=datetime.now(UTC) + _LOGIN_SESSION_LIFETIME,
            )
        )
        return raw_session_id

    async def get_login_session_user(self, raw_session_id: str) -> DevelopmentUser | None:
        """Resolve a non-expired, non-revoked browser session to its user."""
        session = await self.store.get_login_session(_digest(raw_session_id))
        if session is None or session.revoked:
            return None
        user = await self.store.get_user_by_id(session.user_id)
        return user if user is not None and user.active else None

    async def revoke_login_session(self, raw_session_id: str) -> None:
        """Invalidate the durable session referenced by a browser cookie."""
        await self.store.revoke_login_session(_digest(raw_session_id))

    async def create_authorization_code(
        self,
        *,
        username: str,
        client_id: str,
        redirect_uri: str,
        scope: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        """Create a PKCE-bound, single-use code for an authenticated user."""
        user = await self.store.get_user_by_username(username)
        client = await self.store.get_client(client_id)
        requested_scopes = _validate_scope(scope)
        if user is None or not user.active:
            raise ValueError("Unknown user")
        if client is None or redirect_uri not in client.redirect_uris:
            raise ValueError("Invalid client or redirect URI")
        if not requested_scopes.issubset(client.allowed_scopes & user.scopes):
            raise ValueError("Invalid scope")
        if not nonce:
            raise ValueError("Missing nonce")
        if not _PKCE_VALUE.fullmatch(code_challenge):
            raise ValueError("Invalid PKCE code challenge")
        raw_code = generate_token(48)
        digest = _digest(raw_code)
        await self.store.save_code(
            AuthorizationCode(
                digest=digest,
                client_id=client_id,
                user_id=user.user_id,
                redirect_uri=redirect_uri,
                scope=" ".join(sorted(requested_scopes)),
                nonce=nonce,
                code_challenge=code_challenge,
                expires_at=datetime.now(UTC) + _CODE_LIFETIME,
            )
        )
        return raw_code

    async def exchange_code(
        self, *, client_id: str, client_secret: str = "", code: str, redirect_uri: str, code_verifier: str
    ) -> dict[str, str | int]:
        """Exchange a valid PKCE authorization code for OIDC and API tokens."""
        if not _PKCE_VALUE.fullmatch(code_verifier):
            raise ValueError("Invalid PKCE verifier")
        digest = _digest(code)
        authorization_code = await self.store.get_code(digest)
        if authorization_code is None:
            raise ValueError("Invalid authorization code: not found")
        if authorization_code.used:
            raise ValueError("Invalid authorization code: already used")
        if authorization_code.client_id != client_id or authorization_code.redirect_uri != redirect_uri:
            raise ValueError("Invalid authorization code: client or redirect URI mismatch")
        if client_id == WEB_CLIENT_ID and not hmac.compare_digest(client_secret, self.web_client_secret):
            raise ValueError("Invalid client credentials")
        if not hmac.compare_digest(_pkce_challenge(code_verifier), authorization_code.code_challenge):
            raise ValueError("Invalid PKCE verifier")
        if not await self.store.mark_code_used(digest):
            raise ValueError("Invalid authorization code: already used or expired")
        client = await self.store.get_client(client_id)
        user = await self.store.get_user_by_id(authorization_code.user_id)
        key = await self.store.get_signing_key()
        if client is None or user is None or key is None:
            raise ValueError("Development provider is not initialized")
        return _issue_tokens(
            issuer=self.issuer,
            client_id=client.client_id,
            user=user,
            scope=authorization_code.scope,
            nonce=authorization_code.nonce,
            signing_key=key,
        )

    async def discovery_document(self) -> dict[str, object]:
        """Return the provider metadata for standards-based discovery."""
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "end_session_endpoint": f"{self.issuer}/logout",
            "userinfo_endpoint": f"{self.issuer}/userinfo",
            "jwks_uri": f"{self.issuer}/jwks.json",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile", "email", "aio.api", "aio.admin"],
            "code_challenge_methods_supported": ["S256"],
        }

    async def mcp_client_metadata_document(self) -> dict[str, object]:
        """Publish fixed first-party MCP client metadata for CIMD clients."""
        client = await self.store.get_client(self.mcp_client_id)
        if client is None:
            raise ValueError("Development provider is not initialized")
        return {
            "client_id": client.client_id,
            "redirect_uris": sorted(client.redirect_uris),
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": " ".join(sorted(client.allowed_scopes)),
        }

    async def jwks_document(self) -> dict[str, list[dict[str, object]]]:
        """Publish the public key matching issued JWTs."""
        key = await self.store.get_signing_key()
        if key is None:
            raise ValueError("Development provider is not initialized")
        private_key = _load_rsa_private_key(key.private_key_pem)
        public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
        public_jwk.update({"kid": key.key_id, "use": "sig", "alg": "RS256"})
        return {"keys": [public_jwk]}

    async def session_secret(self) -> str:
        """Derive a durable session-cookie signing secret from the persisted key."""
        key = await self.store.get_signing_key()
        if key is None:
            raise ValueError("Development provider is not initialized")
        return _digest(key.private_key_pem.decode())

    async def user_info(self, access_token: str) -> dict[str, object]:
        """Validate an API access token and return standard UserInfo claims."""
        key = await self.store.get_signing_key()
        if key is None:
            raise ValueError("Development provider is not initialized")
        if jwt.get_unverified_header(access_token).get("typ") != "at+jwt":
            raise ValueError("Access token required")
        private_key = _load_rsa_private_key(key.private_key_pem)
        claims = jwt.decode(
            access_token,
            private_key.public_key(),
            algorithms=["RS256"],
            audience=API_AUDIENCE,
            issuer=self.issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
        user = await self.store.get_user_by_id(claims["sub"])
        if user is None or not user.active:
            raise ValueError("Unknown user")
        return {
            "sub": user.user_id,
            "name": user.display_name,
            "preferred_username": user.username,
            "email": user.email,
            "email_verified": True,
        }


def _issue_tokens(
    *, issuer: str, client_id: str, user: DevelopmentUser, scope: str, nonce: str, signing_key: SigningKey
) -> dict[str, str | int]:
    now = int(time.time())
    expires_at = now + int(_TOKEN_LIFETIME.total_seconds())
    private_key = _load_rsa_private_key(signing_key.private_key_pem)
    headers = {"kid": signing_key.key_id}
    base_claims = {"iss": issuer, "sub": user.user_id, "iat": now, "exp": expires_at}
    access_token = jwt.encode(
        {
            **base_claims,
            "aud": API_AUDIENCE,
            "scope": scope,
            "roles": sorted(user.scopes.intersection({"aio.admin"})),
            "client_id": client_id,
            "jti": uuid.uuid4().hex,
        },
        private_key,
        algorithm="RS256",
        headers={**headers, "typ": "at+jwt"},
    )
    id_token = jwt.encode(
        {
            **base_claims,
            "aud": client_id,
            "nonce": nonce,
            "name": user.display_name,
            "preferred_username": user.username,
            "email": user.email,
            "email_verified": True,
        },
        private_key,
        algorithm="RS256",
        headers=headers,
    )
    return {
        "access_token": access_token,
        "id_token": id_token,
        "token_type": "Bearer",
        "expires_in": int(_TOKEN_LIFETIME.total_seconds()),
        "scope": scope,
    }


def _validate_scope(scope: str) -> frozenset[str]:
    values = frozenset(scope.split())
    if "openid" not in values or not values.issubset(SUPPORTED_SCOPES):
        raise ValueError("Invalid scope")
    return values


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _load_rsa_private_key(private_key_pem: bytes) -> rsa.RSAPrivateKey:
    """Load persisted key material and reject anything other than the configured RSA key."""
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ValueError("Development provider signing key is not RSA")
    return private_key


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _hash_password(password: str) -> str:
    salt = generate_token(24).encode()
    derived = hashlib.scrypt(password.encode(), salt=salt, n=_PASSWORD_N, r=_PASSWORD_R, p=_PASSWORD_P)
    return "$".join(
        [
            "scrypt",
            str(_PASSWORD_N),
            str(_PASSWORD_R),
            str(_PASSWORD_P),
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(derived).decode(),
        ]
    )


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode(),
            salt=base64.urlsafe_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
        )
        return hmac.compare_digest(derived, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False
