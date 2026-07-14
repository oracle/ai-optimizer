"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

SQLcl MCP proxy — discovers the ``sql`` binary, creates connection stores
for each configured database, then mounts a proxy onto the main MCP server.
"""
# spell-checker: ignore sqlcl fastmcp connmgr noupdates savepwd dbtools

import asyncio
import logging
import os
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.server.providers import Provider
from fastmcp.server.providers.fastmcp_provider import FastMCPProvider
from fastmcp.server.providers.proxy import ProxyProvider, _create_client_factory
from fastmcp.server.server import FastMCP as FastMCPServer
from fastmcp.server.transforms.namespace import Namespace
from fastmcp.tools import Tool

from server.app.core.mcp import mcp
from server.app.core.paths import PROJECT_ROOT
from server.app.core.secrets import reveal
from server.app.core.settings import settings

LOGGER = logging.getLogger(__name__)

_CORE_TNS_ADMIN = PROJECT_ROOT / "server" / "tns_admin"
_DBTOOLS_TEMPLATE = PROJECT_ROOT / "server" / "etc" / "dbtools"
_CONN_STORE_TIMEOUT = 30  # seconds
_PREFLIGHT_TIMEOUT = 5  # seconds — long enough for SQLcl to start, short enough not to delay startup
_VERIFY_TIMEOUT = 30  # seconds — cap how long we wait for SQLcl to enumerate capabilities

# Maps JSON Schema type names to (target_python_type, converter) pairs.
_TYPE_COERCIONS: dict[str, tuple[type, type]] = {
    "boolean": (bool, bool),  # bool("false") is True — handled specially below
    "integer": (int, int),
    "number": (float, float),
}

_BOOL_STRINGS = {"true": True, "false": False, "1": True, "0": False}


def _coerce_schema_defaults(schema: dict) -> None:
    """Coerce string *default* values to match their declared JSON Schema type.

    Mutates *schema* in place.  Walks ``properties`` recursively so nested
    object schemas are also sanitized.
    """
    properties: dict | None = schema.get("properties")
    if not properties:
        return

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue

        # Recurse into nested object properties
        if prop_schema.get("type") == "object":
            _coerce_schema_defaults(prop_schema)
            continue

        default = prop_schema.get("default")
        if not isinstance(default, str):
            continue

        declared_type = prop_schema.get("type")
        if declared_type not in _TYPE_COERCIONS:
            continue

        target_type, converter = _TYPE_COERCIONS[declared_type]

        try:
            if target_type is bool:
                coerced = _BOOL_STRINGS.get(default.lower())
                if coerced is None:
                    continue
            else:
                coerced = converter(default)
        except (ValueError, TypeError):
            continue

        LOGGER.warning(
            "SQLcl MCP proxy: coerced default of '%s' from %r to %r",
            prop_name,
            default,
            coerced,
        )
        prop_schema["default"] = coerced


class _SanitizingProxyProvider(ProxyProvider):
    """ProxyProvider that coerces mistyped defaults in MCP tool schemas."""

    async def _list_tools(self) -> Sequence[Tool]:
        tools = await super()._list_tools()
        for tool in tools:
            if tool.parameters:
                _coerce_schema_defaults(tool.parameters)
        return tools


def _resolve_dbtools_home() -> Path:
    """Return a writable SQLcl connection-store path."""
    override = os.environ.get("AIO_SQLCL_HOME") or os.environ.get("SQLCL_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path(tempfile.gettempdir()) / "ai-optimizer" / "sqlcl"


_DBTOOLS_HOME = _resolve_dbtools_home()


# Live state for the mounted SQLcl proxy. register_sqlcl_proxy() populates this
# at startup; refresh_sqlcl_proxy() tears it down and rebuilds it when the
# database configuration changes so the SQLcl daemon re-reads the connection store.
# State is wrapped in a class so attribute mutations don't need `global`.
class _ProxyState:
    transport: StdioTransport | None = None
    provider: Provider | None = None


_state = _ProxyState()
_refresh_lock = asyncio.Lock()


def _clear_connection_store(dbtools_home: Path) -> None:
    """Delete and repopulate the connection store at *dbtools_home*."""
    try:
        if dbtools_home.exists():
            shutil.rmtree(dbtools_home)
    except PermissionError as exc:
        LOGGER.error("SQLcl MCP proxy: connection store not writable: %s", exc)
        raise

    dbtools_home.parent.mkdir(parents=True, exist_ok=True)

    if _DBTOOLS_TEMPLATE.exists():
        shutil.copytree(_DBTOOLS_TEMPLATE, dbtools_home, dirs_exist_ok=True)
    else:
        dbtools_home.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Prepared connection store at %s", dbtools_home)


async def _preflight_check(sqlcl_binary: str, args: list[str], env: dict[str, str]) -> bool:
    """Start SQLcl -mcp briefly to check for startup errors (e.g. wrong Java version)."""
    try:
        LOGGER.debug("Preflight: spawning SQLcl process")
        proc = await asyncio.create_subprocess_exec(
            sqlcl_binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except Exception as ex:
        LOGGER.warning("SQLcl MCP proxy: preflight failed to spawn process: %s", ex)
        return False

    LOGGER.debug("Preflight: SQLcl spawned (pid=%s), waiting %ss for exit", proc.pid, _PREFLIGHT_TIMEOUT)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_PREFLIGHT_TIMEOUT)
    except asyncio.TimeoutError:
        # Still running after timeout — process started successfully
        LOGGER.debug("Preflight: SQLcl still running — killing pid %s", proc.pid)
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            LOGGER.warning("Preflight: pid %s did not exit after SIGKILL", proc.pid)
        LOGGER.debug("Preflight: process terminated")
        return True

    # Process exited within timeout — check for errors
    output = (stdout + stderr).decode(errors="replace")
    if proc.returncode != 0 or "requires Java" in output:
        LOGGER.warning(
            "SQLcl MCP proxy: preflight failed (rc=%s): %s",
            proc.returncode,
            output.strip()[:200],
        )
        return False
    return True


async def _verify_backend(client: Client) -> bool:
    """Verify the client exposes tools, prompts, or resources from the SQLcl backend.

    Each capability is enumerated independently so that a single broken list
    (e.g. SQLcl currently emits non-URL resource names that fail Pydantic
    validation) does not abort the whole verification.
    """

    async def _safe_list(label: str, fn):
        try:
            items = await fn()
            return [getattr(it, "name", str(it)) for it in items]
        except Exception as ex:
            LOGGER.warning("SQLcl MCP proxy: failed to list %s: %s", label, ex)
            return []

    try:
        async with client:
            tool_names = await _safe_list("tools", client.list_tools)
            prompt_names = await _safe_list("prompts", client.list_prompts)
            resource_names = await _safe_list("resources", client.list_resources)
    except Exception as ex:
        LOGGER.warning("SQLcl MCP proxy: failed to open client: %s", ex)
        return False

    LOGGER.info(
        "SQLcl MCP proxy: %d tool(s): %s, %d prompt(s): %s, %d resource(s): %s",
        len(tool_names),
        tool_names,
        len(prompt_names),
        prompt_names,
        len(resource_names),
        resource_names,
    )
    return bool(tool_names or prompt_names or resource_names)


def _quote_sqlcl_value(value: str) -> str:
    """Return *value* quoted for SQLcl CLI consumption."""
    escaped = value.replace('"', '\\"')
    return '"' + escaped + '"'


def _flatten_dsn_for_stdin(dsn: str) -> str:
    """Replace CR/LF in a DSN with spaces for SQLcl stdin.

    The Pydantic schema only permits CR/LF inside a connect descriptor,
    where Oracle treats such whitespace as insignificant — so replacing
    them with a single space is semantics-preserving. SQLcl's stdin
    parser treats newlines as command boundaries, hence this narrow
    reshape at the sink rather than at the schema (where it would
    corrupt meaningful spaces inside descriptor *values* like
    SSL_SERVER_CERT_DN).
    """
    return dsn.replace("\r", " ").replace("\n", " ")


async def _create_connection_store(
    sqlcl_binary: str,
    alias: str,
    username: str,
    password: str,
    dsn: str,
    env: dict[str, str],
    dbtools_home: Path,
) -> None:
    """Create a SQLcl connection store entry for a single database."""
    conn_parts = [
        "conn",
        "-save",
        alias,
        "-savepwd",
        "-user",
        _quote_sqlcl_value(username),
        "-password",
        _quote_sqlcl_value(password),
        "-url",
        _quote_sqlcl_value(_flatten_dsn_for_stdin(dsn)),
    ]
    conn_command = " ".join(conn_parts)

    commands = (
        "\n".join(
            [
                conn_command,
                "exit",
            ]
        )
        + "\n"
    )

    proc = await asyncio.create_subprocess_exec(
        sqlcl_binary,
        "-home",
        str(dbtools_home),
        "/nolog",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        await asyncio.wait_for(proc.communicate(commands.encode()), timeout=_CONN_STORE_TIMEOUT)
        LOGGER.info("Established Connection Store for: %s", alias)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        LOGGER.error("Timed out creating connection store for: %s", alias)


async def ensure_sqlcl_saved_connection(alias: str) -> bool:
    """Ensure *alias* exists in SQLcl's saved-connection store.

    Returns ``True`` when the alias was recreated, ``False`` when it could not
    be recreated from the live application settings.
    """
    if not alias:
        return False

    async with _refresh_lock:
        db_config = next((cfg for cfg in settings.database_configs if cfg.alias.lower() == alias.lower()), None)
        if db_config is None:
            LOGGER.warning("SQLcl saved connection cannot be recreated: alias %s is not configured", alias)
            return False

        db_password = reveal(db_config.password)
        if not db_config.username or not db_password or not db_config.dsn:
            LOGGER.warning("SQLcl saved connection cannot be recreated: alias %s is missing credentials", alias)
            return False

        sqlcl_binary = shutil.which("sql")
        if not sqlcl_binary:
            LOGGER.warning("SQLcl saved connection cannot be recreated: sql binary not found")
            return False

        tns_admin = os.environ.get("TNS_ADMIN") or str(_CORE_TNS_ADMIN)
        env_vars = os.environ.copy()
        env_vars["TNS_ADMIN"] = db_config.config_dir or tns_admin

        await _create_connection_store(
            sqlcl_binary=sqlcl_binary,
            alias=db_config.alias,
            username=db_config.username,
            password=db_password,
            dsn=db_config.dsn,
            env=env_vars,
            dbtools_home=_DBTOOLS_HOME,
        )
        if not await _refresh_sqlcl_proxy_unlocked():
            LOGGER.error("SQLcl saved connection was recreated but the proxy could not be refreshed")
            return False
        LOGGER.info("Recreated SQLcl saved connection for alias %s", db_config.alias)
        return True


async def _mount_sqlcl_proxy(
    sqlcl_binary: str, dbtools_home: Path, env_vars: dict
) -> tuple[StdioTransport, Provider] | None:
    """Create an MCP transport, verify the backend, and mount the SQLcl proxy.

    Returns ``(transport, mounted_provider)`` on success so callers can later
    tear the proxy down by removing the provider from ``mcp.providers`` and
    closing the transport.
    """
    transport: StdioTransport | None = None
    try:
        LOGGER.debug("SQLcl proxy: creating StdioTransport")
        transport = StdioTransport(
            command=sqlcl_binary,
            args=["-mcp", "-daemon=start", "-thin", "-noupdates", "-home", str(dbtools_home)],
            env=env_vars,
            log_file=Path(os.devnull),
        )
        client = Client(transport)
        LOGGER.debug("SQLcl proxy: verifying backend capabilities")
        if not await asyncio.wait_for(_verify_backend(client), timeout=_VERIFY_TIMEOUT):
            LOGGER.warning("SQLcl MCP proxy: skipping mount — no capabilities discovered")
            await transport.close()
            return None

        client_factory = _create_client_factory(client)
        proxy = FastMCPServer(name="SQLclProxy")
        proxy.add_provider(_SanitizingProxyProvider(client_factory))
        # Equivalent to mcp.mount(proxy, namespace="sqlcl"), but we keep a
        # reference to the wrapped provider so refresh_sqlcl_proxy() can
        # remove it from mcp.providers on teardown.
        mounted_provider = FastMCPProvider(proxy).wrap_transform(Namespace("sqlcl"))
        mcp.providers.append(mounted_provider)
        LOGGER.info("Mounted SQLcl MCP proxy")
        return transport, mounted_provider
    except Exception as ex:
        LOGGER.error("Failed to create SQLcl MCP proxy: %s", ex)
        if transport is not None:
            await transport.close()
        return None


async def _register_sqlcl_proxy_unlocked() -> tuple[StdioTransport, Provider] | None:
    """Discover SQLcl, set up connection stores, and mount the MCP proxy.

    Caller must hold ``_refresh_lock``.  Returns ``(transport, mounted_provider)``
    on success.
    """
    sqlcl_binary = shutil.which("sql")
    if not sqlcl_binary:
        LOGGER.warning("Not enabling SQLcl MCP server, sql not found in PATH.")
        return None

    # Resolve TNS_ADMIN
    tns_admin = os.environ.get("TNS_ADMIN") or str(_CORE_TNS_ADMIN)

    env_vars = os.environ.copy()
    env_vars["TNS_ADMIN"] = tns_admin

    dbtools_home = _DBTOOLS_HOME

    # 1. Clear and recreate the connection store in a writable location
    try:
        _clear_connection_store(dbtools_home)
    except Exception as ex:
        LOGGER.error("Failed to prepare connection store at %s: %s", dbtools_home, ex)
        return None

    # 2. Create connection stores for each database with valid credentials
    for db in settings.database_configs:
        # Reveal the SecretStr password before the guard so the narrowed
        # local can flow into ``_create_connection_store`` without a second
        # None-check at the call site.
        db_password = reveal(db.password)
        if not db.username or not db_password or not db.dsn:
            continue

        config_dir = db.config_dir or tns_admin
        db_env = {**env_vars, "TNS_ADMIN": config_dir}

        try:
            await _create_connection_store(
                sqlcl_binary=sqlcl_binary,
                alias=db.alias,
                username=db.username,
                password=db_password,
                dsn=db.dsn,
                env=db_env,
                dbtools_home=dbtools_home,
            )
        except Exception as ex:
            LOGGER.error("Failed to create connection store for %s: %s", db.alias, ex)

    # 2b. Preflight — verify SQLcl -mcp can actually start
    LOGGER.debug("SQLcl proxy: starting preflight check")
    mcp_args = ["-mcp", "-daemon=start", "-thin", "-noupdates", "-home", str(dbtools_home)]
    if not await _preflight_check(sqlcl_binary, mcp_args, env_vars):
        return None
    LOGGER.debug("SQLcl proxy: preflight passed")

    # 3. Mount the SQLcl MCP proxy (reads the same -home store)
    return await _mount_sqlcl_proxy(sqlcl_binary, dbtools_home, env_vars)


async def _teardown_active_unlocked() -> None:
    """Unmount the current provider and close the current transport. Caller holds ``_refresh_lock``."""
    if _state.provider is not None and _state.provider in mcp.providers:
        mcp.providers.remove(_state.provider)
    await _close_transport(_state.transport)
    _state.transport = None
    _state.provider = None


async def register_sqlcl_proxy() -> StdioTransport | None:
    """Startup entrypoint: register the SQLcl proxy and cache the transport."""
    async with _refresh_lock:
        await _teardown_active_unlocked()  # defensive — startup should see no prior state
        result = await _register_sqlcl_proxy_unlocked()
        if result is not None:
            _state.transport, _state.provider = result
        return _state.transport


async def refresh_sqlcl_proxy() -> bool:
    """Tear down and rebuild the SQLcl MCP proxy.

    Called after ``settings.database_configs`` mutates so the SQLcl daemon sees
    the updated connection store.  Best-effort: failures are logged, and
    ``settings.nl2sql_available`` reflects the outcome so the UI stays honest.
    """
    async with _refresh_lock:
        return await _refresh_sqlcl_proxy_unlocked()


async def _refresh_sqlcl_proxy_unlocked() -> bool:
    """Refresh the SQLcl MCP proxy while the caller holds ``_refresh_lock``."""
    await _teardown_active_unlocked()
    try:
        result = await _register_sqlcl_proxy_unlocked()
    except Exception as ex:
        LOGGER.error("SQLcl proxy refresh failed: %s", ex)
        result = None

    if result is not None:
        _state.transport, _state.provider = result
    settings.nl2sql_available = _state.transport is not None
    return _state.transport is not None


async def _close_transport(transport: StdioTransport | None) -> None:
    """Close a SQLcl MCP proxy transport, swallowing teardown errors."""
    if transport is None:
        return
    try:
        await transport.close()
    except Exception:
        LOGGER.debug("SQLcl proxy transport close error", exc_info=True)


async def close_sqlcl_proxy() -> None:
    """Close the currently-mounted SQLcl proxy, terminating the SQLcl daemon.

    Reads the active transport from module state so callers don't have to track
    handles themselves — this keeps shutdown correct even after a refresh has
    swapped in a new transport.
    """
    async with _refresh_lock:
        await _teardown_active_unlocked()
