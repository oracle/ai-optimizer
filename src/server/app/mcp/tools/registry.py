"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP tool registration lifecycle.

Tools are auto-discovered from this package.  Any module that defines a
callable whose name starts with ``register_`` will have that callable
invoked at startup.  Modules named ``registry``, ``schemas``, and
``__init__`` are skipped.
"""
# spell-checker:ignore fastmcp pkgutil

import importlib
import logging
import pkgutil

LOGGER = logging.getLogger(__name__)

_SKIP_MODULES = frozenset({"registry", "schemas", "__init__"})


_PACKAGE = __package__ or __name__


def register_mcp_tools() -> None:
    """Discover and register all MCP tools in this package."""
    package = importlib.import_module(_PACKAGE)
    count = 0

    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name in _SKIP_MODULES:
            continue

        module = importlib.import_module(f"{_PACKAGE}.{module_info.name}")

        for attr_name in sorted(dir(module)):
            if attr_name.startswith("register_") and callable(getattr(module, attr_name)):
                getattr(module, attr_name)()
                count += 1

    LOGGER.info("Registered %d MCP tool(s)", count)
