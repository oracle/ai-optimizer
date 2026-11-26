"""Oracle repositories for authentication users, sessions, and authority."""

from datetime import datetime
from uuid import UUID, uuid4, uuid5

import oracledb
from pydantic import SecretStr

from server.app.auth.models import AuthAuthority, AuthSession, AuthUser
from server.app.core.settings import Settings, settings
from server.app.database.config import require_core_pool
from server.app.database.sql import execute_sql

SCHEMA_VERSION = 1
ADMIN_USER_ID = UUID("f4304c28-4bf6-5e7d-a284-33cc0a5a6c01")
OIDC_USER_NAMESPACE = UUID("ab2c6cd7-a206-4e14-8d86-660efcf08b13")
SESSION_CLEANUP_BATCH_SIZE = 500


async def connection_database_identity(conn: oracledb.AsyncConnection) -> str:
    rows = await execute_sql(
        conn,
        "SELECT COALESCE(SYS_CONTEXT('USERENV', 'DB_UNIQUE_NAME'), "
        "SYS_CONTEXT('USERENV', 'DB_NAME')), "
        "COALESCE(SYS_CONTEXT('USERENV', 'CON_NAME'), 'NONCDB') FROM DUAL",
        max_rows=1,
    )
    if not rows or not all(rows[0]):
        raise RuntimeError("Database logical identity is unavailable")
    return f"{rows[0][0]}:{rows[0][1]}".upper()


async def authority_identity() -> tuple[str, str]:
    """Return the stable database and application-schema identity for CORE."""
    pool = require_core_pool()
    async with pool.acquire() as conn:
        database_identity = await connection_database_identity(conn)
        rows = await execute_sql(
            conn,
            "SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL",
            max_rows=1,
        )
    if not rows or not all(rows[0]):
        raise RuntimeError("CORE logical identity is unavailable")
    return database_identity, str(rows[0][0]).upper()


def _configured_authority(app_settings: Settings, identity: tuple[str, str]) -> tuple:
    return (
        app_settings.auth_mode.upper(),
        SCHEMA_VERSION,
        identity[0],
        identity[1],
        app_settings.oidc_issuer if app_settings.auth_mode == "oidc" else None,
        app_settings.oidc_admin_subject if app_settings.auth_mode == "oidc" else None,
    )


def _admin_database_identity(app_settings: Settings) -> str | None:
    if app_settings.auth_mode == "oidc":
        return None
    if not app_settings.db_username:
        raise ValueError("CORE database username is required")
    return app_settings.db_username.upper()


def _auth_user_from_row(row: tuple) -> AuthUser:
    return AuthUser(
        user_id=UUID(bytes=bytes(row[0])),
        username=row[1],
        auth_source=row[2].lower(),
        database_username=row[3],
        issuer=row[4],
        subject=row[5],
        display_name=row[6],
        email=row[7],
        role=row[8].lower(),
        status=row[9].lower(),
        created=row[10],
        updated=row[11],
        last_login=row[12],
    )


def _auth_session_from_row(row: tuple) -> AuthSession:
    return AuthSession(
        session_id=UUID(bytes=bytes(row[0])),
        user_id=UUID(bytes=bytes(row[1])),
        token_digest=SecretStr(bytes(row[2]).hex()),
        created=row[3],
        expires=row[4],
        last_seen=row[5],
        revoked=row[6],
        remote_address=row[7],
    )


async def get_user_by_database_username(username: str) -> AuthUser | None:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT user_id, username, auth_source, database_username, issuer, subject, "
            "display_name, email, role, status, created, updated, last_login "
            "FROM aio_users WHERE database_username = :username",
            {"username": username.upper()},
            max_rows=1,
        )
    return _auth_user_from_row(rows[0]) if rows else None


