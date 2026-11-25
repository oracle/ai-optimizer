"""Tests for the authentication foundation and configuration contract."""

from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from server.app.auth.models import Principal, RequestCredential, workspace_key
from server.app.auth.provisioning import (
    configure_provisioning_authority,
    local_user_management_issues,
    missing_local_user_management_capabilities,
    package_role_name,
)
from server.app.auth.service import AUTHENTICATORS, authenticator_ready, request_auth_context
from server.app.auth.setup import (
    _ensure_connect_role,
    _ensure_login_data_role,
    _init_core_database_with_retry,
    _install_local_user_management,
)
from server.app.core.settings import (
    CoreDatabaseConfigurationError,
    Settings,
    validate_auth_authority_configuration,
    validate_auth_configuration,
)
from server.app.database.registry import CoreDatabaseInitializationError

pytestmark = pytest.mark.unit


def _settings(**overrides) -> Settings:
    values = {
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

    monkeypatch.setitem(AUTHENTICATORS, "local_users", Authenticator())
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


async def test_authentication_setup_retries_until_core_is_initialized(monkeypatch):
    initialize = AsyncMock(side_effect=[CoreDatabaseInitializationError("not ready"), None])
    sleep = AsyncMock()
    monkeypatch.setattr("server.app.auth.setup.init_core_database", initialize)
    monkeypatch.setattr("server.app.auth.setup.asyncio.sleep", sleep)

    await _init_core_database_with_retry(cast(Any, object()), wait_seconds=1, retry_interval=0)

    assert initialize.await_count == 2
    sleep.assert_awaited_once_with(0)


def test_authentication_validation_preserves_initialized_core_pool():
    app_settings = _settings()
    core = app_settings.database_configs[0]
    pool = object()
    core.pool = cast(Any, pool)

    validate_auth_configuration(app_settings)

    assert app_settings.database_configs[0] is core
    assert app_settings.database_configs[0].pool is pool


def test_authentication_authority_is_derived_from_oidc_configuration():
    assert _settings().auth_mode == "local_users"
    assert _settings(oidc_issuer="https://identity.example.test").auth_mode == "oidc"


def test_partial_oidc_configuration_is_rejected():
    with pytest.raises(CoreDatabaseConfigurationError, match="OIDC configuration is incomplete"):
        validate_auth_configuration(_settings(oidc_issuer="https://identity.example.test"))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"auth_session_absolute_seconds": 300, "auth_session_idle_seconds": 301},
            "AIO_AUTH_SESSION_IDLE_SECONDS",
        ),
    ],
)
def test_authentication_configuration_rejects_inconsistent_session_intervals(overrides, message):
    with pytest.raises(CoreDatabaseConfigurationError, match=message):
        validate_auth_configuration(_settings(**overrides))


@pytest.mark.parametrize(
    ("field", "environment_name"),
    [("api_key", "AIO_API_KEY"), ("admin_password", "AIO_ADMIN_PASSWORD")],
)
def test_removed_auth_fields_are_ignored_with_warning(field, environment_name):
    with pytest.warns(UserWarning, match=rf"ignored and unused: {environment_name}"):
        Settings.model_validate({field: "legacy-value"})


