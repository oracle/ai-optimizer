"""Oracle authentication repository contract tests."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from server.app.auth import repository
from server.app.core.settings import Settings

pytestmark = pytest.mark.unit


def _settings(**overrides) -> Settings:
    values = {
        "auth_mode": "single_user",
        "installation_id": "test-installation",
        "admin_database_username": "APP_ADMIN",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def _pool_for(conn):
    @asynccontextmanager
    async def acquire():
        yield conn

    return SimpleNamespace(acquire=acquire)


async def test_authority_refuses_existing_binding_with_changed_installation(monkeypatch):
    app_settings = _settings(installation_id="different-installation")
    expected = repository._configured_authority(app_settings, ("DB", "APP_SCHEMA"))
    existing = ("original-installation", *expected[1:], datetime.now(UTC), datetime.now(UTC))
    monkeypatch.setattr(repository, "authority_identity", AsyncMock(return_value=("DB", "APP_SCHEMA")))
    monkeypatch.setattr(repository, "require_core_pool", lambda: _pool_for(object()))
    monkeypatch.setattr(repository, "execute_sql", AsyncMock(return_value=[existing]))

    with pytest.raises(ValueError, match="Authentication authority does not match"):
        await repository.bind_authority(app_settings)


async def test_authority_refuses_same_installation_on_different_core(monkeypatch):
    app_settings = _settings()
    expected = repository._configured_authority(app_settings, ("REPLACEMENT_DB", "APP_SCHEMA"))
    existing = (
        expected[0],
        expected[1],
        expected[2],
        "ORIGINAL_DB",
        *expected[4:],
        datetime.now(UTC),
        datetime.now(UTC),
    )
    monkeypatch.setattr(repository, "authority_identity", AsyncMock(return_value=("REPLACEMENT_DB", "APP_SCHEMA")))
    monkeypatch.setattr(repository, "require_core_pool", lambda: _pool_for(object()))
    monkeypatch.setattr(repository, "execute_sql", AsyncMock(return_value=[existing]))

    with pytest.raises(ValueError, match="Authentication authority does not match"):
        await repository.verify_authority(app_settings)


async def test_authority_accepts_transport_repair_to_same_logical_core(monkeypatch):
    app_settings = _settings()
    now = datetime.now(UTC)
    authority = (*repository._configured_authority(app_settings, ("LOGICAL_DB", "APP_SCHEMA")), now, now)
    execute = AsyncMock(
        side_effect=[
            [authority],
            [(app_settings.admin_database_username, "DATABASE_END_USER", None, None)],
            [("PACKAGE",), ("PACKAGE BODY",)],
            None,
        ]
    )
    conn = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(repository, "authority_identity", AsyncMock(return_value=("LOGICAL_DB", "APP_SCHEMA")))
    monkeypatch.setattr(repository, "require_core_pool", lambda: _pool_for(conn))
    monkeypatch.setattr(repository, "execute_sql", execute)
    monkeypatch.setattr(repository, "_cleanup_expired_sessions", AsyncMock(return_value=0))

    result = await repository.verify_authority(app_settings)

    assert result.database_identity == "LOGICAL_DB"
    assert result.application_schema == "APP_SCHEMA"
    conn.commit.assert_awaited_once()


async def test_authority_identity_includes_database_container(monkeypatch):
    monkeypatch.setattr(repository, "require_core_pool", lambda: _pool_for(object()))
    monkeypatch.setattr(repository, "execute_sql", AsyncMock(return_value=[("APPDB", "APP_PDB", "APP_SCHEMA")]))

    identity = await repository.authority_identity()

    assert identity == ("APPDB:APP_PDB", "APP_SCHEMA")


async def test_oidc_authority_refuses_wrong_admin_subject(monkeypatch):
    app_settings = _settings(
        auth_mode="oidc",
        oidc_issuer="https://identity.example.test",
        oidc_admin_subject="configured-admin",
    )
    now = datetime.now(UTC)
    authority = (*repository._configured_authority(app_settings, ("LOGICAL_DB", "APP_SCHEMA")), now, now)
    execute = AsyncMock(
        side_effect=[
            [authority],
            [(app_settings.admin_database_username, "OIDC", app_settings.oidc_issuer, "different-admin")],
        ]
    )
    monkeypatch.setattr(repository, "authority_identity", AsyncMock(return_value=("LOGICAL_DB", "APP_SCHEMA")))
    monkeypatch.setattr(repository, "require_core_pool", lambda: _pool_for(object()))
    monkeypatch.setattr(repository, "execute_sql", execute)

    with pytest.raises(ValueError, match="Reserved Admin database mapping"):
        await repository.verify_authority(app_settings)


async def test_user_and_session_lookups_map_oracle_rows(monkeypatch):
    now = datetime.now(UTC)
    user_row = (
        repository.ADMIN_USER_ID.bytes,
        "Admin",
        "DATABASE_END_USER",
        "APP_ADMIN",
        None,
        None,
        "Admin",
        None,
        "ADMIN",
        "ACTIVE",
        now,
        now,
        None,
    )
    session_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    session_row = (
        session_id.bytes,
        repository.ADMIN_USER_ID.bytes,
        b"a" * 32,
        now,
        now + timedelta(hours=1),
        now,
        None,
        "127.0.0.1",
    )
    execute = AsyncMock(side_effect=[[user_row], [session_row]])
    monkeypatch.setattr(repository, "require_core_pool", lambda: _pool_for(object()))
    monkeypatch.setattr(repository, "execute_sql", execute)

    user = await repository.get_user_by_database_username("app_admin")
    session = await repository.get_session_by_digest(b"a" * 32)

    assert user is not None and user.user_id == repository.ADMIN_USER_ID
    assert user.role == "admin" and user.status == "active"
    assert session is not None and session.session_id == session_id
    assert session.token_digest.get_secret_value() == (b"a" * 32).hex()
    assert (b"a" * 32).hex() not in repr(session)


async def test_cleanup_is_bounded_and_committed(monkeypatch):
    cursor = AsyncMock()
    cursor.__aenter__.return_value = cursor
    cursor.__aexit__.return_value = False
    cursor.rowcount = 7
    conn = SimpleNamespace(cursor=lambda: cursor, commit=AsyncMock())
    monkeypatch.setattr(repository, "require_core_pool", lambda: _pool_for(conn))

    count = await repository.cleanup_expired_sessions(batch_size=25)

    assert count == 7
    assert cursor.execute.await_args.args[1] == {"batch_size": 25}
    conn.commit.assert_awaited_once()
