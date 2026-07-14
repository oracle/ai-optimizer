"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for SQLcl Proxies
"""
# spell-checker: disable

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client
from pydantic import SecretStr

from server.app.core.mcp import mcp
from server.app.core.settings import settings
from server.app.database.schemas import DatabaseConfig
from server.app.mcp.proxies import sqlcl


class _DummyClient:
    """Async client stub returning configurable resources."""

    def __init__(self, tools=None, prompts=None, resources=None, raise_on_enter: bool = False):
        self._tools = tools or []
        self._prompts = prompts or []
        self._resources = resources or []
        self._raise_on_enter = raise_on_enter

    async def __aenter__(self):
        """Enter the async context, optionally raising."""
        if self._raise_on_enter:
            raise RuntimeError("boom")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Exit without suppressing exceptions."""
        return False

    async def list_tools(self):
        """Return configured tools."""
        return self._tools

    async def list_prompts(self):
        """Return configured prompts."""
        return self._prompts

    async def list_resources(self):
        """Return configured resources."""
        return self._resources


async def test_verify_backend_success(caplog):
    """_verify_backend returns True when backend exposes capabilities."""
    caplog.set_level("INFO")
    client = _DummyClient(
        tools=[SimpleNamespace(name="tool1")],
        prompts=[SimpleNamespace(name="prompt1")],
        resources=[],
    )
    assert await sqlcl._verify_backend(cast(Client[Any], client)) is True
    assert "tool(s)" in caplog.records[-1].msg


async def test_verify_backend_empty():
    """_verify_backend returns False when nothing is listed."""
    client = _DummyClient()
    assert await sqlcl._verify_backend(cast(Client[Any], client)) is False


async def test_verify_backend_exception(caplog):
    """_verify_backend handles client open failures gracefully."""
    caplog.set_level("WARNING")
    client = _DummyClient(raise_on_enter=True)
    assert await sqlcl._verify_backend(cast(Client[Any], client)) is False
    assert "failed to open client" in caplog.text


async def test_verify_backend_resource_failure_does_not_block_tools(caplog):
    """A failure listing resources must not prevent the proxy from mounting when tools exist."""
    caplog.set_level("WARNING")

    class _PartialClient(_DummyClient):
        async def list_resources(self):
            raise RuntimeError("invalid resource URL")

    client = _PartialClient(tools=[SimpleNamespace(name="tool1")])
    assert await sqlcl._verify_backend(cast(Client[Any], client)) is True
    assert "failed to list resources" in caplog.text


async def test_create_connection_store_success(monkeypatch):
    """_create_connection_store issues expected SQLcl commands."""
    recorded: dict[str, Any] = {}

    class DummyProc:
        """Subprocess stand-in capturing stdin and args."""

        def __init__(self):
            self.killed = False
            self.waited = False

        async def communicate(self, data):
            recorded["input"] = data.decode()
            return b"", b""

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True

    dummy_proc = DummyProc()

    async def _fake_exec(*args, **kwargs):
        recorded["exec_args"] = args
        return dummy_proc

    monkeypatch.setattr(sqlcl.asyncio, "create_subprocess_exec", _fake_exec)

    async def _passthrough(coro, timeout):
        return await coro

    monkeypatch.setattr(sqlcl.asyncio, "wait_for", AsyncMock(side_effect=_passthrough))

    await sqlcl._create_connection_store(
        sqlcl_binary="/usr/bin/sql",
        alias="TEST",
        username="scott",
        password="tiger",
        dsn="db",
        env={"VAR": "1"},
        dbtools_home=sqlcl._DBTOOLS_HOME,
    )

    # Command uses flagged credentials rather than inline user/pass@dsn
    input_cmd = recorded["input"]
    assert 'conn -save TEST -savepwd -user "scott" -password "tiger" -url "db"' in input_cmd
    # No connmgr delete — the store is cleared up front
    assert "connmgr delete" not in input_cmd
    # -home flag passed to subprocess
    exec_args = recorded["exec_args"]
    assert "-home" in exec_args
    assert str(sqlcl._DBTOOLS_HOME) in exec_args
    assert not dummy_proc.killed