async def get_user_by_oidc_subject(issuer: str, subject: str) -> AuthUser | None:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT user_id, username, auth_source, database_username, issuer, subject, "
            "display_name, email, role, status, created, updated, last_login "
            "FROM aio_users WHERE issuer = :issuer AND subject = :subject",
            {"issuer": issuer, "subject": subject},
            max_rows=1,
        )
    return _auth_user_from_row(rows[0]) if rows else None


async def resolve_oidc_user(
    issuer: str,
    subject: str,
    username: str,
    display_name: str | None,
    email: str | None,
) -> AuthUser:
    """Return the configured Admin or persist a stable OIDC member."""
    user_id = (
        ADMIN_USER_ID if subject == settings.oidc_admin_subject else uuid5(OIDC_USER_NAMESPACE, f"{issuer}\0{subject}")
    )
    pool = require_core_pool()
    async with pool.acquire() as conn:
        await execute_sql(
            conn,
            "MERGE INTO aio_users target USING (SELECT :issuer issuer, :subject subject FROM dual) source "
            "ON (target.issuer = source.issuer AND target.subject = source.subject) "
            "WHEN MATCHED THEN UPDATE SET username = CASE WHEN target.role = 'ADMIN' THEN target.username "
            "ELSE :username END, display_name = :display_name, email = :email, "
            "last_login = SYSTIMESTAMP, updated = SYSTIMESTAMP "
            "WHEN NOT MATCHED THEN INSERT (user_id, username, auth_source, issuer, subject, display_name, email, "
            "role, status, last_login) VALUES (:user_id, :username, 'OIDC', :issuer, :subject, :display_name, "
            ":email, 'MEMBER', 'ACTIVE', SYSTIMESTAMP)",
            {
                "user_id": user_id.bytes,
                "issuer": issuer,
                "subject": subject,
                "username": username[:255],
                "display_name": display_name[:255] if display_name else None,
                "email": email[:320] if email else None,
            },
        )
        await conn.commit()
    user = await get_user_by_oidc_subject(issuer, subject)
    if user is None or user.user_id != user_id:
        raise RuntimeError("OIDC identity does not match the configured authority")
    return user


async def get_user_by_id(user_id: UUID) -> AuthUser | None:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT user_id, username, auth_source, database_username, issuer, subject, "
            "display_name, email, role, status, created, updated, last_login "
            "FROM aio_users WHERE user_id = :user_id",
            {"user_id": user_id.bytes},
            max_rows=1,
        )
    return _auth_user_from_row(rows[0]) if rows else None


async def list_database_users() -> list[AuthUser]:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT user_id, username, auth_source, database_username, issuer, subject, "
            "display_name, email, role, status, created, updated, last_login "
            "FROM aio_users WHERE auth_source = 'DATABASE_END_USER' ORDER BY username",
            max_rows=10_000,
        )
    return [_auth_user_from_row(row) for row in rows or []]


async def create_database_member(
    user_id: UUID,
    database_username: str,
    display_name: str | None,
    email: str | None,
) -> AuthUser:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        await execute_sql(
            conn,
            "INSERT INTO aio_users (user_id, username, auth_source, database_username, display_name, email, role) "
            "VALUES (:user_id, :username, 'DATABASE_END_USER', :database_username, :display_name, :email, 'MEMBER')",
            {
                "user_id": user_id.bytes,
                "username": database_username,
                "database_username": database_username,
                "display_name": display_name,
                "email": email,
            },
        )
        await conn.commit()
    user = await get_user_by_id(user_id)
    if user is None:
        raise RuntimeError("Created authentication user is unavailable")
    return user


async def update_database_member(user_id: UUID, display_name: str | None, email: str | None) -> AuthUser:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        await execute_sql(
            conn,
            "UPDATE aio_users SET display_name = :display_name, email = :email, updated = SYSTIMESTAMP "
            "WHERE user_id = :user_id AND role = 'MEMBER' AND auth_source = 'DATABASE_END_USER'",
            {"display_name": display_name, "email": email, "user_id": user_id.bytes},
        )
        await conn.commit()
    user = await get_user_by_id(user_id)
    if user is None or user.role != "member":
        raise ValueError("Authentication member was not found")
    return user


