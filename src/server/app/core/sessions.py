"""Principal-owned session selection and transport adaptation."""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

import oracledb
from fastapi import HTTPException, status

from server.app.database.config import get_core_pool
from server.app.database.sql import execute_sql

if TYPE_CHECKING:
    from server.app.core.auth import Principal

_DEFAULT_SESSION_ID = "default"
_owners: dict[str, tuple[str, str]] = {}
_owners_lock = threading.Lock()
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OwnedSession:
    """Authenticated principal plus its selected opaque working session."""

    principal: Principal
    session_id: str

    @property
    def client_key(self) -> str:
        """Internal client key; never expose this transport/cache namespace."""
        owner = "\0".join(self.principal.ownership_key).encode()
        owner_digest = hashlib.sha256(owner).hexdigest()[:32]
        session_digest = hashlib.sha256(self.session_id.encode()).hexdigest()[:32]
        return f"principal-{owner_digest}-{session_digest}"


async def select_owned_session(principal: Principal, supplied_session_id: str | None) -> OwnedSession:
    """Bind a selected session to *principal*, rejecting cross-owner reuse."""
    session_id = (supplied_session_id or _DEFAULT_SESSION_ID).strip()
    if not session_id or len(session_id) > 255 or any(c in session_id for c in "/\\"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid session ID")
    if session_id != _DEFAULT_SESSION_ID:
        await _claim_durable_session(principal, session_id)
        with _owners_lock:
            owner = _owners.setdefault(session_id, principal.ownership_key)
        if owner != principal.ownership_key:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return OwnedSession(principal=principal, session_id=session_id)


async def _claim_durable_session(principal: Principal, session_id: str) -> None:
    """Persist the owner claim when CORE is available; memory is only a fallback."""
    pool = get_core_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            rows = await execute_sql(
                conn,
                "SELECT issuer, subject FROM aio_principal_sessions WHERE session_id = :session_id",
                {"session_id": session_id},
            )
            if rows:
                if tuple(rows[0]) != principal.ownership_key:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
                return
            await execute_sql(
                conn,
                """
                INSERT INTO aio_principal_sessions (session_id, issuer, subject, created, updated)
                VALUES (:session_id, :issuer, :subject, SYSTIMESTAMP, SYSTIMESTAMP)
                """,
                {"session_id": session_id, "issuer": principal.issuer, "subject": principal.subject},
            )
            await conn.commit()
    except oracledb.IntegrityError:
        # A different replica may have claimed the same session after the
        # read above. Roll back the failed insert and let the durable row
        # decide ownership rather than falling back to process-local state.
        async with pool.acquire() as conn:
            await conn.rollback()
            rows = await execute_sql(
                conn,
                "SELECT issuer, subject FROM aio_principal_sessions WHERE session_id = :session_id",
                {"session_id": session_id},
            )
        if not rows or tuple(rows[0]) != principal.ownership_key:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    except HTTPException:
        raise
    except Exception as exc:
        # CORE remains optional for local operation; do not turn an unavailable
        # persistence store into an authentication bypass or a global outage.
        LOGGER.warning("Unable to persist principal session ownership: %s", exc)
