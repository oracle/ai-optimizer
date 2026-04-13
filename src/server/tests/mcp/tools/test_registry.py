"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.mcp.tools.registry.
"""
# spell-checker: disable

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from server.app.mcp.tools import registry


def test_register_mcp_tools_discovers_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """register_mcp_tools should auto-discover and call every register_* function."""
    called: list[str] = []

    # Build fake modules with register_* callables.
    mod_alpha = types.ModuleType("alpha")
    mod_alpha.register_alpha_tool = lambda: called.append("alpha")

    mod_beta = types.ModuleType("beta")
    mod_beta.register_beta_tool = lambda: called.append("beta")

    # A module with no register_* should be imported but contribute nothing.
    mod_empty = types.ModuleType("empty")
    mod_empty.helper = lambda: None  # not a register_* name

    fake_modules = {
        "alpha": mod_alpha,
        "beta": mod_beta,
        "empty": mod_empty,
    }

    # Fake iter_modules to yield our test modules (skip list tested implicitly
    # because we never yield "registry" or "schemas").
    fake_module_infos = [
        types.SimpleNamespace(name=name) for name in fake_modules
    ]

    package = types.ModuleType(registry.__package__)
    package.__path__ = ["/fake"]

    monkeypatch.setattr(registry, "LOGGER", MagicMock())

    with (
        patch.object(registry.importlib, "import_module") as mock_import,
        patch.object(registry.pkgutil, "iter_modules", return_value=fake_module_infos),
    ):
        mock_import.side_effect = lambda name: (
            package if name == registry.__package__ else fake_modules[name.rsplit(".", 1)[-1]]
        )

        registry.register_mcp_tools()

    assert sorted(called) == ["alpha", "beta"]
    registry.LOGGER.info.assert_called_once_with("Registered %d MCP tool(s)", 2)


def test_register_mcp_tools_skips_reserved_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Modules named registry, schemas, or __init__ must be skipped."""
    called: list[str] = []

    fake_module_infos = [
        types.SimpleNamespace(name="registry"),
        types.SimpleNamespace(name="schemas"),
        types.SimpleNamespace(name="__init__"),
    ]

    package = types.ModuleType(registry.__package__)
    package.__path__ = ["/fake"]

    monkeypatch.setattr(registry, "LOGGER", MagicMock())

    with (
        patch.object(registry.importlib, "import_module", return_value=package) as mock_import,
        patch.object(registry.pkgutil, "iter_modules", return_value=fake_module_infos),
    ):
        registry.register_mcp_tools()

    # import_module should only be called once for the package itself.
    mock_import.assert_called_once_with(registry.__package__)
    registry.LOGGER.info.assert_called_once_with("Registered %d MCP tool(s)", 0)