async def get_session_by_digest(token_digest: bytes) -> AuthSession | None:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT session_id, user_id, token_digest, created, expires, last_seen, revoked, remote_address "
            "FROM aio_auth_sessions WHERE token_digest = :token_digest",
            {"token_digest": token_digest},
            max_rows=1,
        )
    if not rows:
        return None
    return _auth_session_from_row(rows[0])


async def create_session(
    session_id: UUID,
    user_id: UUID,
    token_digest: bytes,
    expires: datetime,
    remote_address: str | None,
    max_sessions: int,
) -> AuthSession:
    """Create a session and revoke this user's oldest excess sessions."""
    pool = require_core_pool()
    async with pool.acquire() as conn:
        await execute_sql(
            conn,
            "INSERT INTO aio_auth_sessions (session_id, user_id, token_digest, expires, remote_address) "
            "VALUES (:session_id, :user_id, :token_digest, :expires, :remote_address)",
            {
                "session_id": session_id.bytes,
                "user_id": user_id.bytes,
                "token_digest": token_digest,
                "expires": expires,
                "remote_address": remote_address,
            },
        )
        await execute_sql(
            conn,
            "UPDATE aio_auth_sessions SET revoked = SYSTIMESTAMP WHERE revoked IS NULL AND session_id IN ("
            "SELECT session_id FROM (SELECT session_id, ROW_NUMBER() OVER (ORDER BY created DESC) position "
            "FROM aio_auth_sessions WHERE user_id = :user_id AND revoked IS NULL AND expires > SYSTIMESTAMP) "
            "WHERE position > :max_sessions)",
            {"user_id": user_id.bytes, "max_sessions": max_sessions},
        )
        await execute_sql(
            conn,
            "UPDATE aio_users SET last_login = SYSTIMESTAMP, updated = SYSTIMESTAMP WHERE user_id = :user_id",
            {"user_id": user_id.bytes},
        )
        await conn.commit()
    session = await get_session_by_digest(token_digest)
    if session is None:
        raise RuntimeError("Created authentication session is unavailable")
    return session


async def get_active_session_user(token_digest: bytes, idle_seconds: int) -> tuple[AuthSession, AuthUser] | None:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT s.session_id, s.user_id, s.token_digest, s.created, s.expires, s.last_seen, s.revoked, "
            "s.remote_address, u.user_id, u.username, u.auth_source, u.database_username, u.issuer, u.subject, "
            "u.display_name, u.email, u.role, u.status, u.created, u.updated, u.last_login "
            "FROM aio_auth_sessions s JOIN aio_users u ON u.user_id = s.user_id "
            "WHERE s.token_digest = :token_digest AND s.revoked IS NULL AND s.expires > SYSTIMESTAMP "
            "AND s.last_seen > SYSTIMESTAMP - NUMTODSINTERVAL(:idle_seconds, 'SECOND') "
            "AND u.status = 'ACTIVE'",
            {"token_digest": token_digest, "idle_seconds": idle_seconds},
            max_rows=1,
        )
    if not rows:
        return None
    return _auth_session_from_row(rows[0][:8]), _auth_user_from_row(rows[0][8:])


async def touch_session(session_id: UUID, write_interval_seconds: int) -> None:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        await execute_sql(
            conn,
            "UPDATE aio_auth_sessions SET last_seen = SYSTIMESTAMP WHERE session_id = :session_id "
            "AND revoked IS NULL AND last_seen <= SYSTIMESTAMP - NUMTODSINTERVAL(:write_interval, 'SECOND')",
            {"session_id": session_id.bytes, "write_interval": write_interval_seconds},
        )
        await conn.commit()


