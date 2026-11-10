"""Validated authentication domain models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

AuthMode = Literal["single_user", "local_users", "oidc"]
AuthRole = Literal["admin", "member"]


class Principal(BaseModel):
    """Identity established by a configured credential authority."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    subject: str
    username: str
    display_name: str | None = None
    email: str | None = None
    auth_source: Literal["database_end_user", "oidc"]
    database_username: str | None = None
    roles: frozenset[AuthRole]
    scopes: frozenset[str] = frozenset()


class AuthUser(BaseModel):
    """Persistent application user."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    username: str
    auth_source: Literal["database_end_user", "oidc"]
    database_username: str | None = None
    issuer: str | None = None
    subject: str | None = None
    display_name: str | None = None
    email: str | None = None
    role: AuthRole
    status: Literal["active", "disabled"]
    created: datetime
    updated: datetime
    last_login: datetime | None = None


class AuthSession(BaseModel):
    """Persistent opaque application session metadata."""

    model_config = ConfigDict(frozen=True)

    session_id: UUID
    user_id: UUID
    token_digest: SecretStr = Field(repr=False)
    created: datetime
    expires: datetime
    last_seen: datetime
    revoked: datetime | None = None
    remote_address: str | None = None


class AuthAuthority(BaseModel):
    """Immutable deployment authentication authority."""

    model_config = ConfigDict(frozen=True)

    installation_id: str
    auth_mode: AuthMode
    schema_version: int
    database_identity: str
    application_schema: str
    admin_database_username: str
    oidc_issuer: str | None = None
    oidc_admin_subject: str | None = None
    initialized: datetime
    last_validated: datetime


@dataclass(frozen=True)
class RequestCredential:
    """Credential extracted from a request without establishing identity."""

    kind: Literal["bearer"]
    value: str = field(repr=False)


@dataclass(frozen=True)
class AuthContext:
    """Authenticated request identity and its internal workspace."""

    principal: Principal
    credential: RequestCredential
    workspace_key: str


@dataclass(frozen=True)
class IssuedSession:
    """A newly issued bearer credential and its public expiry metadata."""

    token: str = field(repr=False)
    expires: datetime


def workspace_key(user_id: UUID) -> str:
    """Return the server-owned workspace key for a user."""
    return f"user:{user_id}"
