"""Tests for the authentication foundation and configuration contract."""

from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from server.app.auth.models import Principal, RequestCredential, workspace_key
from server.app.auth.service import AUTHENTICATORS, authenticator_ready, request_auth_context
from server.app.auth.setup import (
    _core_wait_seconds,
    _ensure_connect_role,
    _ensure_login_data_role,
    _init_core_database_with_retry,
    _validate_local_auth_capabilities,
)
from server.app.core.settings import CoreDatabaseConfigurationError, Settings, validate_auth_configuration
from server.app.database.registry import CoreDatabaseInitializationError

pytestmark = pytest.mark.unit


def _settings(**overrides) -> Settings:
    values = {
        "auth_mode": "single_user",
        "installation_id": "test-installation",
        "admin_database_username": "APP_ADMIN",
        "db_username": "APP_SCHEMA",
        "db_password": SecretStr("schema-password"),
        "db_dsn": "localhost:1521/FREEPDB1",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_request_credential_repr_redacts_bearer_token():
    credential = RequestCredential(kind="bearer", value="sensitive-access-token")
    assert "sensitive-access-token" not in repr(credential)


def test_workspace_key_is_derived_from_stable_user_id():
    user_id = UUID("f4304c28-4bf6-5e7d-a284-33cc0a5a6c01")
    assert workspace_key(user_id) == f"user:{user_id}"


def test_principal_rejects_unrecognized_role():
    with pytest.raises(ValidationError):
        Principal(
            user_id=UUID("f4304c28-4bf6-5e7d-a284-33cc0a5a6c01"),
            subject="APP_ADMIN",
            username="Admin",
            auth_source="database_end_user",
            roles=frozenset({cast(Any, "owner")}),
        )


async def test_request_identity_headers_cannot_construct_a_principal(monkeypatch):
    verified = Principal(
        user_id=UUID("f4304c28-4bf6-5e7d-a284-33cc0a5a6c01"),
        subject="APP_ADMIN",
        username="Admin",
        auth_source="database_end_user",
        database_username="APP_ADMIN",
        roles=frozenset({"admin"}),
    )

    class Authenticator:
        async def authenticate(self, _credential):
            return verified

    monkeypatch.setitem(AUTHENTICATORS, "single_user", Authenticator())
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"authorization", b"Bearer verified-token"),
                (b"x-user-id", b"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                (b"x-user-role", b"admin"),
            ],
        }
    )

    context = await request_auth_context(request)

    assert context.principal is verified
    assert context.workspace_key == workspace_key(verified.user_id)


def test_authenticator_readiness_requires_registered_provider(monkeypatch):
    class Authenticator:
        async def authenticate(self, _credential):
            raise AssertionError("not called")

    assert authenticator_ready("oidc") is False

    monkeypatch.setitem(AUTHENTICATORS, "oidc", Authenticator())

    assert authenticator_ready("oidc") is True


@pytest.mark.parametrize("value", ["invalid", "-1"])
def test_authentication_setup_rejects_invalid_core_wait(monkeypatch, value):
    monkeypatch.setenv("AIO_AUTH_SETUP_WAIT_SECONDS", value)

    with pytest.raises(ValueError, match="AIO_AUTH_SETUP_WAIT_SECONDS"):
        _core_wait_seconds()


async def test_authentication_setup_retries_until_core_is_initialized(monkeypatch):
    initialize = AsyncMock(side_effect=[CoreDatabaseInitializationError("not ready"), None])
    sleep = AsyncMock()
    monkeypatch.setattr("server.app.auth.setup.init_core_database", initialize)
    monkeypatch.setattr("server.app.auth.setup.asyncio.sleep", sleep)

    await _init_core_database_with_retry(cast(Any, object()), wait_seconds=1, retry_interval=0)

    assert initialize.await_count == 2
    sleep.assert_awaited_once_with(0)


def test_authentication_configuration_requires_explicit_mode():
    app_settings = _settings()
    object.__setattr__(app_settings, "__pydantic_fields_set__", app_settings.model_fields_set - {"auth_mode"})
    with pytest.raises(CoreDatabaseConfigurationError, match="AIO_AUTH_MODE"):
        validate_auth_configuration(app_settings)


