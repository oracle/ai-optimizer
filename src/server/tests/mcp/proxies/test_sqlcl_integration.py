"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

SQLcl MCP integration tests.
"""
# spell-checker: disable

import os
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from mcp.shared.exceptions import McpError

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _sqlcl_client(tmp_path) -> AsyncIterator[Client]:
    """Yield an initialized SQLcl MCP client or skip when SQLcl MCP is unavailable."""
    sqlcl_binary = shutil.which("sql")
    if sqlcl_binary is None:
        pytest.skip("SQLcl is not installed")

    sqlcl_home = tmp_path / "sqlcl-home"
    transport = StdioTransport(
        command=sqlcl_binary,
        args=["-mcp", "-R", "4", "-thin", "-noupdates", "-home", str(sqlcl_home)],
        env={**os.environ, "TNS_ADMIN": str(sqlcl_home)},
        log_file=Path(os.devnull),
    )

    client = Client(transport)
    try:
        try:
            await client.__aenter__()
        except McpError as exc:
            pytest.skip(f"Oracle SQLcl MCP is unavailable: {exc}")
        try:
            yield client
        finally:
            await client.__aexit__(None, None, None)
    finally:
        await transport.close()


async def test_sqlcl_restrict_level_four_refuses_host_and_spool(tmp_path):
    """SQLcl MCP level 4 refuses host and spool commands when SQLcl is available."""
    async with _sqlcl_client(tmp_path) as client:
        for command in ("host true", "spool /dev/null"):
            result = await client.call_tool("sqlcl_run", {"sqlcl": command})
            output = "\n".join(str(getattr(content, "text", "")) for content in getattr(result, "content", []))
            assert "Restricted command" in output


async def test_sqlcl_run_advertises_write_capabilities(tmp_path):
    """SQLcl's standard SQL tool permits DML, DDL, and PL/SQL when authorized."""
    async with _sqlcl_client(tmp_path) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        description = tools["sqlcl_run"].description
        assert description is not None
        assert "DML, DDL statements, and PL/SQL blocks" in description
