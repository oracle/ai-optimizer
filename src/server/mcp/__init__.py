"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore fastapi fastmcp

import importlib
import pkgutil

from fastapi import APIRouter
from fastmcp import FastMCP

from common import logging_config

logger = logging_config.logging.getLogger("mcp.__init__.py")


async def _discover_and_register(
    package: str,
    mcp: FastMCP = None,
    auth: APIRouter = None,
):
    """Import all modules in a package and call their register function."""
    try:
        pkg = importlib.import_module(package)
    except ImportError:
        logger.warning("Package %s not found, skipping.", package)
        return

    for module_info in pkgutil.walk_packages(pkg.__path__, prefix=f"{package}."):
        if module_info.name.endswith("__init__"):
            continue

        try:
            module = importlib.import_module(module_info.name)
        except (ImportError, ModuleNotFoundError, AttributeError, SyntaxError, ValueError) as ex:
            logger.error("Failed to import %s: %s", module_info.name, ex)
            continue

        # Decide what to register based on available functions
        if hasattr(module, "register"):
            logger.info("Registering via %s.register()", module_info.name)
            if ".tools." in module.__name__:
                logger.info("Registering tool via %s.register_tool()", module_info.name)
                await module.register(mcp, auth)
            if ".proxies." in module.__name__:
                logger.info("Registering proxy via %s.register_proxy()", module_info.name)
                await module.register(mcp)
            if ".prompts." in module.__name__:
                logger.info("Registering prompt via %s.register_prompt()", module_info.name)
                await module.register(mcp)
            if ".resources." in module.__name__:
                logger.info("Registering resource via %s.register_resource()", module_info.name)
                await module.register(mcp)
        else:
            logger.debug("No register function in %s, skipping.", module_info.name)


async def register_all_mcp(mcp: FastMCP, auth: APIRouter):
    """
    Auto-discover and register all MCP tools, prompts, resources, and proxies.
    """
    logger.info("Starting Registering MCP Components")
    await _discover_and_register("server.mcp.tools", mcp=mcp, auth=auth)
    await _discover_and_register("server.mcp.proxies", mcp=mcp)
    await _discover_and_register("server.mcp.prompts", mcp=mcp)
    await _discover_and_register("server.mcp.resources", mcp=mcp)
    logger.info("Finished Registering MCP Components")
