"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database configuration lookup utilities.
"""

import contextlib
import logging
import os
import re
from typing import Optional, TypeGuard

import oracledb

from server.app.core.paths import PROJECT_ROOT
from server.app.core.secrets import reveal
from server.app.core.settings import _client_store, _client_store_lock, resolve_client, settings

from .schemas import DatabaseConfig

LOGGER = logging.getLogger(__name__)
_CORE_TNS_ADMIN = PROJECT_ROOT / "server" / "tns_admin"
# Matches Oracle descriptor retry tokens tolerating insignificant whitespace
# (docs often show the spaced `(RETRY_COUNT = 5)` form). The schema preserves
# descriptor whitespace verbatim to avoid corrupting values like
# SSL_SERVER_CERT_DN, so this regex accepts it instead.
_RE_RETRY = re.compile(
    r"\(\s*retry_count\s*=\s*\d+\s*\)|\(\s*retry_delay\s*=\s*\d+\s*\)",
    re.IGNORECASE,
)


def _strip_retry_tokens(dsn: str) -> str:
    """Remove retry_count / retry_delay tokens from the structural part of
    a connect descriptor, leaving quoted values untouched.

    Quoted descriptor values may contain text that matches the retry-token
    regex (e.g. paths with parenthesised segments), so the scanner splits
    the DSN on unescaped double quotes and only applies the regex to
    segments that are outside any quoted region.
    """
    if not dsn:
        return dsn
    parts: list[str] = []
    segment_start = 0
    in_quote = False
    for i, ch in enumerate(dsn):
        if ch == '"':
            segment = dsn[segment_start:i]
            parts.append(segment if in_quote else _RE_RETRY.sub("", segment))
            parts.append(ch)
            in_quote = not in_quote
            segment_start = i + 1
    tail = dsn[segment_start:]
    parts.append(tail if in_quote else _RE_RETRY.sub("", tail))
    return "".join(parts)


def get_database_settings(db_configs: list[DatabaseConfig], alias: str) -> Optional[DatabaseConfig]:
    """Return the database config for the given alias, or ``None`` if not found."""
    for cfg in db_configs:
        if cfg.alias == alias:
            return cfg
    return None


def has_required_credentials(db_config: DatabaseConfig) -> bool:
    """Return True if the config has username, password, and dsn."""
    return all([db_config.username, db_config.password, db_config.dsn])


def _is_usable(db_config: Optional[DatabaseConfig]) -> TypeGuard[DatabaseConfig]:
    """Return True when *db_config* exists and has a live, usable pool (narrows None away)."""
    return db_config is not None and db_config.pool is not None and db_config.usable


def _build_connect_args(db_config: DatabaseConfig) -> dict:
    """Build the oracledb connection keyword arguments from a DatabaseConfig."""
    if not has_required_credentials(db_config):
        raise ValueError(f"Database alias {db_config.alias} missing credentials")

    config_dir = db_config.config_dir or os.environ.get("TNS_ADMIN") or str(_CORE_TNS_ADMIN)

    args: dict = {
        "user": db_config.username,
        "password": reveal(db_config.password),
        "dsn": _strip_retry_tokens(db_config.dsn or ""),
        "config_dir": config_dir,
    }
    if db_config.wallet_password:
        args["wallet_password"] = reveal(db_config.wallet_password)
    if db_config.wallet_location:
        args["wallet_location"] = db_config.wallet_location

    # Default wallet location to config directory when only a password is set
    if args.get("wallet_password") and not args.get("wallet_location"):
        args["wallet_location"] = args["config_dir"]

    return args


async def create_pool(db_config: DatabaseConfig) -> oracledb.AsyncConnectionPool:
    """Create and return an async oracledb connection pool."""
    try:
        connect_args = _build_connect_args(db_config)
    except ValueError:
        db_config.usable = False
        raise

    LOGGER.info("Connecting to Database alias=%s dsn=%s", db_config.alias, db_config.dsn)
    return oracledb.create_pool_async(
        **connect_args, min=1, max=settings.db_pool_size, increment=1, tcp_connect_timeout=db_config.tcp_connect_timeout
    )


def create_sync_connection(db_config: DatabaseConfig) -> oracledb.Connection:
    """Create a synchronous oracledb connection from a DatabaseConfig.

    Returns a plain synchronous connection (useful for LangChain OracleVS
    and other sync-only libraries).
    """
    return oracledb.connect(**_build_connect_args(db_config))


def get_core_pool() -> Optional[oracledb.AsyncConnectionPool]:
    """Return the CORE database connection pool, or ``None`` if unavailable."""

    core_cfg = get_database_settings(settings.database_configs, "CORE")
    return core_cfg.pool if _is_usable(core_cfg) else None


def get_client_db_config(client: str = "CONFIGURED") -> Optional[DatabaseConfig]:
    """Resolve a client string to its ``DatabaseConfig``.

    Returns the config when the associated pool exists and is usable,
    otherwise ``None``.
    """

    alias = resolve_client(client).database.alias
    db_config = get_database_settings(settings.database_configs, alias)
    return db_config if _is_usable(db_config) else None


def get_client_pool(client: str = "CONFIGURED") -> Optional[oracledb.AsyncConnectionPool]:
    """Resolve a client string to its async connection pool.

    Convenience wrapper that returns just the pool, or ``None`` if the
    database is not available or not usable.
    """
    db_config = get_client_db_config(client)
    return db_config.pool if db_config else None


# ---------------------------------------------------------------------------
# Deep Data Security: effective connection for chat-time read tools
# ---------------------------------------------------------------------------
class DdsConnectionError(Exception):
    """Raised when a Deep Data Security 'connect as' override is active but its
    managed connection is missing/unusable.

    Tool-path resolvers raise this **unchanged** — they never fall back to the
    schema owner (which would leak full, unmasked data). It is caught only at the
    chat/tool boundaries, which turn it into a user-facing error.
    """


def managed_marker(base_alias: str) -> str:
    """The ``managed_by`` value for a DDS connect-as connection owned by *base_alias*.

    Single source of the ``"dds:<base>"`` encoding (constructed at registration, matched
    on teardown) so the format lives in one place.
    """
    return f"dds:{base_alias}"


def _find_config_ci(alias: Optional[str], *, exclude_managed: bool = False) -> Optional[DatabaseConfig]:
    """Case-insensitive lookup in ``settings.database_configs``.

    With ``exclude_managed=True`` a DDS-managed (runtime-only) alias is treated as not found,
    so the user-facing database endpoints don't act on hidden connections.
    """
    if not alias:
        return None
    for cfg in settings.database_configs:
        if cfg.alias.lower() == alias.lower():
            return None if exclude_managed and cfg.managed_by else cfg
    return None


def resolve_effective_tool_alias(client: str = "CONFIGURED") -> str:
    """Return the database alias chat-time read tools (Vector Search, NL2SQL) should use.

    Owner alias when DDS is disabled or configured for a different base; the managed
    end-user alias when DDS is active for the current base. Raises ``DdsConnectionError``
    when DDS is active but its managed connection is missing/unusable (never falls back
    to the owner).
    """
    cs = resolve_client(client)
    owner_alias = cs.database.alias
    dds = cs.deep_data_security
    if not dds.enabled or dds.base_alias != owner_alias:
        return owner_alias
    managed = _find_config_ci(dds.alias)
    # The setting is client-supplied (PUT /settings field-merges deep_data_security), so the
    # alias alone is not trusted: the resolved config must be a DDS-managed connection *owned by
    # the current base*. This blocks a crafted/stale payload from routing tools at an ordinary
    # connection (managed_by=None) or a managed connection of another base (dds:OTHER).
    if managed is None or managed.managed_by != managed_marker(owner_alias) or not _is_usable(managed):
        raise DdsConnectionError(
            f"Deep Data Security connection unavailable for end user '{dds.end_user}'. "
            "Re-select the connect-as user in Tools → Deep Data Security."
        )
    return managed.alias


def get_tool_db_config(client: str = "CONFIGURED") -> Optional[DatabaseConfig]:
    """Resolve the ``DatabaseConfig`` chat-time read tools should use.

    Applies the DDS 'connect as' override (see ``resolve_effective_tool_alias``);
    returns ``None`` when the owner database itself is unavailable. Raises
    ``DdsConnectionError`` when DDS is active but its managed connection is unusable.
    """
    alias = resolve_effective_tool_alias(client)
    if alias == resolve_client(client).database.alias:
        return get_client_db_config(client)
    # Managed alias already validated as usable by resolve_effective_tool_alias.
    return _find_config_ci(alias)


def get_tool_pool(client: str = "CONFIGURED") -> Optional[oracledb.AsyncConnectionPool]:
    """Resolve the async connection pool chat-time read tools should use (DDS-aware)."""
    db_config = get_tool_db_config(client)
    return db_config.pool if db_config else None


def _reset_dds(cs) -> None:
    """Reset a ClientSettings' deep_data_security override in place."""
    dds = cs.deep_data_security
    dds.enabled = False
    dds.end_user = None
    dds.alias = None
    dds.base_alias = None


