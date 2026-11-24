"""Oracle local-end-user authentication and opaque application sessions."""

import asyncio
import hashlib
import re
import secrets
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

import oracledb

from server.app.auth import repository
from server.app.auth.models import AuthUser, IssuedSession, Principal, RequestCredential
from server.app.auth.service import AuthAuthorityUnavailable, AuthenticationError, register_authenticator
from server.app.core.settings import settings
from server.app.database.config import CoreDatabaseUnavailable, _build_connect_args, require_core_pool
from server.app.database.schemas import DatabaseConfig

_TOKEN_BYTES = 32
_TOKEN_DOMAIN = b"aio-auth-session-v1\x00"
_USERNAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,127}")
_GENERIC_LOGIN_ERROR = "Database credentials are invalid or the account is unavailable"
_MAX_LOGIN_BACKOFF_SECONDS = 5.0
_MAX_LOGIN_ATTEMPT_KEYS = 10_000
_MAX_ACCOUNT_STATUS_CACHE_ENTRIES = 10_000
_MAX_CONCURRENT_LOGINS = 8
_LAST_SEEN_INTERVAL_SECONDS = min(60, max(1, settings.auth_session_idle_seconds // 2))


def normalize_database_username(username: str) -> str:
    if _USERNAME_RE.fullmatch(username) is None:
        raise AuthenticationError(_GENERIC_LOGIN_ERROR)
    return username.upper()


def session_token_digest(token: str) -> bytes:
    return hashlib.sha256(_TOKEN_DOMAIN + token.encode("ascii", errors="strict")).digest()


def _core_config() -> DatabaseConfig:
    for config in settings.database_configs:
        if config.alias.upper() == "CORE":
            return config
    raise AuthenticationError(_GENERIC_LOGIN_ERROR)


async def verify_database_credentials(username: str, password: str, new_password: str | None = None) -> str:
    """Verify an end-user credential through a short-lived direct connection."""
    canonical = normalize_database_username(username)
    core_config = _core_config()
    args = _build_connect_args(core_config)
    args["user"] = canonical
    args["password"] = password
    if new_password is not None:
        args["newpassword"] = new_password
    connection = None
    try:
        connection = await oracledb.connect_async(
            **args,
            tcp_connect_timeout=core_config.tcp_connect_timeout,
        )
    except (oracledb.Error, ValueError):
        raise AuthenticationError(_GENERIC_LOGIN_ERROR) from None
    finally:
        if connection is not None:
            await connection.close()
    return canonical


async def database_account_status(username: str) -> str:
    canonical = normalize_database_username(username)
    pool = require_core_pool()
    try:
        async with pool.acquire() as conn, conn.cursor() as cursor:
            status = cursor.var(str, size=128)
            await cursor.callproc("AIO_AUTH_ADMIN.ACCOUNT_STATUS", [canonical, status])
            value = status.getvalue()
    except oracledb.Error:
        user = await repository.get_user_by_database_username(canonical)
        if user is not None and user.role == "admin":
            return "OPEN"
        raise
    if str(value or "MISSING").upper() == "MISSING":
        user = await repository.get_user_by_database_username(canonical)
        if user is not None and user.role == "admin":
            return "OPEN"
    return str(value or "MISSING").upper()


class DatabaseSessionAuthenticator:
    """Validate opaque bearer sessions backed by shared CORE state."""

    def __init__(self) -> None:
        self._account_cache: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def invalidate_account(self, username: str) -> None:
        self._account_cache.pop(username.upper(), None)

    async def account_status(self, username: str, *, fresh: bool = False) -> str:
        canonical = username.upper()
        cached = self._account_cache.get(canonical)
        now = monotonic()
        if not fresh and cached is not None and cached[1] > now:
            return cached[0]
        status = await database_account_status(canonical)
        self._account_cache[canonical] = (status, now + settings.auth_account_status_cache_seconds)
        self._account_cache.move_to_end(canonical)
        while len(self._account_cache) > _MAX_ACCOUNT_STATUS_CACHE_ENTRIES:
            self._account_cache.popitem(last=False)
        return status

    async def authenticate(self, credential: RequestCredential) -> Principal:
        try:
            digest = session_token_digest(credential.value)
        except (UnicodeEncodeError, ValueError):
            raise AuthenticationError("Invalid bearer credential") from None
        try:
            result = await repository.get_active_session_user(digest, settings.auth_session_idle_seconds)
        except (CoreDatabaseUnavailable, oracledb.Error):
            raise AuthAuthorityUnavailable("Database authentication session authority is unavailable") from None
        if result is None:
            raise AuthenticationError("Invalid bearer credential")
        session, user = result
        database_username = user.database_username
        if database_username is None:
            raise AuthenticationError("Invalid bearer credential")
        try:
            account_open = await self.account_status(database_username) == "OPEN"
        except (CoreDatabaseUnavailable, oracledb.Error):
            raise AuthAuthorityUnavailable("Database account authority is unavailable") from None
        if not account_open:
            raise AuthenticationError("Invalid bearer credential")
        try:
            await repository.touch_session(session.session_id, _LAST_SEEN_INTERVAL_SECONDS)
        except (CoreDatabaseUnavailable, oracledb.Error):
            raise AuthAuthorityUnavailable("Database authentication session authority is unavailable") from None
        return Principal(
            user_id=user.user_id,
            subject=database_username,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            auth_source="database_end_user",
            database_username=database_username,
            roles=frozenset({user.role}),
        )


_DATABASE_AUTHENTICATOR = DatabaseSessionAuthenticator()
_LOGIN_LIMIT = asyncio.Semaphore(_MAX_CONCURRENT_LOGINS)


class _LoginAttemptLimiter:
    def __init__(self) -> None:
        self._failures: OrderedDict[tuple[str, str], tuple[int, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def wait(self, key: tuple[str, str]) -> None:
        async with self._lock:
            failure = self._failures.get(key)
        if failure is not None:
            await asyncio.sleep(max(0.0, failure[1] - monotonic()))

    async def failed(self, key: tuple[str, str]) -> None:
        async with self._lock:
            count = self._failures.get(key, (0, 0.0))[0] + 1
            backoff = min(0.25 * (2 ** min(count - 1, 5)), _MAX_LOGIN_BACKOFF_SECONDS)
            self._failures[key] = (count, monotonic() + backoff)
            self._failures.move_to_end(key)
            while len(self._failures) > _MAX_LOGIN_ATTEMPT_KEYS:
                self._failures.popitem(last=False)

    async def succeeded(self, key: tuple[str, str]) -> None:
        async with self._lock:
            self._failures.pop(key, None)


_LOGIN_ATTEMPTS = _LoginAttemptLimiter()


def initialize_database_authenticator() -> None:
    if settings.auth_mode == "local_users":
        register_authenticator("local_users", _DATABASE_AUTHENTICATOR)


def invalidate_account_status(username: str) -> None:
    _DATABASE_AUTHENTICATOR.invalidate_account(username)


def principal_for_user(user: AuthUser) -> Principal:
    if user.database_username is None:
        raise AuthenticationError(_GENERIC_LOGIN_ERROR)
    return Principal(
        user_id=user.user_id,
        subject=user.database_username,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        auth_source="database_end_user",
        database_username=user.database_username,
        roles=frozenset({user.role}),
    )


async def login_database_user(
    username: str,
    password: str,
    remote_address: str | None = None,
) -> tuple[IssuedSession, Principal]:
    canonical = normalize_database_username(username)
    attempt_key = (remote_address or "unknown", canonical)
    await _LOGIN_ATTEMPTS.wait(attempt_key)
    try:
        user = await repository.get_user_by_database_username(canonical)
        if user is None or user.status != "active":
            raise AuthenticationError(_GENERIC_LOGIN_ERROR)
        async with _LOGIN_LIMIT:
            await verify_database_credentials(canonical, password)
        if await _DATABASE_AUTHENTICATOR.account_status(canonical, fresh=True) != "OPEN":
            raise AuthenticationError(_GENERIC_LOGIN_ERROR)
    except AuthenticationError:
        await _LOGIN_ATTEMPTS.failed(attempt_key)
        raise
    await _LOGIN_ATTEMPTS.succeeded(attempt_key)

    token = secrets.token_urlsafe(_TOKEN_BYTES)
    expires = datetime.now(UTC) + timedelta(seconds=settings.auth_session_absolute_seconds)
    await repository.create_session(
        session_id=uuid4(),
        user_id=user.user_id,
        token_digest=session_token_digest(token),
        expires=expires,
        remote_address=remote_address,
        max_sessions=settings.auth_session_max_per_user,
    )
    return IssuedSession(token=token, expires=expires), principal_for_user(user)


async def change_database_password(username: str, current_password: str, new_password: str) -> None:
    canonical = normalize_database_username(username)
    user = await repository.get_user_by_database_username(canonical)
    if user is None or user.status != "active" or user.role == "admin":
        raise AuthenticationError(_GENERIC_LOGIN_ERROR)
    async with _LOGIN_LIMIT:
        await verify_database_credentials(canonical, current_password, new_password)
    invalidate_account_status(canonical)
    await repository.revoke_user_sessions(user.user_id)


async def logout_database_session(token: str) -> None:
    try:
        digest = session_token_digest(token)
    except (UnicodeEncodeError, ValueError):
        return
    await repository.revoke_session(digest)
