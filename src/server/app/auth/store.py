"""CORE-backed persistence for the embedded authentication gateway."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Protocol

import oracledb

from server.app.auth.models import (
    AccessToken,
    AuthClient,
    AuthenticatedIdentity,
    AuthorizationCode,
    LocalAccount,
    LoginSession,
    LoginTransaction,
    PrincipalRecord,
    SigningKey,
)
from server.app.database.config import get_core_pool
from server.app.database.sql import execute_sql


class AuthStore(Protocol):
    """Persistence operations required by all authentication sources."""

    async def resolve_identity(self, identity: AuthenticatedIdentity, source: str) -> PrincipalRecord: ...

    async def get_principal(self, principal_id: str) -> PrincipalRecord | None: ...

    async def list_principals(self) -> list[PrincipalRecord]: ...

    async def set_principal_active(self, principal_id: str, active: bool) -> None: ...

    async def set_role(self, principal_id: str, role: str, source: str, enabled: bool) -> None: ...

    async def get_local_account(self, username: str) -> LocalAccount | None: ...

    async def save_local_account(self, account: LocalAccount) -> None: ...

    async def save_client(self, client: AuthClient) -> None: ...

    async def get_client(self, client_id: str) -> AuthClient | None: ...

    async def save_code(self, code: AuthorizationCode) -> None: ...

    async def get_code(self, digest: str) -> AuthorizationCode | None: ...

    async def mark_code_used(self, digest: str) -> bool: ...

    async def save_login_session(self, session: LoginSession) -> None: ...

    async def get_login_session(self, digest: str) -> LoginSession | None: ...

    async def revoke_login_session(self, digest: str) -> None: ...

    async def save_access_token(self, token: AccessToken) -> None: ...

    async def get_access_token(self, digest: str) -> AccessToken | None: ...

    async def revoke_access_tokens(self, principal_id: str) -> None: ...

    async def save_transaction(self, transaction: LoginTransaction) -> None: ...

    async def consume_transaction(self, state: str) -> LoginTransaction | None: ...

    async def get_signing_key(self) -> SigningKey | None: ...

    async def save_signing_key(self, key: SigningKey) -> None: ...


class OracleAuthStore:
    """Oracle-backed gateway state shared by every Server replica."""

    @staticmethod
    def _pool():
        pool = get_core_pool()
        if pool is None:
            raise RuntimeError("End-user authentication requires an available CORE database")
        return pool

    async def resolve_identity(self, identity: AuthenticatedIdentity, source: str) -> PrincipalRecord:
        pool = self._pool()
        async with pool.acquire() as conn:
            rows = await execute_sql(
                conn,
                """
                SELECT principal_id FROM aio_principal_identities
                 WHERE issuer = :issuer AND subject = :subject
                """,
                {"issuer": identity.issuer, "subject": identity.subject},
            )
            if rows:
                principal_id = rows[0][0]
                await execute_sql(
                    conn,
                    """
                    UPDATE aio_principals
                       SET display_name = :display_name, email = :email, updated = SYSTIMESTAMP
                     WHERE principal_id = :principal_id
                    """,
                    {
                        "principal_id": principal_id,
                        "display_name": identity.display_name,
                        "email": identity.email,
                    },
                )
            else:
                principal_id = str(uuid.uuid4())
                try:
                    await execute_sql(
                        conn,
                        """
                        INSERT INTO aio_principals (principal_id, display_name, email, active, created, updated)
                        VALUES (:principal_id, :display_name, :email, TRUE, SYSTIMESTAMP, SYSTIMESTAMP)
                        """,
                        {
                            "principal_id": principal_id,
                            "display_name": identity.display_name,
                            "email": identity.email,
                        },
                    )
                    await execute_sql(
                        conn,
                        """
                        INSERT INTO aio_principal_identities (principal_id, issuer, subject, last_login, created)
                        VALUES (:principal_id, :issuer, :subject, SYSTIMESTAMP, SYSTIMESTAMP)
                        """,
                        {"principal_id": principal_id, "issuer": identity.issuer, "subject": identity.subject},
                    )
                except oracledb.IntegrityError:
                    await conn.rollback()
                    rows = await execute_sql(
                        conn,
                        """
                        SELECT principal_id FROM aio_principal_identities
                         WHERE issuer = :issuer AND subject = :subject
                        """,
                        {"issuer": identity.issuer, "subject": identity.subject},
                    )
                    if not rows:
                        raise
                    principal_id = rows[0][0]
            await execute_sql(
                conn,
                """
                UPDATE aio_principal_identities SET last_login = SYSTIMESTAMP
                 WHERE issuer = :issuer AND subject = :subject
                """,
                {"issuer": identity.issuer, "subject": identity.subject},
            )
            await execute_sql(
                conn,
                "DELETE FROM aio_principal_roles WHERE principal_id = :principal_id AND source = :source",
                {"principal_id": principal_id, "source": source},
            )
            for role in identity.roles:
                await execute_sql(
                    conn,
                    """
                    INSERT INTO aio_principal_roles (principal_id, role, source, created)
                    VALUES (:principal_id, :role, :source, SYSTIMESTAMP)
                    """,
                    {"principal_id": principal_id, "role": role, "source": source},
                )
            await conn.commit()
        principal = await self.get_principal(principal_id)
        if principal is None:
            raise RuntimeError("Authentication principal could not be loaded")
        return principal

    async def get_principal(self, principal_id: str) -> PrincipalRecord | None:
        rows = await self._query(
            "SELECT principal_id, display_name, email, active FROM aio_principals WHERE principal_id = :principal_id",
            {"principal_id": principal_id},
        )
        if not rows:
            return None
        stored_id, display_name, email, active = rows[0]
        role_rows = await self._query(
            "SELECT role FROM aio_principal_roles WHERE principal_id = :principal_id", {"principal_id": stored_id}
        )
        return PrincipalRecord(stored_id, display_name, email, bool(active), frozenset(row[0] for row in role_rows))

    async def list_principals(self) -> list[PrincipalRecord]:
        rows = await self._query("SELECT principal_id FROM aio_principals ORDER BY display_name")
        principals = [await self.get_principal(row[0]) for row in rows]
        return [principal for principal in principals if principal is not None]

    async def set_principal_active(self, principal_id: str, active: bool) -> None:
        await self._execute(
            "UPDATE aio_principals SET active = :active, updated = SYSTIMESTAMP WHERE principal_id = :principal_id",
            {"principal_id": principal_id, "active": active},
        )

    async def set_role(self, principal_id: str, role: str, source: str, enabled: bool) -> None:
        if enabled:
            await self._execute(
                """
                MERGE INTO aio_principal_roles target
                USING (SELECT :principal_id AS principal_id, :role AS role, :source AS source FROM dual) item
                   ON (target.principal_id = item.principal_id
                       AND target.role = item.role
                       AND target.source = item.source)
                WHEN NOT MATCHED THEN INSERT (principal_id, role, source, created)
                    VALUES (item.principal_id, item.role, item.source, SYSTIMESTAMP)
                """,
                {"principal_id": principal_id, "role": role, "source": source},
            )
            return
        await self._execute(
            "DELETE FROM aio_principal_roles WHERE principal_id = :principal_id AND role = :role AND source = :source",
            {"principal_id": principal_id, "role": role, "source": source},
        )

    async def get_local_account(self, username: str) -> LocalAccount | None:
        rows = await self._query(
            "SELECT principal_id, username, password_hash FROM aio_local_accounts WHERE username = :username",
            {"username": username},
        )
        return LocalAccount(*rows[0]) if rows else None

    async def save_local_account(self, account: LocalAccount) -> None:
        await self._execute(
            """
            MERGE INTO aio_local_accounts target
            USING (SELECT :principal_id AS principal_id FROM dual) item
               ON (target.principal_id = item.principal_id)
            WHEN MATCHED THEN UPDATE SET username = :username, password_hash = :password_hash, updated = SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT (principal_id, username, password_hash, created, updated)
                VALUES (:principal_id, :username, :password_hash, SYSTIMESTAMP, SYSTIMESTAMP)
            """,
            {
                "principal_id": account.principal_id,
                "username": account.username,
                "password_hash": account.password_hash,
            },
        )

    async def save_client(self, client: AuthClient) -> None:
        await self._execute(
            """
            MERGE INTO aio_auth_clients target
            USING (SELECT :client_id AS client_id FROM dual) item ON (target.client_id = item.client_id)
            WHEN MATCHED THEN UPDATE SET redirect_uris = :redirect_uris, allowed_scopes = :allowed_scopes,
                is_public = :is_public, updated = SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT (client_id, redirect_uris, allowed_scopes, is_public, created, updated)
                VALUES (:client_id, :redirect_uris, :allowed_scopes, :is_public, SYSTIMESTAMP, SYSTIMESTAMP)
            """,
            {
                "client_id": client.client_id,
                "redirect_uris": json.dumps(sorted(client.redirect_uris)),
                "allowed_scopes": json.dumps(sorted(client.allowed_scopes)),
                "is_public": client.public,
            },
        )

    async def get_client(self, client_id: str) -> AuthClient | None:
        rows = await self._query(
            """
            SELECT client_id, redirect_uris, allowed_scopes, is_public
              FROM aio_auth_clients WHERE client_id = :client_id
            """,
            {"client_id": client_id},
        )
        if not rows:
            return None
        stored_id, redirect_uris, scopes, public = rows[0]
        return AuthClient(stored_id, frozenset(json.loads(redirect_uris)), frozenset(json.loads(scopes)), bool(public))

    async def save_code(self, code: AuthorizationCode) -> None:
        await self._execute(
            """
            INSERT INTO aio_auth_codes
                (code_digest, client_id, principal_id, redirect_uri, scope, nonce,
                 code_challenge, expires_at, used, created)
            VALUES (:digest, :client_id, :principal_id, :redirect_uri, :scope, :nonce, :code_challenge,
                    :expires_at, FALSE, SYSTIMESTAMP)
            """,
            {
                "digest": code.digest,
                "client_id": code.client_id,
                "principal_id": code.principal_id,
                "redirect_uri": code.redirect_uri,
                "scope": code.scope,
                "nonce": code.nonce,
                "code_challenge": code.code_challenge,
                "expires_at": code.expires_at,
            },
        )

    async def get_code(self, digest: str) -> AuthorizationCode | None:
        rows = await self._query(
            """
            SELECT code_digest, client_id, principal_id, redirect_uri, scope, nonce, code_challenge, expires_at, used
              FROM aio_auth_codes WHERE code_digest = :digest
            """,
            {"digest": digest},
        )
        return AuthorizationCode(*rows[0]) if rows else None

    async def mark_code_used(self, digest: str) -> bool:
        return await self._changed(
            """
            UPDATE aio_auth_codes SET used = TRUE
             WHERE code_digest = :digest AND used = FALSE AND expires_at > SYSTIMESTAMP
            """,
            {"digest": digest},
        )

    async def save_login_session(self, session: LoginSession) -> None:
        await self._execute(
            """
            INSERT INTO aio_auth_login_sessions (session_digest, principal_id, expires_at, revoked, created)
            VALUES (:digest, :principal_id, :expires_at, FALSE, SYSTIMESTAMP)
            """,
            {"digest": session.digest, "principal_id": session.principal_id, "expires_at": session.expires_at},
        )

    async def get_login_session(self, digest: str) -> LoginSession | None:
        rows = await self._query(
            """
            SELECT session_digest, principal_id, expires_at, revoked
              FROM aio_auth_login_sessions
             WHERE session_digest = :digest AND expires_at > SYSTIMESTAMP
            """,
            {"digest": digest},
        )
        return LoginSession(*rows[0]) if rows else None

    async def revoke_login_session(self, digest: str) -> None:
        await self._execute(
            "UPDATE aio_auth_login_sessions SET revoked = TRUE WHERE session_digest = :digest", {"digest": digest}
        )

    async def save_access_token(self, token: AccessToken) -> None:
        await self._execute(
            """
            INSERT INTO aio_auth_access_tokens
                (token_digest, principal_id, client_id, scope, expires_at, revoked, created)
            VALUES (:digest, :principal_id, :client_id, :scope, :expires_at, FALSE, SYSTIMESTAMP)
            """,
            {
                "digest": token.digest,
                "principal_id": token.principal_id,
                "client_id": token.client_id,
                "scope": token.scope,
                "expires_at": token.expires_at,
            },
        )

    async def get_access_token(self, digest: str) -> AccessToken | None:
        rows = await self._query(
            """
            SELECT token_digest, principal_id, client_id, scope, expires_at, revoked
              FROM aio_auth_access_tokens WHERE token_digest = :digest AND expires_at > SYSTIMESTAMP
            """,
            {"digest": digest},
        )
        return AccessToken(*rows[0]) if rows else None

    async def revoke_access_tokens(self, principal_id: str) -> None:
        await self._execute(
            "UPDATE aio_auth_access_tokens SET revoked = TRUE WHERE principal_id = :principal_id",
            {"principal_id": principal_id},
        )

    async def save_transaction(self, transaction: LoginTransaction) -> None:
        await self._execute(
            """
            INSERT INTO aio_auth_transactions
                (state, downstream_state, client_id, redirect_uri, scope, nonce, code_challenge,
                 upstream_nonce, upstream_verifier, expires_at, used, created)
            VALUES (:state, :downstream_state, :client_id, :redirect_uri, :scope, :nonce,
                    :code_challenge, :upstream_nonce,
                    :upstream_verifier, :expires_at, FALSE, SYSTIMESTAMP)
            """,
            {
                "state": transaction.state,
                "downstream_state": transaction.downstream_state,
                "client_id": transaction.client_id,
                "redirect_uri": transaction.redirect_uri,
                "scope": transaction.scope,
                "nonce": transaction.nonce,
                "code_challenge": transaction.code_challenge,
                "upstream_nonce": transaction.upstream_nonce,
                "upstream_verifier": transaction.upstream_verifier,
                "expires_at": transaction.expires_at,
            },
        )

    async def consume_transaction(self, state: str) -> LoginTransaction | None:
        pool = self._pool()
        async with pool.acquire() as conn:
            rows = await execute_sql(
                conn,
                """
                SELECT state, downstream_state, client_id, redirect_uri, scope, nonce, code_challenge,
                       upstream_nonce, upstream_verifier, expires_at
                 FROM aio_auth_transactions
                 WHERE state = :state AND used = FALSE AND expires_at > SYSTIMESTAMP
                   FOR UPDATE
                """,
                {"state": state},
            )
            if not rows:
                return None
            await execute_sql(
                conn,
                "UPDATE aio_auth_transactions SET used = TRUE WHERE state = :state AND used = FALSE",
                {"state": state},
            )
            await conn.commit()
        return LoginTransaction(*rows[0])

    async def get_signing_key(self) -> SigningKey | None:
        rows = await self._query(
            "SELECT key_id, private_key_pem FROM aio_auth_signing_keys WHERE active = TRUE ORDER BY created"
        )
        if not rows:
            return None
        key_id, private_key_pem = rows[0]
        return SigningKey(
            key_id, private_key_pem.encode() if isinstance(private_key_pem, str) else bytes(private_key_pem)
        )

    async def save_signing_key(self, key: SigningKey) -> None:
        pool = self._pool()
        async with pool.acquire() as conn:
            await execute_sql(conn, "LOCK TABLE aio_auth_signing_keys IN EXCLUSIVE MODE")
            rows = await execute_sql(conn, "SELECT key_id FROM aio_auth_signing_keys WHERE active = TRUE")
            if not rows:
                await execute_sql(
                    conn,
                    """
                    INSERT INTO aio_auth_signing_keys (key_id, private_key_pem, active, created)
                    VALUES (:key_id, :private_key_pem, TRUE, SYSTIMESTAMP)
                    """,
                    {"key_id": key.key_id, "private_key_pem": key.private_key_pem.decode()},
                )
            await conn.commit()

    async def _query(self, sql: str, binds: dict | None = None) -> list:
        pool = self._pool()
        async with pool.acquire() as conn:
            return await execute_sql(conn, sql, binds) or []

    async def _execute(self, sql: str, binds: dict | None = None) -> None:
        pool = self._pool()
        async with pool.acquire() as conn:
            await execute_sql(conn, sql, binds)
            await conn.commit()

    async def _changed(self, sql: str, binds: dict) -> bool:
        pool = self._pool()
        async with pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, binds)
            changed = cursor.rowcount == 1
            await conn.commit()
        return changed


def utc_now() -> datetime:
    """Return a timezone-aware current time for in-memory expiry checks."""
    return datetime.now(UTC)
