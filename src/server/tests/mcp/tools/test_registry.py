"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.mcp.tools.registry.
"""
# spell-checker: disable

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from server.app.mcp.tools import registry


def test_register_mcp_tools_invokes_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """register_mcp_tools should invoke all tool registrations in order."""
    called: list[str] = []

    def _make_recorder(name: str):
        def _record():
            called.append(name)

        return _record

    monkeypatch.setattr(registry, "register_discovery_tool", _make_recorder("discovery"))
    monkeypatch.setattr(registry, "register_grade_tool", _make_recorder("grade"))
    monkeypatch.setattr(registry, "register_rephrase_tool", _make_recorder("rephrase"))
    monkeypatch.setattr(registry, "register_retriever_tool", _make_recorder("retriever"))

    registry.LOGGER = MagicMock()

    registry.register_mcp_tools()

    assert called == ["discovery", "grade", "rephrase", "retriever"]
    registry.LOGGER.info.assert_called_once_with("Registered 4 MCP tool(s)")
