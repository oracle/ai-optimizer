"""Application-managed Oracle end-user lifecycle."""

from uuid import UUID, uuid4

import oracledb

from server.app.auth import repository
from server.app.auth.local import database_account_status, invalidate_account_status, normalize_database_username
from server.app.auth.models import AuthUser
from server.app.auth.provisioning import local_user_management_issues
from server.app.core.settings import settings
from server.app.database.config import require_core_pool


def require_local_users_mode() -> None:
    if settings.auth_mode != "local_users":
        raise LookupError("Local user management is unavailable")


async def require_local_user_management() -> None:
    require_local_users_mode()
    pool = require_core_pool()
    async with pool.acquire() as conn:
        issues = await local_user_management_issues(conn)
    if issues:
        raise LookupError(f"Local user management is unavailable: {', '.join(issues)}")


async def _call_admin(action: str, username: str, password: str | None = None) -> None:
    await require_local_user_management()
    pool = require_core_pool()
    async with pool.acquire() as conn, conn.cursor() as cursor:
        if action == "CREATE":
            await cursor.callproc("AIO_AUTH_ADMIN.CREATE_USER", [username, password])
        else:
            await cursor.callproc("AIO_AUTH_ADMIN.ALTER_USER", [username, action, password])


async def create_member(
    username: str,
    password: str,
    display_name: str | None,
    email: str | None,
) -> AuthUser:
    require_local_users_mode()
    canonical = normalize_database_username(username)
    if await repository.get_user_by_database_username(canonical) is not None:
        raise ValueError("Authentication member already exists")

    status = await database_account_status(canonical)
    created = status == "MISSING"
    if status == "UNMANAGED":
        raise ValueError("Database end user is not managed by this application")
    if created:
        await _call_admin("CREATE", canonical, password)
    else:
        await _call_admin("RESET", canonical, password)
    try:
        user = await repository.create_database_member(uuid4(), canonical, display_name, email)
    except Exception:
        await _call_admin("LOCK", canonical)
        raise
    invalidate_account_status(canonical)
    return user


async def update_member(
    user_id: UUID,
    account_locked: bool | None,
    display_name: str | None,
    email: str | None,
) -> AuthUser:
    require_local_users_mode()
    user = await repository.get_user_by_id(user_id)
    if user is None or user.role != "member" or user.database_username is None:
        raise ValueError("Authentication member was not found")
    if account_locked is not None:
        await _call_admin("LOCK" if account_locked else "UNLOCK", user.database_username)
        invalidate_account_status(user.database_username)
        if account_locked:
            await repository.revoke_user_sessions(user.user_id)
    return await repository.update_database_member(user_id, display_name, email)


async def reset_member_password(user_id: UUID, password: str) -> AuthUser:
    require_local_users_mode()
    user = await repository.get_user_by_id(user_id)
    if user is None or user.role != "member" or user.database_username is None:
        raise ValueError("Authentication member was not found")
    await _call_admin("RESET", user.database_username, password)
    invalidate_account_status(user.database_username)
    await repository.revoke_user_sessions(user.user_id)
    return user


async def database_user_status(user: AuthUser) -> str:
    if user.database_username is None:
        return "MISSING"
    try:
        return await database_account_status(user.database_username)
    except oracledb.Error:
        raise RuntimeError("Database account status is unavailable") from None
