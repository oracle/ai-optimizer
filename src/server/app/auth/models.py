"""Provider-neutral authentication domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class PrincipalRecord:
    """A durable AI Optimizer user, independent from any login provider."""

    principal_id: str
    display_name: str
    email: str | None
    active: bool
    roles: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """Validated identity returned by a selected authentication source."""

    issuer: str
    subject: str
    display_name: str
    email: str | None = None
    roles: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class LocalAccount:
    """Password credential for one locally managed principal."""

    principal_id: str
    username: str
    password_hash: str


@dataclass(frozen=True, slots=True)
class AuthClient:
    """Registered downstream OpenID Connect client."""

    client_id: str
    redirect_uris: frozenset[str]
    allowed_scopes: frozenset[str]
    public: bool = True


@dataclass(slots=True)
class AuthorizationCode:
    """Single-use, PKCE-bound downstream authorization code."""

    digest: str
    client_id: str
    principal_id: str
    redirect_uri: str
    scope: str
    nonce: str
    code_challenge: str
    expires_at: datetime
    used: bool = False


@dataclass(frozen=True, slots=True)
class LoginSession:
    """Opaque browser session for the embedded gateway."""

    digest: str
    principal_id: str
    expires_at: datetime
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class AccessToken:
    """Digest-backed API credential issued by the embedded gateway."""

    digest: str
    principal_id: str
    client_id: str
    scope: str
    expires_at: datetime
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class LoginTransaction:
    """Durable state for one upstream provider authorization redirect."""

    state: str
    downstream_state: str
    client_id: str
    redirect_uri: str
    scope: str
    nonce: str
    code_challenge: str
    upstream_nonce: str
    upstream_verifier: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SigningKey:
    """Private signing key retained by the gateway and published through JWKS."""

    key_id: str
    private_key_pem: bytes


AuthenticationMethod = Literal["gateway", "proxy", "api_key"]


@dataclass
class InMemoryAuthStore:
    """Test store implementing the durable authentication store contract."""

    principals: dict[str, PrincipalRecord] = field(default_factory=dict)
    identities: dict[tuple[str, str], str] = field(default_factory=dict)
    local_accounts: dict[str, LocalAccount] = field(default_factory=dict)
    accounts_by_username: dict[str, str] = field(default_factory=dict)
    clients: dict[str, AuthClient] = field(default_factory=dict)
    codes: dict[str, AuthorizationCode] = field(default_factory=dict)
    sessions: dict[str, LoginSession] = field(default_factory=dict)
    access_tokens: dict[str, AccessToken] = field(default_factory=dict)
    transactions: dict[str, LoginTransaction] = field(default_factory=dict)
    signing_key: SigningKey | None = None
    source_roles: dict[str, set[tuple[str, str]]] = field(default_factory=dict)

    async def resolve_identity(self, identity: AuthenticatedIdentity, source: str) -> PrincipalRecord:
        principal_id = self.identities.get((identity.issuer, identity.subject))
        if principal_id is None:
            principal_id = str(uuid4())
            self.identities[(identity.issuer, identity.subject)] = principal_id
            active = True
        else:
            active = self.principals[principal_id].active
        source_roles = self.source_roles.setdefault(principal_id, set())
        source_roles.difference_update(
            {(role_source, role) for role_source, role in source_roles if role_source == source}
        )
        source_roles.update((source, role) for role in identity.roles)
        record = PrincipalRecord(
            principal_id,
            identity.display_name,
            identity.email,
            active,
            frozenset(role for _, role in source_roles),
        )
        self.principals[principal_id] = record
        return record

    async def get_principal(self, principal_id: str) -> PrincipalRecord | None:
        return self.principals.get(principal_id)

    async def list_principals(self) -> list[PrincipalRecord]:
        return sorted(self.principals.values(), key=lambda principal: principal.display_name.casefold())

    async def set_principal_active(self, principal_id: str, active: bool) -> None:
        principal = self.principals.get(principal_id)
        if principal is not None:
            self.principals[principal_id] = PrincipalRecord(
                principal.principal_id, principal.display_name, principal.email, active, principal.roles
            )

    async def set_role(self, principal_id: str, role: str, source: str, enabled: bool) -> None:
        principal = self.principals.get(principal_id)
        if principal is None:
            return
        source_roles = self.source_roles.setdefault(principal_id, set())
        if enabled:
            source_roles.add((source, role))
        else:
            source_roles.discard((source, role))
        self.principals[principal_id] = PrincipalRecord(
            principal.principal_id,
            principal.display_name,
            principal.email,
            principal.active,
            frozenset(item_role for _, item_role in source_roles),
        )

    async def get_local_account(self, username: str) -> LocalAccount | None:
        principal_id = self.accounts_by_username.get(username)
        return self.local_accounts.get(principal_id) if principal_id else None

    async def save_local_account(self, account: LocalAccount) -> None:
        prior = self.local_accounts.get(account.principal_id)
        if prior is not None and prior.username != account.username:
            self.accounts_by_username.pop(prior.username, None)
        existing = self.accounts_by_username.get(account.username)
        if existing is not None and existing != account.principal_id:
            raise ValueError("A user with that username already exists")
        self.local_accounts[account.principal_id] = account
        self.accounts_by_username[account.username] = account.principal_id

    async def save_client(self, client: AuthClient) -> None:
        self.clients[client.client_id] = client

    async def get_client(self, client_id: str) -> AuthClient | None:
        return self.clients.get(client_id)

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
        self.sessions[session.digest] = session

    async def get_login_session(self, digest: str) -> LoginSession | None:
        session = self.sessions.get(digest)
        return session if session is not None and session.expires_at > datetime.now(UTC) else None

    async def revoke_login_session(self, digest: str) -> None:
        session = self.sessions.get(digest)
        if session is not None:
            self.sessions[digest] = LoginSession(session.digest, session.principal_id, session.expires_at, True)

    async def save_access_token(self, token: AccessToken) -> None:
        self.access_tokens[token.digest] = token

    async def get_access_token(self, digest: str) -> AccessToken | None:
        token = self.access_tokens.get(digest)
        return token if token is not None and token.expires_at > datetime.now(UTC) else None

    async def revoke_access_tokens(self, principal_id: str) -> None:
        for digest, token in tuple(self.access_tokens.items()):
            if token.principal_id == principal_id:
                self.access_tokens[digest] = AccessToken(
                    token.digest, token.principal_id, token.client_id, token.scope, token.expires_at, True
                )

    async def save_transaction(self, transaction: LoginTransaction) -> None:
        self.transactions[transaction.state] = transaction

    async def consume_transaction(self, state: str) -> LoginTransaction | None:
        transaction = self.transactions.pop(state, None)
        return transaction if transaction is not None and transaction.expires_at > datetime.now(UTC) else None

    async def get_signing_key(self) -> SigningKey | None:
        return self.signing_key

    async def save_signing_key(self, key: SigningKey) -> None:
        if self.signing_key is None:
            self.signing_key = key
