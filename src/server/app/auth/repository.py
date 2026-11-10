"""Oracle repositories for authentication users, sessions, and authority."""

from uuid import UUID

import oracledb
from pydantic import SecretStr

from server.app.auth.models import AuthAuthority, AuthSession, AuthUser
from server.app.core.settings import Settings, settings
from server.app.database.config import require_core_pool
from server.app.database.sql import execute_sql

SCHEMA_VERSION = 1
ADMIN_USER_ID = UUID("f4304c28-4bf6-5e7d-a284-33cc0a5a6c01")
SESSION_CLEANUP_BATCH_SIZE = 500


async def authority_identity() -> tuple[str, str]:
    """Return the stable database and application-schema identity for CORE."""
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT COALESCE(SYS_CONTEXT('USERENV', 'DB_UNIQUE_NAME'), "
            "SYS_CONTEXT('USERENV', 'DB_NAME')), "
            "COALESCE(SYS_CONTEXT('USERENV', 'CON_NAME'), 'NONCDB'), "
            "SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL",
            max_rows=1,
        )
    if not rows or not all(rows[0]):
        raise RuntimeError("CORE logical identity is unavailable")
    database_identity = f"{rows[0][0]}:{rows[0][1]}".upper()
    return database_identity, str(rows[0][2]).upper()


def _configured_authority(app_settings: Settings, identity: tuple[str, str]) -> tuple:
    return (
        app_settings.installation_id,
        app_settings.auth_mode.upper(),
        SCHEMA_VERSION,
        identity[0],
        identity[1],
        app_settings.admin_database_username.upper() if app_settings.admin_database_username else None,
        app_settings.oidc_issuer if app_settings.auth_mode == "oidc" else None,
        app_settings.oidc_admin_subject if app_settings.auth_mode == "oidc" else None,
    )


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
    row = rows[0]
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
    if not app_settings.installation_id or not app_settings.admin_database_username:
        raise ValueError("Installation ID and Admin database username are required")
    identity = await authority_identity()
    expected = _configured_authority(app_settings, identity)
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT installation_id, auth_mode, schema_version, database_identity, application_schema, "
            "admin_database_username, oidc_issuer, oidc_admin_subject, initialized, last_validated "
            "FROM aio_auth_authority",
            max_rows=2,
        )
        if rows:
            if len(rows) != 1 or tuple(rows[0][:8]) != expected:
                raise ValueError("Authentication authority does not match the configured deployment")
        else:
            await execute_sql(
                conn,
                "INSERT INTO aio_auth_authority (installation_id, auth_mode, schema_version, "
                "database_identity, application_schema, admin_database_username, oidc_issuer, "
                "oidc_admin_subject) VALUES (:installation_id, :auth_mode, :schema_version, "
                ":database_identity, :application_schema, :admin_database_username, :oidc_issuer, "
                ":oidc_admin_subject)",
                dict(
                    zip(
                        (
                            "installation_id",
                            "auth_mode",
                            "schema_version",
                            "database_identity",
                            "application_schema",
                            "admin_database_username",
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
                "database_username": app_settings.admin_database_username.upper(),
                "issuer": issuer,
                "subject": subject,
            },
        )
        await conn.commit()
    return await verify_authority(app_settings)


async def verify_authority(app_settings: Settings = settings) -> AuthAuthority:
    """Verify immutable authority, Admin mapping, package, and session hygiene."""
    if not app_settings.installation_id or not app_settings.admin_database_username:
        raise ValueError("Installation ID and Admin database username are required")
    identity = await authority_identity()
    expected = _configured_authority(app_settings, identity)
    pool = require_core_pool()
    async with pool.acquire() as conn:
        rows = await execute_sql(
            conn,
            "SELECT installation_id, auth_mode, schema_version, database_identity, application_schema, "
            "admin_database_username, oidc_issuer, oidc_admin_subject, initialized, last_validated "
            "FROM aio_auth_authority",
            max_rows=2,
        )
        if not rows or len(rows) != 1 or tuple(rows[0][:8]) != expected:
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
            app_settings.admin_database_username.upper(),
            "OIDC" if app_settings.auth_mode == "oidc" else "DATABASE_END_USER",
            app_settings.oidc_issuer if app_settings.auth_mode == "oidc" else None,
            app_settings.oidc_admin_subject if app_settings.auth_mode == "oidc" else None,
        )
        if not admin_rows or tuple(admin_rows[0]) != expected_admin:
            raise ValueError("Reserved Admin database mapping does not match authentication authority")
        package_rows = await execute_sql(
            conn,
            "SELECT object_type FROM user_objects WHERE object_name = 'AIO_AUTH_ADMIN' "
            "AND object_type IN ('PACKAGE', 'PACKAGE BODY') AND status = 'VALID'",
            max_rows=2,
        )
        if {row[0] for row in package_rows or []} != {"PACKAGE", "PACKAGE BODY"}:
            raise ValueError("Authentication provisioning package is missing or invalid")
        await execute_sql(
            conn,
            "UPDATE aio_auth_authority SET last_validated = SYSTIMESTAMP WHERE installation_id = :installation_id",
            {"installation_id": app_settings.installation_id},
        )
        await _cleanup_expired_sessions(conn, SESSION_CLEANUP_BATCH_SIZE)
        await conn.commit()
    row = authority_row
    return AuthAuthority(
        installation_id=row[0],
        auth_mode=row[1].lower(),
        schema_version=row[2],
        database_identity=row[3],
        application_schema=row[4],
        admin_database_username=row[5],
        oidc_issuer=row[6],
        oidc_admin_subject=row[7],
        initialized=row[8],
        last_validated=row[9],
    )