def test_authentication_configuration_requires_installation_and_admin_mapping():
    with pytest.raises(CoreDatabaseConfigurationError) as exc_info:
        validate_auth_configuration(_settings(installation_id=None, admin_database_username=None))
    assert "AIO_INSTALLATION_ID" in str(exc_info.value)
    assert "AIO_ADMIN_DATABASE_USERNAME" in str(exc_info.value)


def test_authentication_validation_preserves_initialized_core_pool():
    app_settings = _settings()
    core = app_settings.database_configs[0]
    pool = object()
    core.pool = cast(Any, pool)

    validate_auth_configuration(app_settings)

    assert app_settings.database_configs[0] is core
    assert app_settings.database_configs[0].pool is pool


def test_database_mode_rejects_oidc_authority_fields():
    with pytest.raises(CoreDatabaseConfigurationError, match="require AIO_AUTH_MODE=oidc"):
        validate_auth_configuration(_settings(oidc_issuer="https://identity.example.test"))


@pytest.mark.parametrize("field", ["api_key", "admin_password"])
def test_removed_auth_fields_are_rejected(field):
    with pytest.raises(ValidationError, match="Removed authentication settings"):
        Settings.model_validate({field: "legacy-value"})


def test_removed_auth_environment_variables_are_rejected(monkeypatch):
    monkeypatch.setenv("AIO_API_KEY", "legacy-value")
    with pytest.raises(ValidationError, match="Removed authentication settings"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_oidc_mode_requires_trust_and_client_configuration():
    with pytest.raises(CoreDatabaseConfigurationError, match="AIO_OIDC_ISSUER"):
        validate_auth_configuration(_settings(auth_mode="oidc"))


def test_valid_oidc_configuration_requires_https_trust():
    app_settings = _settings(
        auth_mode="oidc",
        env="prd",
        oidc_issuer="http://identity.example.test",
        oidc_discovery_url="https://identity.example.test/.well-known/openid-configuration",
        oidc_audience="optimizer-api",
        oidc_required_scopes=["openid", "profile"],
        oidc_client_id="optimizer-client",
        oidc_client_secret=SecretStr("client-secret"),
        oidc_admin_subject="exact-subject",
        oidc_public_server_url="https://optimizer.example.test",
    )
    with pytest.raises(CoreDatabaseConfigurationError, match="AIO_OIDC_ISSUER must use HTTPS"):
        validate_auth_configuration(app_settings)


async def test_setup_reports_missing_database_account_capability(monkeypatch):
    async def execute(_conn, sql, **_kwargs):
        if "USER_SYS_PRIVS" in sql:
            return []
        return []

    monkeypatch.setattr("server.app.auth.setup.execute_sql", execute)
    with pytest.raises(RuntimeError, match="CREATE DATA ROLE privilege"):
        await _validate_local_auth_capabilities(cast(Any, object()))


async def test_setup_reuses_preprovisioned_connect_role(monkeypatch):
    calls = []

    async def execute(_conn, sql, **_kwargs):
        calls.append(sql)
        return [("YES",)]

    monkeypatch.setattr("server.app.auth.setup.execute_sql", execute)

    await _ensure_connect_role(cast(Any, object()))

    assert len(calls) == 1
    assert "USER_ROLE_PRIVS" in calls[0].upper()


async def test_setup_requires_connect_role_admin_option(monkeypatch):
    async def execute(_conn, _sql, **_kwargs):
        return [("NO",)]

    monkeypatch.setattr("server.app.auth.setup.execute_sql", execute)

    with pytest.raises(RuntimeError, match="admin option"):
        await _ensure_connect_role(cast(Any, object()))


async def test_setup_reuses_existing_login_data_role(monkeypatch):
    calls = []

    async def execute(_conn, sql, *_args, **_kwargs):
        calls.append(sql)
        return [("AIO_LOGIN_ROLE",)] if "DBA_DATA_ROLES" in sql.upper() else None

    monkeypatch.setattr("server.app.auth.setup.execute_sql", execute)

    await _ensure_login_data_role(cast(Any, object()), "AIO_LOGIN_ROLE")

    assert len(calls) == 2
    assert all("CREATE DATA ROLE" not in sql for sql in calls)
    assert calls[-1] == 'GRANT AIO_DDS_ROLE TO "AIO_LOGIN_ROLE"'
