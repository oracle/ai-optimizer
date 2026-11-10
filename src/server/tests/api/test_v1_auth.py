"""Authentication API tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from server.app.auth.models import IssuedSession, Principal

pytestmark = pytest.mark.unit


def _principal() -> Principal:
    return Principal(
        user_id=UUID("f4304c28-4bf6-5e7d-a284-33cc0a5a6c01"),
        subject="APP_ADMIN",
        username="Admin",
        auth_source="database_end_user",
        database_username="APP_ADMIN",
        roles=frozenset({"admin"}),
    )


async def test_database_login_returns_raw_token_once(app_client, monkeypatch):
    issued = IssuedSession(token="opaque-session-token", expires=datetime.now(UTC) + timedelta(hours=1))
    monkeypatch.setattr("server.app.auth.router.settings.auth_mode", "single_user")
    monkeypatch.setattr(
        "server.app.auth.router.login_database_user",
        AsyncMock(return_value=(issued, _principal())),
    )

    response = await app_client.post("/v1/auth/login", json={"username": "APP_ADMIN", "password": "secret"})

    assert response.status_code == 200
    assert response.json()["access_token"] == "opaque-session-token"
    assert response.json()["principal"]["user_id"] == str(_principal().user_id)


async def test_login_failure_is_generic(app_client, monkeypatch):
    from server.app.auth.service import AuthenticationError

    monkeypatch.setattr("server.app.auth.router.settings.auth_mode", "single_user")
    monkeypatch.setattr(
        "server.app.auth.router.login_database_user",
        AsyncMock(side_effect=AuthenticationError("private database detail")),
    )

    response = await app_client.post("/v1/auth/login", json={"username": "UNKNOWN", "password": "wrong"})

    assert response.status_code == 401
    assert "private database detail" not in response.text


async def test_logout_revokes_current_bearer(app_client, auth_headers, monkeypatch):
    revoke = AsyncMock()
    monkeypatch.setattr("server.app.auth.router.logout_database_session", revoke)

    response = await app_client.post("/v1/auth/logout", headers=auth_headers)

    assert response.status_code == 200
    revoke.assert_awaited_once_with("test-token")


async def test_single_user_hides_member_management(app_client, auth_headers, monkeypatch):
    monkeypatch.setattr("server.app.auth.router.settings.auth_mode", "single_user")

    response = await app_client.get("/v1/users", headers=auth_headers)

    assert response.status_code == 404


async def test_admin_database_mapping_requires_both_credentials_and_revokes_sessions(
    app_client,
    auth_headers,
    monkeypatch,
):
    verify = AsyncMock(side_effect=["APP_ADMIN", "NEW_ADMIN"])
    recover = AsyncMock()
    monkeypatch.setattr("server.app.auth.router.settings.auth_mode", "single_user")
    monkeypatch.setattr("server.app.auth.router.settings.installation_id", "test-installation")
    monkeypatch.setattr("server.app.auth.router.settings.admin_database_username", "APP_ADMIN")
    monkeypatch.setattr("server.app.auth.router.verify_database_credentials", verify)
    monkeypatch.setattr("server.app.auth.router.database_account_status", AsyncMock(return_value="OPEN"))
    monkeypatch.setattr("server.app.auth.router.repository.recover_admin_identity", recover)

    response = await app_client.put(
        "/v1/auth/admin/database-mapping",
        headers=auth_headers,
        json={
            "current_password": "current-secret",
            "database_username": "new_admin",
            "replacement_password": "replacement-secret",
        },
    )

    assert response.status_code == 200
    assert verify.await_args_list[0].args == ("APP_ADMIN", "current-secret")
    assert verify.await_args_list[1].args == ("NEW_ADMIN", "replacement-secret")
    recover.assert_awaited_once_with("test-installation", database_username="NEW_ADMIN")