async def revoke_session(token_digest: bytes) -> None:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        await execute_sql(
            conn,
            "UPDATE aio_auth_sessions SET revoked = COALESCE(revoked, SYSTIMESTAMP) WHERE token_digest = :token_digest",
            {"token_digest": token_digest},
        )
        await conn.commit()


async def revoke_user_sessions(user_id: UUID) -> None:
    pool = require_core_pool()
    async with pool.acquire() as conn:
        await execute_sql(
            conn,
            "UPDATE aio_auth_sessions SET revoked = COALESCE(revoked, SYSTIMESTAMP) "
            "WHERE user_id = :user_id AND revoked IS NULL",
            {"user_id": user_id.bytes},
        )
        await conn.commit()


async def recover_oidc_admin_subject(oidc_subject: str) -> None:
    """Replace the reserved OIDC Admin subject and revoke its sessions."""
    if not oidc_subject:
        raise ValueError("Replacement OIDC Admin subject is required")
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT auth_mode, oidc_admin_subject FROM aio_auth_authority WHERE authority_id = 1",
            max_rows=1,
        )
        if not rows:
            raise ValueError("Authentication authority was not found")
        auth_mode, old_subject = rows[0]
        if auth_mode != "OIDC":
            raise ValueError("OIDC Admin recovery requires OIDC mode")
        await execute_sql(
            conn,
            "UPDATE aio_auth_authority SET oidc_admin_subject = :replacement, "
            "last_validated = SYSTIMESTAMP WHERE authority_id = 1",
            {"replacement": oidc_subject},
        )
        await execute_sql(
            conn,
            "UPDATE aio_users SET subject = :replacement, updated = SYSTIMESTAMP "
            "WHERE user_id = :user_id AND role = 'ADMIN'",
            {"replacement": oidc_subject, "user_id": ADMIN_USER_ID.bytes},
        )
        await execute_sql(
            conn,
            "UPDATE aio_auth_sessions SET revoked = COALESCE(revoked, SYSTIMESTAMP) "
            "WHERE user_id = :user_id AND revoked IS NULL",
            {"user_id": ADMIN_USER_ID.bytes},
        )
        await execute_sql(
            conn,
            "INSERT INTO aio_auth_audit (event_id, event_type, user_id, old_identity, new_identity) "
            "VALUES (:event_id, 'ADMIN_RECOVERY', :user_id, :old_identity, :new_identity)",
            {
                "event_id": uuid4().bytes,
                "user_id": ADMIN_USER_ID.bytes,
                "old_identity": old_subject,
                "new_identity": oidc_subject,
            },
        )
        await conn.commit()


async def _cleanup_expired_sessions(conn: oracledb.AsyncConnection, batch_size: int) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    async with conn.cursor() as cursor:
        await cursor.execute(
            "DELETE FROM aio_auth_sessions WHERE session_id IN ("
            "SELECT session_id FROM aio_auth_sessions "
            "WHERE expires <= SYSTIMESTAMP OR revoked IS NOT NULL "
            "FETCH FIRST :batch_size ROWS ONLY)",
            {"batch_size": batch_size},
        )
        return cursor.rowcount


async def cleanup_expired_sessions(batch_size: int = SESSION_CLEANUP_BATCH_SIZE) -> int:
    """Delete a bounded batch of unusable sessions."""
    pool = require_core_pool()
    async with pool.acquire() as conn:
        count = await _cleanup_expired_sessions(conn, batch_size)
        await conn.commit()
    return count


