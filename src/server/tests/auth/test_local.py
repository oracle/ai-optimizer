"""Database-account authentication and session tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import SecretStr

from server.app.auth import local, repository, users
from server.app.auth.models import AuthRole, AuthSession, AuthUser, RequestCredential

pytestmark = pytest.mark.unit

_USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_SESSION_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _user(*, role: AuthRole = "member") -> AuthUser:
    now = datetime.now(UTC)
    return AuthUser(
        user_id=_USER_ID,
        username="APP_MEMBER",
        auth_source="database_end_user",
        database_username="APP_MEMBER",
        role=role,
        status="active",
        created=now,
        updated=now,
    )


def _session(token: str = "token") -> AuthSession:
    now = datetime.now(UTC)
    return AuthSession(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        token_digest=SecretStr(local.session_token_digest(token).hex()),
        created=now,
        expires=now + timedelta(hours=1),
        last_seen=now,
    )


def test_session_digest_is_domain_separated_and_token_is_redacted():
    digest = local.session_token_digest("opaque-token")

    assert len(digest) == 32
    assert digest != __import__("hashlib").sha256(b"opaque-token").digest()
    assert "opaque-token" not in repr(RequestCredential(kind="bearer", value="opaque-token"))


async def test_database_login_issues_only_a_digest_to_repository(monkeypatch):
    member = _user()
    create_session = AsyncMock(return_value=_session())
    monkeypatch.setattr(repository, "get_user_by_database_username", AsyncMock(return_value=member))
    monkeypatch.setattr(local, "verify_database_credentials", AsyncMock(return_value="APP_MEMBER"))
    monkeypatch.setattr(local._DATABASE_AUTHENTICATOR, "account_status", AsyncMock(return_value="OPEN"))
    monkeypatch.setattr(repository, "create_session", create_session)

    issued, principal = await local.login_database_user("app_member", "secret")

    assert principal.user_id == _USER_ID
    assert len(issued.token) >= 43
    assert issued.token not in repr(issued)
    assert create_session.await_args is not None
    call = create_session.await_args.kwargs
    assert call["token_digest"] == local.session_token_digest(issued.token)
    assert issued.token.encode() not in call["token_digest"]


async def test_database_session_authenticator_checks_account_and_touches_session(monkeypatch):
    authenticator = local.DatabaseSessionAuthenticator()
    touch = AsyncMock()
    monkeypatch.setattr(repository, "get_active_session_user", AsyncMock(return_value=(_session(), _user())))
    monkeypatch.setattr(authenticator, "account_status", AsyncMock(return_value="OPEN"))
    monkeypatch.setattr(repository, "touch_session", touch)

    principal = await authenticator.authenticate(RequestCredential(kind="bearer", value="token"))

    assert principal.user_id == _USER_ID
    touch.assert_awaited_once()


async def test_locking_member_revokes_shared_sessions(monkeypatch):
    member = _user()
    admin_call = AsyncMock()
    revoke = AsyncMock()
    monkeypatch.setattr(repository, "get_user_by_id", AsyncMock(return_value=member))
    monkeypatch.setattr(repository, "update_database_member", AsyncMock(return_value=member))
    monkeypatch.setattr(users, "_call_admin", admin_call)
    monkeypatch.setattr(repository, "revoke_user_sessions", revoke)

    await users.update_member(_USER_ID, True, None, None)

    admin_call.assert_awaited_once_with("LOCK", "APP_MEMBER")
    revoke.assert_awaited_once_with(_USER_ID)


async def test_password_reset_revokes_shared_sessions(monkeypatch):
    member = _user()
    admin_call = AsyncMock()
    revoke = AsyncMock()
    monkeypatch.setattr(repository, "get_user_by_id", AsyncMock(return_value=member))
    monkeypatch.setattr(users, "_call_admin", admin_call)
    monkeypatch.setattr(repository, "revoke_user_sessions", revoke)

    await users.reset_member_password(_USER_ID, "temporary-secret")

    admin_call.assert_awaited_once_with("RESET", "APP_MEMBER", "temporary-secret")
    revoke.assert_awaited_once_with(_USER_ID)


async def test_admin_password_change_is_managed_outside_the_application(monkeypatch):
    verify = AsyncMock()
    monkeypatch.setattr(repository, "get_user_by_database_username", AsyncMock(return_value=_user(role="admin")))
    monkeypatch.setattr(local, "verify_database_credentials", verify)

    with pytest.raises(local.AuthenticationError):
        await local.change_database_password("APP_MEMBER", "current-secret", "new-secret")

    verify.assert_not_awaited()


async def test_member_creation_reconciles_existing_managed_account(monkeypatch):
    member = _user()
    admin_call = AsyncMock()
    monkeypatch.setattr(repository, "get_user_by_database_username", AsyncMock(return_value=None))
    monkeypatch.setattr(users, "database_account_status", AsyncMock(return_value="LOCKED"))
    monkeypatch.setattr(users, "_call_admin", admin_call)
    monkeypatch.setattr(repository, "create_database_member", AsyncMock(return_value=member))

    result = await users.create_member("APP_MEMBER", "new-temporary-secret", None, None)

    assert result is member
    admin_call.assert_awaited_once_with("RESET", "APP_MEMBER", "new-temporary-secret")


async def test_reconciled_member_is_locked_when_metadata_creation_fails(monkeypatch):
    admin_call = AsyncMock()
    monkeypatch.setattr(repository, "get_user_by_database_username", AsyncMock(return_value=None))
    monkeypatch.setattr(users, "database_account_status", AsyncMock(return_value="LOCKED"))
    monkeypatch.setattr(users, "_call_admin", admin_call)
    monkeypatch.setattr(repository, "create_database_member", AsyncMock(side_effect=RuntimeError("write failed")))

    with pytest.raises(RuntimeError, match="write failed"):
        await users.create_member("APP_MEMBER", "new-temporary-secret", None, None)

    assert [item.args for item in admin_call.await_args_list] == [
        ("RESET", "APP_MEMBER", "new-temporary-secret"),
        ("LOCK", "APP_MEMBER"),
    ]


async def test_failed_login_applies_per_source_and_user_backoff(monkeypatch):
    limiter = local._LoginAttemptLimiter()
    sleep = AsyncMock()
    monkeypatch.setattr(local.asyncio, "sleep", sleep)
    monkeypatch.setattr(local, "monotonic", lambda: 100.0)

    await limiter.failed(("127.0.0.1", "APP_MEMBER"))
    await limiter.wait(("127.0.0.1", "APP_MEMBER"))

    sleep.assert_awaited_once_with(0.25)
