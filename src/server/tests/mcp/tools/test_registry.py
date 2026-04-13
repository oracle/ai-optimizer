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

_PACKAGE = registry._PACKAGE


def _make_module(name: str, **attrs: object) -> types.ModuleType:
    """Create a ModuleType and inject attributes via sys.modules-style assignment."""
    mod = types.ModuleType(name)
    for key, val in attrs.items():
        object.__setattr__(mod, key, val)
    return mod


def test_register_mcp_tools_discovers_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """register_mcp_tools should auto-discover and call every register_* function."""
    called: list[str] = []

    # Build fake modules with register_* callables.
    mod_alpha = _make_module("alpha", register_alpha_tool=lambda: called.append("alpha"))
    mod_beta = _make_module("beta", register_beta_tool=lambda: called.append("beta"))

    # A module with no register_* should be imported but contribute nothing.
    mod_empty = _make_module("empty", helper=lambda: None)

    fake_modules: dict[str, types.ModuleType] = {
        "alpha": mod_alpha,
        "beta": mod_beta,
        "empty": mod_empty,
    }

    # Fake iter_modules to yield our test modules (skip list tested implicitly
    # because we never yield "registry" or "schemas").
    fake_module_infos = [
        types.SimpleNamespace(name=name) for name in fake_modules
    ]

    package = _make_module(_PACKAGE)
    package.__path__ = ["/fake"]  # type: ignore[attr-defined]

    mock_logger = MagicMock()
    monkeypatch.setattr(registry, "LOGGER", mock_logger)

    with (
        patch.object(registry.importlib, "import_module") as mock_import,
        patch.object(registry.pkgutil, "iter_modules", return_value=fake_module_infos),
    ):
        mock_import.side_effect = lambda name: (
            package if name == _PACKAGE else fake_modules[name.rsplit(".", 1)[-1]]
        )

        registry.register_mcp_tools()

    assert sorted(called) == ["alpha", "beta"]
    mock_logger.info.assert_called_once_with("Registered %d MCP tool(s)", 2)


def test_register_mcp_tools_skips_reserved_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Modules named registry, schemas, or __init__ must be skipped."""
    fake_module_infos = [
        types.SimpleNamespace(name="registry"),
        types.SimpleNamespace(name="schemas"),
        types.SimpleNamespace(name="__init__"),
    ]

    package = _make_module(_PACKAGE)
    package.__path__ = ["/fake"]  # type: ignore[attr-defined]

    mock_logger = MagicMock()
    monkeypatch.setattr(registry, "LOGGER", mock_logger)

    with (
        patch.object(registry.importlib, "import_module", return_value=package) as mock_import,
        patch.object(registry.pkgutil, "iter_modules", return_value=fake_module_infos),
    ):
        registry.register_mcp_tools()

    # import_module should only be called once for the package itself.
    mock_import.assert_called_once_with(_PACKAGE)
    mock_logger.info.assert_called_once_with("Registered %d MCP tool(s)", 0)
