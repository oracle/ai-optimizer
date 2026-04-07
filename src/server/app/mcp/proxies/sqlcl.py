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
from fastmcp.server.providers.proxy import ProxyProvider, _create_client_factory
from fastmcp.server.server import FastMCP as FastMCPServer
from fastmcp.tools import Tool

from server.app.core.mcp import mcp
from server.app.core.paths import PROJECT_ROOT
from server.app.core.settings import settings
from server.app.database.config import has_required_credentials

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
    """Verify the client exposes tools, prompts, or resources from the SQLcl backend."""
    try:
        async with client:
            tools = await client.list_tools()
            prompts = await client.list_prompts()
            resources = await client.list_resources()

            tool_names = [t.name for t in tools]
            prompt_names = [p.name for p in prompts]
            resource_names = [r.name for r in resources]

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
    except Exception as ex:
        LOGGER.warning("SQLcl MCP proxy: failed to enumerate capabilities: %s", ex)
        return False


def _quote_sqlcl_value(value: str) -> str:
    """Return *value* quoted for SQLcl CLI consumption."""
    escaped = value.replace('"', '\\"')
    return '"' + escaped + '"'


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
        _quote_sqlcl_value(dsn),
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


async def _mount_sqlcl_proxy(sqlcl_binary: str, dbtools_home: Path, env_vars: dict) -> StdioTransport | None:
    """Create an MCP transport, verify the backend, and mount the SQLcl proxy."""
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
        mcp.mount(proxy, namespace="sqlcl")
        LOGGER.info("Mounted SQLcl MCP proxy")
        return transport
    except Exception as ex:
        LOGGER.error("Failed to create SQLcl MCP proxy: %s", ex)
        if transport is not None:
            await transport.close()
        return None


async def register_sqlcl_proxy() -> StdioTransport | None:
    """Discover SQLcl, set up connection stores, and mount the MCP proxy."""
    sqlcl_binary = shutil.which("sql")
    if not sqlcl_binary:
        LOGGER.warning("Not enabling SQLcl MCP server, sqlcl not found in PATH.")
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
        if not has_required_credentials(db) or not db.username or not db.password or not db.dsn:
            continue

        config_dir = db.config_dir or tns_admin
        db_env = {**env_vars, "TNS_ADMIN": config_dir}

        try:
            await _create_connection_store(
                sqlcl_binary=sqlcl_binary,
                alias=db.alias,
                username=db.username,
                password=db.password,
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


async def close_sqlcl_proxy(transport: StdioTransport | None) -> None:
    """Close the FastMCP proxy transport, terminating the SQLcl daemon process."""
    if transport is None:
        return
    try:
        await transport.close()
    except Exception:
        LOGGER.debug("SQLcl proxy transport close error", exc_info=True)