async def bind_authority(app_settings: Settings = settings) -> AuthAuthority:
    """Bind an uninitialized CORE schema to the configured deployment authority."""
    admin_database_identity = _admin_database_identity(app_settings)
    identity = await authority_identity()
    expected = _configured_authority(app_settings, identity)
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT auth_mode, schema_version, database_identity, application_schema, "
            "oidc_issuer, oidc_admin_subject, initialized, last_validated "
            "FROM aio_auth_authority",
            max_rows=2,
        )
        if rows:
            existing = tuple(rows[0][:6]) if len(rows) == 1 else ()
            if existing != expected:
                raise ValueError("Authentication authority does not match the configured deployment")
        else:
            await execute_sql(
                conn,
                "INSERT INTO aio_auth_authority (authority_id, auth_mode, schema_version, "
                "database_identity, application_schema, oidc_issuer, oidc_admin_subject) "
                "VALUES (1, :auth_mode, :schema_version, :database_identity, :application_schema, "
                ":oidc_issuer, :oidc_admin_subject)",
                dict(
                    zip(
                        (
                            "auth_mode",
                            "schema_version",
                            "database_identity",
                            "application_schema",
                            "oidc_issuer",
                            "oidc_admin_subject",
                        ),
                        expected,
                        strict=True,
                    )
                ),
            )

        auth_source = "OIDC" if app_settings.auth_mode == "oidc" else "DATABASE_END_USER"
        issuer = app_settings.oidc_issuer if app_settings.auth_mode == "oidc" else None
        subject = app_settings.oidc_admin_subject if app_settings.auth_mode == "oidc" else None
        await execute_sql(
            conn,
            "MERGE INTO aio_users target USING (SELECT :user_id user_id FROM dual) source "
            "ON (target.user_id = source.user_id) "
            "WHEN NOT MATCHED THEN INSERT (user_id, username, auth_source, database_username, "
            "issuer, subject, display_name, role, status) VALUES (:user_id, 'Admin', :auth_source, "
            ":database_username, :issuer, :subject, 'Admin', 'ADMIN', 'ACTIVE')",
            {
                "user_id": ADMIN_USER_ID.bytes,
                "auth_source": auth_source,
                "database_username": admin_database_identity,
                "issuer": issuer,
                "subject": subject,
            },
        )
        await conn.commit()
    return await verify_authority(app_settings)


async def verify_authority(app_settings: Settings = settings) -> AuthAuthority:
    """Verify immutable authority, Admin identity, and session hygiene."""
    admin_database_identity = _admin_database_identity(app_settings)
    identity = await authority_identity()
    expected = _configured_authority(app_settings, identity)
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT auth_mode, schema_version, database_identity, application_schema, "
            "oidc_issuer, oidc_admin_subject, initialized, last_validated "
            "FROM aio_auth_authority",
            max_rows=2,
        )
        if not rows or len(rows) != 1 or tuple(rows[0][:6]) != expected:
            raise ValueError("Authentication authority does not match the configured deployment")
        authority_row = rows[0]
        admin_rows = await execute_sql(
            conn,
            "SELECT database_username, auth_source, issuer, subject FROM aio_users "
            "WHERE user_id = :user_id AND role = 'ADMIN' AND status = 'ACTIVE'",
            {"user_id": ADMIN_USER_ID.bytes},
            max_rows=1,
        )
        expected_admin = (
            admin_database_identity,
            "OIDC" if app_settings.auth_mode == "oidc" else "DATABASE_END_USER",
            app_settings.oidc_issuer if app_settings.auth_mode == "oidc" else None,
            app_settings.oidc_admin_subject if app_settings.auth_mode == "oidc" else None,
        )
        if not admin_rows or tuple(admin_rows[0]) != expected_admin:
            raise ValueError("Reserved Admin identity does not match authentication authority")
        await execute_sql(
            conn,
            "UPDATE aio_auth_authority SET last_validated = SYSTIMESTAMP WHERE authority_id = 1",
        )
        await _cleanup_expired_sessions(conn, SESSION_CLEANUP_BATCH_SIZE)
        await conn.commit()
    row = authority_row
    return AuthAuthority(
        auth_mode=row[0].lower(),
        schema_version=row[1],
        database_identity=row[2],
        application_schema=row[3],
        oidc_issuer=row[4],
        oidc_admin_subject=row[5],
        initialized=row[6],
        last_validated=row[7],
    )
