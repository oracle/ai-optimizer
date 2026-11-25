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

    monkeypatch.setattr(
        "server.app.auth.router.login_database_user",
        AsyncMock(side_effect=AuthenticationError("private database detail")),
    )

    response = await app_client.post("/v1/auth/login", json={"username": "UNKNOWN", "password": "wrong"})

    assert response.status_code == 401
    assert "private database detail" not in response.text


async def test_password_change_requires_authentication(app_client, monkeypatch):
    change = AsyncMock()
    monkeypatch.setattr("server.app.auth.router.change_database_password", change)

    response = await app_client.post(
        "/v1/auth/password-change",
        json={"current_password": "current-secret", "new_password": "new-secret"},
    )

    assert response.status_code == 401
    change.assert_not_awaited()


async def test_password_change_uses_authenticated_database_user(app_client, auth_headers, monkeypatch):
    from server.app.auth.service import AUTHENTICATORS

    member = Principal(
        user_id=UUID("0fc6d82d-56ea-44c6-933f-a50fe69db9e0"),
        subject="APP_MEMBER",
        username="Member",
        auth_source="database_end_user",
        database_username="APP_MEMBER",
        roles=frozenset({"member"}),
    )

    class MemberAuthenticator:
        async def authenticate(self, _credential):
            return member

    monkeypatch.setitem(AUTHENTICATORS, "local_users", MemberAuthenticator())
    change = AsyncMock()
    monkeypatch.setattr("server.app.auth.router.change_database_password", change)

    response = await app_client.post(
        "/v1/auth/password-change",
        headers=auth_headers,
        json={
            "username": "SOMEONE_ELSE",
            "current_password": "current-secret",
            "new_password": "new-secret",
        },
    )

    assert response.status_code == 200
    change.assert_awaited_once_with("APP_MEMBER", "current-secret", "new-secret")


async def test_logout_revokes_current_bearer(app_client, auth_headers, monkeypatch):
    revoke = AsyncMock()
    monkeypatch.setattr("server.app.auth.router.logout_database_session", revoke)

    response = await app_client.post("/v1/auth/logout", headers=auth_headers)

    assert response.status_code == 200
    revoke.assert_awaited_once_with("test-token")


async def test_missing_database_capabilities_hide_member_management(app_client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        "server.app.auth.router.require_local_user_management",
        AsyncMock(side_effect=LookupError("Local user management is unavailable")),
    )

    response = await app_client.get("/v1/users", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Local user management is unavailable"


async def test_admin_database_mapping_endpoint_is_not_exposed(app_client, auth_headers):
    response = await app_client.put(
        "/v1/auth/admin/database-mapping",
        headers=auth_headers,
        json={},
    )

    assert response.status_code == 404