def test_removed_auth_environment_variables_are_ignored_with_warning(monkeypatch):
    monkeypatch.setenv("AIO_API_KEY", "legacy-value")
    with pytest.warns(UserWarning, match=r"ignored and unused: AIO_API_KEY"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_oidc_configuration_requires_trust_and_client_configuration():
    with pytest.raises(CoreDatabaseConfigurationError, match="AIO_OIDC_AUDIENCE"):
        validate_auth_configuration(
            _settings(
                oidc_issuer="https://identity.example.test",
                oidc_admin_subject="exact-subject",
            )
        )


def test_oidc_authority_setup_does_not_require_client_secret():
    validate_auth_authority_configuration(
        _settings(
            oidc_issuer="https://identity.example.test",
            oidc_admin_subject="exact-subject",
        )
    )


def test_valid_oidc_configuration_requires_https_trust():
    app_settings = _settings(
        env="prd",
        oidc_issuer="http://identity.example.test",
        oidc_audience="optimizer-api",
        oidc_required_scopes=["openid", "profile"],
        oidc_admin_subject="exact-subject",
        oidc_public_server_url="https://optimizer.example.test",
    )
    with pytest.raises(CoreDatabaseConfigurationError, match="AIO_OIDC_ISSUER must use HTTPS"):
        validate_auth_configuration(app_settings)


async def test_setup_reports_missing_member_management_capability(monkeypatch):
    async def execute(_conn, sql, **_kwargs):
        if "USER_SYS_PRIVS" in sql:
            return []
        return []

    monkeypatch.setattr("server.app.auth.provisioning.execute_sql", execute)
    missing = await missing_local_user_management_capabilities(cast(Any, object()))

    assert "CREATE DATA ROLE privilege" in missing


async def test_member_management_accepts_direct_authority(monkeypatch):
    execute = AsyncMock(side_effect=[[("APP_SCHEMA",)], [], [("AIO_LOGIN_ROLE",)]])
    missing = AsyncMock(return_value=[])
    monkeypatch.setattr("server.app.auth.provisioning.provisioning_package_available", AsyncMock(return_value=True))
    monkeypatch.setattr("server.app.auth.provisioning.execute_sql", execute)
    monkeypatch.setattr("server.app.auth.provisioning.missing_local_user_management_capabilities", missing)

    assert await local_user_management_issues(cast(Any, object())) == []
    missing.assert_awaited_once()


async def test_member_management_reports_unavailable_package(monkeypatch):
    monkeypatch.setattr("server.app.auth.provisioning.provisioning_package_available", AsyncMock(return_value=False))

    assert await local_user_management_issues(cast(Any, object())) == ["AIO_AUTH_ADMIN package is unavailable"]


async def test_member_management_accepts_delegated_package_authority(monkeypatch):
    execute = AsyncMock(side_effect=[[("APP_SCHEMA",)], [("AIO_AUTH_PACKAGE",)]])
    missing = AsyncMock()
    monkeypatch.setattr("server.app.auth.provisioning.provisioning_package_available", AsyncMock(return_value=True))
    monkeypatch.setattr("server.app.auth.provisioning.execute_sql", execute)
    monkeypatch.setattr("server.app.auth.provisioning.missing_local_user_management_capabilities", missing)

    assert await local_user_management_issues(cast(Any, object())) == []
    missing.assert_not_awaited()


async def test_missing_member_privileges_do_not_block_local_authentication(monkeypatch, caplog):
    install = AsyncMock()
    monkeypatch.setattr(
        "server.app.auth.setup.missing_local_user_management_capabilities",
        AsyncMock(return_value=["ALTER END USER privilege"]),
    )
    monkeypatch.setattr("server.app.auth.setup.install_provisioning_package", install)

    available = await _install_local_user_management(
        cast(Any, object()),
        None,
        cast(Any, object()),
        "AIO_LOGIN_ROLE",
    )

    assert available is False
    install.assert_awaited_once()
    assert "Local member administration is unavailable: ALTER END USER privilege" in caplog.text


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


async def test_provisioning_privileges_are_attached_to_package(monkeypatch):
    execute = AsyncMock(side_effect=lambda _conn, sql, *_args, **_kwargs: [] if "dba_roles" in sql else None)
    monkeypatch.setattr("server.app.auth.provisioning.execute_sql", execute)

    await configure_provisioning_authority(cast(Any, object()), cast(Any, object()), "APP_SCHEMA")

    package_role = package_role_name("APP_SCHEMA")
    statements = [call.args[1] for call in execute.await_args_list]
    assert f'GRANT {package_role} TO "APP_SCHEMA" WITH DELEGATE OPTION' in statements
    assert f'GRANT {package_role} TO PACKAGE "APP_SCHEMA".AIO_AUTH_ADMIN' in statements
    assert 'REVOKE CREATE END USER FROM "APP_SCHEMA"' in statements
    assert 'REVOKE ALTER END USER FROM "APP_SCHEMA"' in statements


async def test_provisioning_rejects_existing_package_role_with_unexpected_grantee(monkeypatch):
    execute = AsyncMock(side_effect=[[("EXISTING", "SYSTEM")], [("OTHER_SCHEMA",)], []])
    monkeypatch.setattr("server.app.auth.provisioning.execute_sql", execute)

    with pytest.raises(RuntimeError, match="unexpected grantees"):
        await configure_provisioning_authority(cast(Any, object()), cast(Any, object()), "APP_SCHEMA")