async def clear_dds_for(*, alias: Optional[str] = None, base_alias: Optional[str] = None) -> set[str]:
    """Tear down DDS-managed connection(s) and clear referencing client settings.

    A managed config matches when ``managed_by`` is set and it matches a provided criterion:
    the managed ``alias`` (case-insensitive, exact) or the owning ``base_alias``
    (``managed_by == f"dds:{base_alias}"``). There is intentionally **no** match-by-end-user:
    DDS end users are per-database accounts, so a same-named user on another base is a
    distinct connection and must never be swept up. Callers scope by exact ``alias`` (the
    current client/base) or by ``base_alias`` (a whole owner DB being removed/rotated).

    Closes matching pools, removes them from ``settings.database_configs``, and clears
    ``deep_data_security`` on ``settings.client_settings`` and every per-client copy whose
    managed alias was removed. Returns the set of removed aliases (lower-cased).

    **Locking:** the caller must hold ``_settings_lock`` (asyncio.Lock is non-reentrant).
    The client store is enumerated directly under ``_client_store_lock`` — this never calls
    ``resolve_client`` (which would create entries). It does **not** refresh the SQLcl proxy;
    the caller must ``await refresh_sqlcl_proxy()`` once after releasing the lock when the
    returned set is non-empty (keeps the slow rebuild out of the lock and batches it).
    """

    def _matches(cfg: DatabaseConfig) -> bool:
        if not cfg.managed_by:
            return False
        if alias and cfg.alias.lower() == alias.lower():
            return True
        return bool(base_alias and cfg.managed_by == managed_marker(base_alias))

    removed: set[str] = set()
    remaining: list[DatabaseConfig] = []
    for cfg in settings.database_configs:
        if _matches(cfg):
            await close_pool(cfg.pool)
            cfg.pool = None
            removed.add(cfg.alias.lower())
        else:
            remaining.append(cfg)
    if not removed:
        return removed
    settings.database_configs[:] = remaining

    def _clear_if_orphaned(cs) -> None:
        if cs.deep_data_security.alias and cs.deep_data_security.alias.lower() in removed:
            _reset_dds(cs)

    _clear_if_orphaned(settings.client_settings)
    with _client_store_lock:
        for cs in _client_store.values():
            _clear_if_orphaned(cs)
    return removed


async def close_pool(pool: Optional[oracledb.AsyncConnectionPool]) -> None:
    """Silently close a connection pool if it is not None."""
    if pool is not None:
        with contextlib.suppress(oracledb.Error):
            await pool.close(force=True)
