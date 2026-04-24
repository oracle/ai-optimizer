"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Database configuration lookup utilities.
"""

import contextlib
import logging
import os
import re
from typing import Optional

import oracledb

from server.app.core.paths import PROJECT_ROOT
from server.app.core.settings import resolve_client, settings

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

    A descriptor value like ``(MY_WALLET_DIRECTORY="/path/(retry_count=5)/w")``
    can legitimately contain the literal substring ``(retry_count=5)``; the
    retry-strip must not delete text from inside a quoted value. This
    scanner splits the DSN on unescaped double quotes and only applies the
    regex to segments that are outside any quoted region.
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


def _build_connect_args(db_config: DatabaseConfig) -> dict:
    """Build the oracledb connection keyword arguments from a DatabaseConfig."""
    if not has_required_credentials(db_config):
        raise ValueError(f"Database alias {db_config.alias} missing credentials")

    config_dir = db_config.config_dir or os.environ.get("TNS_ADMIN") or str(_CORE_TNS_ADMIN)

    args: dict = {
        "user": db_config.username,
        "password": db_config.password,
        "dsn": _strip_retry_tokens(db_config.dsn or ""),
        "config_dir": config_dir,
    }
    if db_config.wallet_password:
        args["wallet_password"] = db_config.wallet_password
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
    if core_cfg is None or not core_cfg.pool or not core_cfg.usable:
        return None
    return core_cfg.pool


def get_client_db_config(client: str = "CONFIGURED") -> Optional[DatabaseConfig]:
    """Resolve a client string to its ``DatabaseConfig``.

    Returns the config when the associated pool exists and is usable,
    otherwise ``None``.
    """

    alias = resolve_client(client).database.alias
    db_config = get_database_settings(settings.database_configs, alias)
    if db_config is None or not db_config.pool or not db_config.usable:
        return None
    return db_config


def get_client_pool(client: str = "CONFIGURED") -> Optional[oracledb.AsyncConnectionPool]:
    """Resolve a client string to its async connection pool.

    Convenience wrapper that returns just the pool, or ``None`` if the
    database is not available or not usable.
    """
    db_config = get_client_db_config(client)
    return db_config.pool if db_config else None


async def close_pool(pool: Optional[oracledb.AsyncConnectionPool]) -> None:
    """Silently close a connection pool if it is not None."""
    if pool is not None:
        with contextlib.suppress(oracledb.Error):
            await pool.close(force=True)
