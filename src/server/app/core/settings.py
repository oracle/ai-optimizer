"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Application settings loaded from environment variables and .env file.
"""
# spell-checker: ignore genai

import asyncio
import json
import os
import secrets
import threading
from collections import OrderedDict
from typing import Annotated, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from server.app.core.paths import PROJECT_ROOT
from server.app.core.schemas import ClientSettings
from server.app.core.secrets import SecretField
from server.app.database.schemas import DatabaseConfig
from server.app.mcp.prompts.schemas import PromptConfig
from server.app.models.schemas import ModelConfig
from server.app.oci.schemas import OciProfileConfig


def _validate_issuer_url(issuer: str, *, require_root_path: bool = True) -> None:
    """Validate an absolute issuer and limit plaintext HTTP to loopback."""
    parsed = urlparse(issuer)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OIDC issuer must be an absolute HTTP(S) origin")
    if require_root_path and parsed.path not in {"", "/"}:
        raise ValueError("OIDC issuer must use its dedicated origin root path")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Plain HTTP OIDC issuers are allowed only on loopback")


class SettingsBase(BaseModel):
    """Fields shared between Settings and SettingsResponse."""

    env: str = "dev"
    server_url_prefix: str = ""

    @field_validator("server_url_prefix")
    @classmethod
    def _normalize_url_prefix(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not v.startswith("/"):
            v = f"/{v}"
        return v

    server_address: str = "0.0.0.0"
    server_port: int = 8000
    server_ssl: bool = False
    server_ssl_cert_file: str = ""
    server_ssl_key_file: str = ""
    log_level: str = "INFO"
    database_configs: list[DatabaseConfig] = []
    oci_configs: list[OciProfileConfig] = []
    model_configs: list[ModelConfig] = []
    prompt_configs: list[PromptConfig] = []
    client_settings: ClientSettings = ClientSettings()
    nl2sql_available: bool = False
    api_key: SecretField = Field(default=None, exclude=True)


class Settings(SettingsBase, BaseSettings):
    """Application settings populated from environment variables / .env file."""

    model_config = SettingsConfigDict(  # should be identical to client.app.core.settings
        env_prefix="AIO_",
        env_file=PROJECT_ROOT / f".env.{os.getenv('AIO_ENV', 'dev')}",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database — flat fields loaded from AIO_DB_* env vars (excluded from serialization)
    db_username: Optional[str] = Field(default=None, exclude=True)
    db_password: Optional[SecretStr] = Field(default=None, exclude=True)
    db_dsn: Optional[str] = Field(default=None, exclude=True)
    db_wallet_password: Optional[SecretStr] = Field(default=None, exclude=True)
    db_wallet_location: Optional[str] = Field(default=None, exclude=True)
    db_pool_size: int = Field(default=5, exclude=True)

    max_clients: int = Field(default=64, ge=1, exclude=True)

    # Principal authentication. A deployment selects OIDC bearer validation or
    # a trusted identity-proxy adapter.
    auth_mode: Literal["dev", "oidc", "proxy"] | None = Field(default=None, exclude=True)
    auth_oidc_issuer: str = Field(default="", exclude=True)
    auth_oidc_audience: str = Field(default="", exclude=True)
    auth_oidc_client_id: str = Field(default="", exclude=True)
    auth_oidc_client_secret: Optional[SecretStr] = Field(default=None, exclude=True)
    auth_oidc_scopes: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["openid", "profile", "email", "aio.api"], exclude=True
    )
    auth_oidc_required_scopes: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["aio.api"], exclude=True)
    auth_oidc_roles_claim: str = Field(default="roles", exclude=True)
    auth_dev_issuer: str = Field(default="http://127.0.0.1:8765", exclude=True)
    auth_dev_web_redirect_uri: str = Field(default="http://localhost:8501/oauth2callback", exclude=True)
    auth_dev_listen_host: str = Field(default="127.0.0.1", exclude=True)
    auth_dev_listen_port: int = Field(default=8765, ge=1, le=65535, exclude=True)
    auth_dev_admin_password: Optional[SecretStr] = Field(default=None, exclude=True)
    auth_dev_web_client_secret: Optional[SecretStr] = Field(default=None, exclude=True)
    # Retained solely to reject the retired AIO_CLIENT_PASSWORD setting with a
    # useful migration error instead of silently accepting a no-longer-effective
    # shared-state control.
    client_password: Optional[SecretStr] = Field(default=None, exclude=True)
    auth_proxy_trusted_cidrs: Annotated[list[str], NoDecode] = Field(default_factory=list, exclude=True)
    auth_proxy_subject_header: str = Field(default="X-Authenticated-Subject", exclude=True)
    auth_proxy_roles_header: str = Field(default="X-Authenticated-Roles", exclude=True)
    auth_proxy_issuer: str = Field(default="trusted-proxy", exclude=True)
    auth_admin_claim_values: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["aio.admin"], exclude=True)

    @field_validator(
        "auth_proxy_trusted_cidrs",
        "auth_admin_claim_values",
        "auth_oidc_scopes",
        "auth_oidc_required_scopes",
        mode="before",
    )
    @classmethod
    def _parse_auth_list(cls, value):
        """Accept normal comma-separated environment values as well as JSON lists."""
        if isinstance(value, str):
            if value.lstrip().startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    # OCI CLI — applied to DEFAULT profile at startup (excluded from serialization)
    oci_cli_auth: Optional[str] = Field(default=None, exclude=True)
    oci_cli_tenancy: Optional[str] = Field(default=None, exclude=True)
    oci_cli_region: Optional[str] = Field(default=None, exclude=True)
    oci_cli_user: Optional[str] = Field(default=None, exclude=True)
    oci_cli_fingerprint: Optional[str] = Field(default=None, exclude=True)
    oci_cli_key_file: Optional[str] = Field(default=None, exclude=True)
    oci_cli_key_content: Optional[SecretStr] = Field(default=None, exclude=True)
    oci_cli_passphrase: Optional[SecretStr] = Field(default=None, exclude=True)
    oci_cli_security_token_file: Optional[str] = Field(default=None, exclude=True)
    genai_compartment_id: Optional[str] = Field(default=None, exclude=True)
    genai_region: Optional[str] = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _build_core_database_config(self) -> "Settings":
        """Create the CORE database config from DB_* / AIO_DB_* env vars.

        Precedence: DB_* env var > AIO_DB_* (.env / export).
        """
        username = os.environ.get("DB_USERNAME") or self.db_username
        # Env-var values arrive as ``str``; promote them to ``SecretStr`` so
        # the precedence ``or self.db_password`` produces a single SecretStr |
        # None type rather than a mixed str | SecretStr | None.
        db_password_env = os.environ.get("DB_PASSWORD")
        password: Optional[SecretStr] = SecretStr(db_password_env) if db_password_env else self.db_password
        dsn = os.environ.get("DB_DSN") or self.db_dsn
        wallet_password_env = os.environ.get("DB_WALLET_PASSWORD")
        wallet_password: Optional[SecretStr] = (
            SecretStr(wallet_password_env) if wallet_password_env else self.db_wallet_password
        )
        wallet_location = os.environ.get("DB_WALLET_LOCATION") or self.db_wallet_location

        if any([username, password, dsn]):
            core = DatabaseConfig(
                alias="CORE",
                username=username,
                password=password,
                dsn=dsn,
                wallet_password=wallet_password,
                wallet_location=wallet_location,
            )
            self.database_configs = [core]
        return self

    @model_validator(mode="after")
    def _generate_api_key_if_missing(self) -> "Settings":
        if self.api_key is None:
            object.__setattr__(self, "_api_key_generated", True)
            self.api_key = SecretStr(secrets.token_urlsafe(32))
        else:
            object.__setattr__(self, "_api_key_generated", False)
        return self

    @model_validator(mode="after")
    def _validate_authentication_posture(self) -> "Settings":
        """Reject development/production combinations that cannot be safe."""
        if self.client_password is not None:
            raise ValueError("AIO_CLIENT_PASSWORD is retired; use AIO_AUTH_DEV_ADMIN_PASSWORD in development mode")
        if self.auth_mode is None and any(cfg.alias == "CORE" for cfg in self.database_configs):
            self.auth_mode = "dev"
        if self.auth_mode == "dev" and not any(cfg.alias == "CORE" for cfg in self.database_configs):
            raise ValueError("AIO_AUTH_MODE=dev requires an Oracle CORE database")
        if self.auth_mode == "dev":
            _validate_issuer_url(self.auth_dev_issuer)
            if self.auth_dev_admin_password is None:
                self.auth_dev_admin_password = SecretStr(secrets.token_urlsafe(32))
            if self.auth_dev_web_client_secret is None:
                self.auth_dev_web_client_secret = SecretStr(secrets.token_urlsafe(32))
        if self.auth_mode == "oidc":
            _validate_issuer_url(self.auth_oidc_issuer, require_root_path=False)
        return self

    @property
    def api_key_generated(self) -> bool:
        """True when api_key was auto-generated (AIO_API_KEY not set)."""
        return getattr(self, "_api_key_generated", False)


settings = Settings()

# ---------------------------------------------------------------------------
# Per-client settings store
# ---------------------------------------------------------------------------
_PROTECTED_CLIENTS = frozenset(("CONFIGURED", "FACTORY", "server"))
_client_store: OrderedDict[str, ClientSettings] = OrderedDict()
_client_store_lock = threading.Lock()
_settings_lock = asyncio.Lock()


def _ensure_capacity() -> None:
    """Evict the least-recently-used entry (never protected clients) when the store is full."""
    while len(_client_store) >= settings.max_clients:
        for key in _client_store:
            if key not in _PROTECTED_CLIENTS:
                del _client_store[key]
                break
        else:
            break  # only protected clients remain — nothing to evict


def _apply_default_ll_model(cs: ClientSettings) -> None:
    """Set ll_model to the first enabled+available language model when unset."""
    if cs.ll_model.provider is not None or cs.ll_model.id is not None:
        return
    for cfg in settings.model_configs:
        if cfg.type == "ll" and cfg.enabled and cfg.status == "available":
            cs.ll_model.provider = cfg.provider
            cs.ll_model.id = cfg.id
            if cfg.max_input_tokens is not None:
                cs.ll_model.max_input_tokens = cfg.max_input_tokens
            if cfg.max_tokens is not None:
                cs.ll_model.max_tokens = cfg.max_tokens
            break


def resolve_client(client: str) -> ClientSettings:
    """Return the ClientSettings for a client, creating from defaults if needed.

    The ``"CONFIGURED"`` client always returns the global ``settings.client_settings``
    singleton so that startup-time mutations (e.g. OCI profile auto-detection) are
    visible to callers without an extra copy.  All other clients get an isolated
    fork cached in ``_client_store``.
    """
    if client == "CONFIGURED":
        return settings.client_settings
    with _client_store_lock:
        if client in _client_store:
            _client_store.move_to_end(client)
        else:
            _ensure_capacity()
            _client_store[client] = settings.client_settings.model_copy(deep=True)
            _client_store[client].client = client
            _apply_default_ll_model(_client_store[client])
        return _client_store[client]