async def test_create_connection_store_special_chars(monkeypatch):
    """_create_connection_store quotes credentials containing special characters."""
    recorded: dict[str, Any] = {}

    class DummyProc:
        """Minimal process stub recording stdin."""

        async def communicate(self, data):
            recorded["input"] = data.decode()
            return b"", b""

    dummy_proc = DummyProc()

    async def _fake_exec(*args, **_kwargs):
        return dummy_proc

    async def _passthrough(coro, timeout):
        return await coro

    monkeypatch.setattr(sqlcl.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(sqlcl.asyncio, "wait_for", AsyncMock(side_effect=_passthrough))

    await sqlcl._create_connection_store(
        sqlcl_binary="/usr/bin/sql",
        alias="TEST",
        username='user"name',
        password="pa@ss/word",
        dsn="db/service",
        env={},
        dbtools_home=sqlcl._DBTOOLS_HOME,
    )

    input_cmd = recorded["input"]
    assert '-user "user\\"name"' in input_cmd
    assert '-password "pa@ss/word"' in input_cmd
    assert '-url "db/service"' in input_cmd


async def test_create_connection_store_flattens_newlines_for_sqlcl_stdin(monkeypatch):
    """Multi-line descriptors are flattened to a single line before SQLcl stdin.

    SQLcl's stdin parser treats \\n as a command boundary. Oracle's descriptor
    whitespace is insignificant, so replacing newlines with spaces at the
    sink preserves semantics while keeping SQLcl's stream coherent.

    Crucially, internal spaces inside descriptor values are NOT disturbed —
    only CR/LF are replaced. A DN like "CN=adb, OU=foo" passes through
    unchanged.
    """
    recorded: dict[str, Any] = {}

    class DummyProc:
        async def communicate(self, data):
            recorded["input"] = data.decode()
            return b"", b""

    async def _fake_exec(*args, **_kwargs):
        return DummyProc()

    async def _passthrough(coro, timeout):
        return await coro

    monkeypatch.setattr(sqlcl.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(sqlcl.asyncio, "wait_for", AsyncMock(side_effect=_passthrough))

    multiline_dsn = (
        "(DESCRIPTION =\n"
        "  (ADDRESS = (PROTOCOL = tcps)(HOST = h)(PORT = 1522))\n"
        "  (CONNECT_DATA = (SERVICE_NAME = svc))\n"
        '  (SECURITY = (SSL_SERVER_CERT_DN = "CN=h, OU=foo"))\n'
        ")"
    )

    await sqlcl._create_connection_store(
        sqlcl_binary="/usr/bin/sql",
        alias="TEST",
        username="scott",
        password="tiger",
        dsn=multiline_dsn,
        env={},
        dbtools_home=sqlcl._DBTOOLS_HOME,
    )

    input_cmd = recorded["input"]
    # The `conn` line sent to SQLcl contains no raw newlines.
    conn_line, _, _ = input_cmd.partition("\nexit")
    assert "\n" not in conn_line and "\r" not in conn_line
    # Meaningful spaces inside the DN value pass through unchanged —
    # _quote_sqlcl_value escapes the surrounding `"` to `\"`, but the
    # DN contents (including the spaces) are preserved byte-for-byte.
    assert r"\"CN=h, OU=foo\"" in conn_line
    # Descriptor structure (with internal spaces) is preserved.
    assert "(CONNECT_DATA = (SERVICE_NAME = svc))" in conn_line


async def test_create_connection_store_timeout(monkeypatch, caplog):
    """_create_connection_store kills process after timeout."""
    caplog.set_level("ERROR")

    class DummyProc:
        """Process stub that tracks kill invocation."""

        def __init__(self):
            self.killed = False

        async def communicate(self, data):
            raise AssertionError("Unexpected communicate call")  # pragma: no cover

        def kill(self):
            self.killed = True

        async def wait(self):
            return None

    dummy_proc = DummyProc()
    monkeypatch.setattr(sqlcl.asyncio, "create_subprocess_exec", AsyncMock(return_value=dummy_proc))

    async def _raise_timeout(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(sqlcl.asyncio, "wait_for", AsyncMock(side_effect=_raise_timeout))

    await sqlcl._create_connection_store(
        sqlcl_binary="/usr/bin/sql",
        alias="TEST",
        username="scott",
        password="tiger",
        dsn="db",
        env={"VAR": "1"},
        dbtools_home=sqlcl._DBTOOLS_HOME,
    )

    assert dummy_proc.killed is True
    assert "Timed out creating connection store" in caplog.text


async def test_register_sqlcl_proxy_missing_binary(monkeypatch, caplog):
    """register_sqlcl_proxy logs warning when sqlcl is absent."""
    caplog.set_level("WARNING")
    monkeypatch.setattr(sqlcl.shutil, "which", lambda name: None)

    await sqlcl.register_sqlcl_proxy()

    assert "sql not found" in caplog.text


async def test_register_sqlcl_proxy_no_capabilities(monkeypatch, caplog):
    """register_sqlcl_proxy aborts proxy mount if backend exposes no capabilities."""
    caplog.set_level("WARNING")
    monkeypatch.setattr(sqlcl.shutil, "which", lambda name: "/usr/bin/sql")
    verify_mock = AsyncMock(return_value=False)
    store_mock = AsyncMock()
    transport_mock = MagicMock()
    transport_mock.return_value.close = AsyncMock()
    client_mock = MagicMock()
    clear_mock = MagicMock()
    monkeypatch.setattr(sqlcl, "_verify_backend", verify_mock)
    monkeypatch.setattr(sqlcl, "_create_connection_store", store_mock)
    monkeypatch.setattr(sqlcl, "_clear_connection_store", clear_mock)
    monkeypatch.setattr(sqlcl, "_preflight_check", AsyncMock(return_value=True))
    monkeypatch.setattr(sqlcl, "StdioTransport", transport_mock)
    monkeypatch.setattr(sqlcl, "Client", client_mock)
    monkeypatch.setattr(sqlcl, "_create_client_factory", MagicMock())
    monkeypatch.setattr(sqlcl, "FastMCPServer", MagicMock())
    monkeypatch.setattr(sqlcl, "FastMCPProvider", MagicMock())
    monkeypatch.setattr(sqlcl, "Namespace", MagicMock())

    # No databases configured — so no store calls expected
    settings.database_configs = []

    await sqlcl.register_sqlcl_proxy()

    assert "skipping mount — no capabilities discovered" in caplog.text
    clear_mock.assert_called_once()
    store_mock.assert_not_called()


async def test_register_sqlcl_proxy_success(monkeypatch):
    """register_sqlcl_proxy clears store, creates connections, then mounts proxy."""
    monkeypatch.setattr(sqlcl.shutil, "which", lambda name: "/usr/bin/sql")

    transport_mock = MagicMock()
    client_mock = MagicMock()
    factory_mock = MagicMock(return_value="fake_factory")
    fastmcp_mock = MagicMock()
    verify_mock = AsyncMock(return_value=True)
    clear_mock = MagicMock()

    wrapped_provider = MagicMock()
    provider_instance = MagicMock()
    provider_instance.wrap_transform.return_value = wrapped_provider
    fastmcp_provider_mock = MagicMock(return_value=provider_instance)
    namespace_mock = MagicMock()

    monkeypatch.setattr(sqlcl, "StdioTransport", transport_mock)
    monkeypatch.setattr(sqlcl, "Client", client_mock)
    monkeypatch.setattr(sqlcl, "_create_client_factory", factory_mock)
    monkeypatch.setattr(sqlcl, "FastMCPServer", fastmcp_mock)
    monkeypatch.setattr(sqlcl, "FastMCPProvider", fastmcp_provider_mock)
    monkeypatch.setattr(sqlcl, "Namespace", namespace_mock)
    monkeypatch.setattr(sqlcl, "_verify_backend", verify_mock)
    monkeypatch.setattr(sqlcl, "_clear_connection_store", clear_mock)
    monkeypatch.setattr(sqlcl, "_preflight_check", AsyncMock(return_value=True))

    # Reset module state and avoid touching the real MCP singleton's providers list
    sqlcl._state.transport = None
    sqlcl._state.provider = None
    fake_providers: list = []
    monkeypatch.setattr(mcp, "providers", fake_providers)

    store_calls: list[dict] = []

    async def _fake_store(**kwargs):
        store_calls.append(kwargs)

    monkeypatch.setattr(sqlcl, "_create_connection_store", _fake_store)

    good = DatabaseConfig(
        alias="CORE", username="scott", password=SecretStr("tiger"), dsn="db", config_dir="/tmp/custom"
    )
    bad = DatabaseConfig(alias="BAD")
    settings.database_configs = [good, bad]

    monkeypatch.setenv("TNS_ADMIN", "/env/tns")

    try:
        result = await sqlcl.register_sqlcl_proxy()
    finally:
        sqlcl._state.transport = None
        sqlcl._state.provider = None

    # Store cleared before anything else
    clear_mock.assert_called_once()

    # Connection stores created (only valid database)
    assert len(store_calls) == 1
    call = store_calls[0]
    assert call["alias"] == "CORE"
    assert call["env"]["TNS_ADMIN"] == "/tmp/custom"

    # Proxy mounted with -home flag
    assert transport_mock.call_count == 1
    transport_args = transport_mock.call_args
    args_list = transport_args.kwargs.get("args", transport_args[1].get("args", []))
    assert "-home" in args_list
    assert str(sqlcl._DBTOOLS_HOME) in args_list

    client_mock.assert_called_once_with(transport_mock.return_value)
    factory_mock.assert_called_once_with(client_mock.return_value)
    fastmcp_mock.assert_called_once_with(name="SQLclProxy")

    # Wrapped provider appended to mcp.providers rather than mcp.mount(...)
    fastmcp_provider_mock.assert_called_once()
    namespace_mock.assert_called_once_with("sqlcl")
    provider_instance.wrap_transform.assert_called_once_with(namespace_mock.return_value)
    assert fake_providers == [wrapped_provider]
    assert result is transport_mock.return_value


async def test_register_sqlcl_proxy_store_error(monkeypatch, caplog):
    """register_sqlcl_proxy logs errors from connection store creation."""
    monkeypatch.setattr(sqlcl.shutil, "which", lambda name: "/usr/bin/sql")
    monkeypatch.setattr(sqlcl, "StdioTransport", MagicMock())
    monkeypatch.setattr(sqlcl, "Client", MagicMock())
    monkeypatch.setattr(sqlcl, "_create_client_factory", MagicMock())
    monkeypatch.setattr(sqlcl, "FastMCPServer", MagicMock())
    monkeypatch.setattr(sqlcl, "FastMCPProvider", MagicMock())
    monkeypatch.setattr(sqlcl, "Namespace", MagicMock())
    monkeypatch.setattr(sqlcl, "_verify_backend", AsyncMock(return_value=True))
    monkeypatch.setattr(sqlcl, "_clear_connection_store", MagicMock())
    monkeypatch.setattr(sqlcl, "_preflight_check", AsyncMock(return_value=True))

    async def _raise_store(**kwargs):
        raise RuntimeError("store failed")

    monkeypatch.setattr(sqlcl, "_create_connection_store", _raise_store)
    monkeypatch.setattr(mcp, "providers", [])
    sqlcl._state.transport = None
    sqlcl._state.provider = None

    settings.database_configs = [
        DatabaseConfig(alias="CORE", username="scott", password=SecretStr("tiger"), dsn="db"),
    ]

    caplog.set_level("ERROR")

    try:
        await sqlcl.register_sqlcl_proxy()
    finally:
        sqlcl._state.transport = None
        sqlcl._state.provider = None

    assert "store failed" in caplog.text


async def test_ensure_sqlcl_saved_connection_recreates_alias(monkeypatch):
    """ensure_sqlcl_saved_connection recreates one saved alias from live settings."""
    sqlcl_binary = "/usr/bin/sql"
    monkeypatch.setattr(sqlcl.shutil, "which", lambda name: sqlcl_binary)
    create_mock = AsyncMock()
    refresh_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(sqlcl, "_create_connection_store", create_mock)
    monkeypatch.setattr(sqlcl, "_refresh_sqlcl_proxy_unlocked", refresh_mock)

    settings.database_configs = [
        DatabaseConfig(
            alias="CORE",
            username="scott",
            password=SecretStr("tiger"),
            dsn="db",
            config_dir="/tmp/custom",
        )
    ]
    monkeypatch.setenv("TNS_ADMIN", "/env/tns")

    ok = await sqlcl.ensure_sqlcl_saved_connection("CORE")

    assert ok is True
    create_mock.assert_awaited_once()
    await_args = create_mock.await_args
    assert await_args is not None
    call = await_args.kwargs
    assert call["sqlcl_binary"] == sqlcl_binary
    assert call["alias"] == "CORE"
    assert call["username"] == "scott"
    assert call["password"] == "tiger"
    assert call["dsn"] == "db"
    assert call["env"]["TNS_ADMIN"] == "/tmp/custom"
    assert call["dbtools_home"] == sqlcl._DBTOOLS_HOME
    refresh_mock.assert_awaited_once()


async def test_ensure_sqlcl_saved_connection_returns_false_when_alias_unknown(monkeypatch):
    """ensure_sqlcl_saved_connection is a no-op when the alias is not configured."""
    monkeypatch.setattr(sqlcl.shutil, "which", lambda name: "/usr/bin/sql")
    create_mock = AsyncMock()
    monkeypatch.setattr(sqlcl, "_create_connection_store", create_mock)
    settings.database_configs = []

    ok = await sqlcl.ensure_sqlcl_saved_connection("CORE")

    assert ok is False
    create_mock.assert_not_called()


async def test_register_sqlcl_proxy_creation_failure(monkeypatch, caplog):
    """register_sqlcl_proxy logs and exits on proxy creation failure."""
    caplog.set_level("ERROR")
    monkeypatch.setattr(sqlcl.shutil, "which", lambda name: "/usr/bin/sql")
    monkeypatch.setattr(sqlcl, "_clear_connection_store", MagicMock())
    monkeypatch.setattr(sqlcl, "_preflight_check", AsyncMock(return_value=True))
    monkeypatch.setattr(sqlcl, "StdioTransport", MagicMock(side_effect=RuntimeError("transport boom")))
    settings.database_configs = []

    await sqlcl.register_sqlcl_proxy()

    assert "Failed to create SQLcl MCP proxy" in caplog.text


def test_clear_connection_store(monkeypatch, tmp_path, caplog):
    """_clear_connection_store removes stale content and copies the template."""
    caplog.set_level("INFO")
    fake_home = tmp_path / "etc" / "dbtools"
    fake_home.mkdir(parents=True)
    (fake_home / "stale_file.xml").write_text("old data")

    fake_template = tmp_path / "template"
    fake_template.mkdir()
    (fake_template / "connections.xml").write_text("template data")
    monkeypatch.setattr(sqlcl, "_DBTOOLS_TEMPLATE", fake_template)

    sqlcl._clear_connection_store(fake_home)

    # Directory recreated with template contents and without stale files
    assert fake_home.exists()
    assert not (fake_home / "stale_file.xml").exists()
    assert sorted(p.name for p in fake_home.iterdir()) == ["connections.xml"]
    assert "Prepared connection store" in caplog.text


def test_clear_connection_store_nonexistent(monkeypatch, tmp_path, caplog):
    """_clear_connection_store creates directory when template is absent."""
    caplog.set_level("INFO")
    fake_home = tmp_path / "new_etc" / "dbtools"
    monkeypatch.setattr(sqlcl, "_DBTOOLS_TEMPLATE", tmp_path / "missing")

    sqlcl._clear_connection_store(fake_home)

    assert fake_home.exists()
    assert not list(fake_home.iterdir())
    assert "Prepared connection store" in caplog.text


# ---------------------------------------------------------------------------
# _coerce_schema_defaults
# ---------------------------------------------------------------------------


def test_coerce_schema_defaults_boolean():
    schema = {"properties": {"show_details": {"type": "boolean", "default": "false"}}}
    sqlcl._coerce_schema_defaults(schema)
    assert schema["properties"]["show_details"]["default"] is False


def test_coerce_schema_defaults_boolean_true():
    schema = {"properties": {"verbose": {"type": "boolean", "default": "True"}}}
    sqlcl._coerce_schema_defaults(schema)
    assert schema["properties"]["verbose"]["default"] is True


def test_coerce_schema_defaults_integer():
    schema = {"properties": {"limit": {"type": "integer", "default": "42"}}}
    sqlcl._coerce_schema_defaults(schema)
    assert schema["properties"]["limit"]["default"] == 42


def test_coerce_schema_defaults_number():
    schema = {"properties": {"threshold": {"type": "number", "default": "3.14"}}}
    sqlcl._coerce_schema_defaults(schema)
    assert schema["properties"]["threshold"]["default"] == pytest.approx(3.14)


def test_coerce_schema_defaults_string_unchanged():
    schema = {"properties": {"name": {"type": "string", "default": "hello"}}}
    sqlcl._coerce_schema_defaults(schema)
    assert schema["properties"]["name"]["default"] == "hello"


def test_coerce_schema_defaults_no_default():
    schema = {"properties": {"flag": {"type": "boolean"}}}
    sqlcl._coerce_schema_defaults(schema)
    assert "default" not in schema["properties"]["flag"]


def test_coerce_schema_defaults_already_correct_type():
    schema = {"properties": {"flag": {"type": "boolean", "default": True}}}
    sqlcl._coerce_schema_defaults(schema)
    assert schema["properties"]["flag"]["default"] is True


# ---------------------------------------------------------------------------
# _preflight_check
# ---------------------------------------------------------------------------


async def test_preflight_check_healthy(monkeypatch):
    """Preflight returns True when the process stays running (timeout fires)."""

    class _RunningProc:
        """Process stub that never exits — communicate blocks until killed."""

        pid = 9999

        def __init__(self):
            self.killed = False

        async def communicate(self):
            await asyncio.sleep(60)

        def kill(self):
            self.killed = True

        async def wait(self):
            return None

    proc = _RunningProc()
    monkeypatch.setattr(sqlcl.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))

    # Use a very short timeout so the test runs fast
    monkeypatch.setattr(sqlcl, "_PREFLIGHT_TIMEOUT", 0.1)

    result = await sqlcl._preflight_check("/usr/bin/sql", ["-mcp"], {})

    assert result is True
    assert proc.killed is True


async def test_preflight_check_java_error(monkeypatch, caplog):
    """Preflight returns False when SQLcl reports a Java version error."""
    caplog.set_level("WARNING")

    class _JavaErrorProc:
        """Process stub that exits immediately with Java error."""

        pid = 9999
        returncode = 1

        async def communicate(self):
            return (b"SQLcl -mcp requires Java 17 and above to run\n", b"")

    monkeypatch.setattr(sqlcl.asyncio, "create_subprocess_exec", AsyncMock(return_value=_JavaErrorProc()))

    async def _passthrough(coro, timeout):
        return await coro

    monkeypatch.setattr(sqlcl.asyncio, "wait_for", AsyncMock(side_effect=_passthrough))

    result = await sqlcl._preflight_check("/usr/bin/sql", ["-mcp"], {})

    assert result is False
    assert "preflight failed" in caplog.text
    assert "requires Java" in caplog.text


async def test_preflight_check_nonzero_exit(monkeypatch, caplog):
    """Preflight returns False when process exits with non-zero return code."""
    caplog.set_level("WARNING")

    class _FailProc:
        """Process stub that exits with rc=2."""

        pid = 9999
        returncode = 2

        async def communicate(self):
            return (b"", b"Something went wrong\n")

    monkeypatch.setattr(sqlcl.asyncio, "create_subprocess_exec", AsyncMock(return_value=_FailProc()))

    async def _passthrough(coro, timeout):
        return await coro

    monkeypatch.setattr(sqlcl.asyncio, "wait_for", AsyncMock(side_effect=_passthrough))

    result = await sqlcl._preflight_check("/usr/bin/sql", ["-mcp"], {})

    assert result is False
    assert "preflight failed" in caplog.text


async def test_preflight_check_clean_exit(monkeypatch):
    """Preflight returns True when process exits cleanly with rc=0 and no errors."""

    class _CleanProc:
        """Process stub that exits cleanly."""

        pid = 9999
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    monkeypatch.setattr(sqlcl.asyncio, "create_subprocess_exec", AsyncMock(return_value=_CleanProc()))

    async def _passthrough(coro, timeout):
        return await coro

    monkeypatch.setattr(sqlcl.asyncio, "wait_for", AsyncMock(side_effect=_passthrough))

    result = await sqlcl._preflight_check("/usr/bin/sql", ["-mcp"], {})

    assert result is True


async def test_register_sqlcl_proxy_preflight_fails(monkeypatch, caplog):
    """register_sqlcl_proxy returns None when preflight fails."""
    caplog.set_level("WARNING")
    monkeypatch.setattr(sqlcl.shutil, "which", lambda name: "/usr/bin/sql")
    monkeypatch.setattr(sqlcl, "_clear_connection_store", MagicMock())
    monkeypatch.setattr(sqlcl, "_preflight_check", AsyncMock(return_value=False))

    settings.database_configs = []

    result = await sqlcl.register_sqlcl_proxy()

    assert result is None


async def test_preflight_check_spawn_failure(monkeypatch, caplog):
    """Preflight returns False when the subprocess cannot be spawned."""
    caplog.set_level("WARNING")
    monkeypatch.setattr(
        sqlcl.asyncio,
        "create_subprocess_exec",
        AsyncMock(side_effect=PermissionError("Permission denied")),
    )

    result = await sqlcl._preflight_check("/usr/bin/sql", ["-mcp"], {})

    assert result is False
    assert "preflight failed to spawn process" in caplog.text


def test_coerce_schema_defaults_nested():
    schema = {
        "properties": {
            "opts": {
                "type": "object",
                "properties": {"enabled": {"type": "boolean", "default": "true"}},
            }
        }
    }
    sqlcl._coerce_schema_defaults(schema)
    assert schema["properties"]["opts"]["properties"]["enabled"]["default"] is True


# ---------------------------------------------------------------------------
# refresh_sqlcl_proxy
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_sqlcl_state(monkeypatch):
    """Isolate tests from each other: clear module state and swap in a fake
    providers list so the real MCP singleton isn't mutated."""
    sqlcl._state.transport = None
    sqlcl._state.provider = None
    fake_providers: list = []
    monkeypatch.setattr(mcp, "providers", fake_providers)
    yield fake_providers
    sqlcl._state.transport = None
    sqlcl._state.provider = None


async def test_refresh_sqlcl_proxy_closes_old_and_mounts_new(reset_sqlcl_state, monkeypatch):
    """Refresh tears down the previous transport+provider and stores the new pair."""
    providers = reset_sqlcl_state
    old_transport = MagicMock()
    old_transport.close = AsyncMock()
    old_provider = MagicMock()
    new_transport = MagicMock()
    new_provider = MagicMock()

    sqlcl._state.transport = old_transport
    sqlcl._state.provider = old_provider
    providers.append(old_provider)

    async def _fake_unlocked():
        return (new_transport, new_provider)

    monkeypatch.setattr(sqlcl, "_register_sqlcl_proxy_unlocked", _fake_unlocked)

    ok = await sqlcl.refresh_sqlcl_proxy()

    assert ok is True
    old_transport.close.assert_awaited_once()
    assert old_provider not in providers
    assert sqlcl._state.transport is new_transport
    assert sqlcl._state.provider is new_provider
    assert settings.nl2sql_available is True


async def test_refresh_sqlcl_proxy_handles_register_failure(reset_sqlcl_state, monkeypatch, caplog):
    """A failed rebuild leaves state cleared and nl2sql_available False, but never raises."""
    caplog.set_level("ERROR")
    old_transport = MagicMock()
    old_transport.close = AsyncMock()
    sqlcl._state.transport = old_transport

    async def _boom():
        raise RuntimeError("register boom")

    monkeypatch.setattr(sqlcl, "_register_sqlcl_proxy_unlocked", _boom)

    ok = await sqlcl.refresh_sqlcl_proxy()

    assert ok is False
    assert sqlcl._state.transport is None
    assert sqlcl._state.provider is None
    assert settings.nl2sql_available is False
    assert "SQLcl proxy refresh failed" in caplog.text


async def test_refresh_sqlcl_proxy_unlocked_returns_none(reset_sqlcl_state, monkeypatch):
    """When the underlying register returns None (e.g. no sqlcl binary), state stays cleared."""
    sqlcl._state.transport = MagicMock(close=AsyncMock())

    async def _none():
        return None

    monkeypatch.setattr(sqlcl, "_register_sqlcl_proxy_unlocked", _none)

    ok = await sqlcl.refresh_sqlcl_proxy()

    assert ok is False
    assert sqlcl._state.transport is None
    assert sqlcl._state.provider is None
    assert settings.nl2sql_available is False


async def test_refresh_sqlcl_proxy_serializes_concurrent_calls(reset_sqlcl_state, monkeypatch):
    """Two concurrent refreshes execute sequentially under _refresh_lock."""
    overlap = {"max_inflight": 0, "inflight": 0}
    gate = asyncio.Event()

    async def _slow_register():
        overlap["inflight"] += 1
        overlap["max_inflight"] = max(overlap["max_inflight"], overlap["inflight"])
        # First call blocks until released; second should not start meanwhile
        if overlap["inflight"] == 1 and not gate.is_set():
            gate.set()
            await asyncio.sleep(0.05)
        overlap["inflight"] -= 1
        return (MagicMock(), object())

    monkeypatch.setattr(sqlcl, "_register_sqlcl_proxy_unlocked", _slow_register)

    await asyncio.gather(sqlcl.refresh_sqlcl_proxy(), sqlcl.refresh_sqlcl_proxy())

    assert overlap["max_inflight"] == 1
