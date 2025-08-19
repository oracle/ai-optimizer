"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore fastapi fastmcp

import importlib
import pkgutil

from fastapi import APIRouter
from fastmcp import FastMCP

import common.logging_config as logging_config

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
        except Exception as ex:
            logger.error("Failed to import %s: %s", module_info.name, ex)
            continue

        # Decide what to register based on available functions
        if hasattr(module, "register"):
            logger.info("Registering via %s.register()", module_info.name)
            if ".tools." in module.__name__:
                await module.register(mcp, auth)
            if ".proxies." in module.__name__:
                await module.register(mcp)
            if ".prompts." in module.__name__:
                await module.register(mcp)
        # elif hasattr(module, "register_tool"):
        #     logger.info("Registering tool via %s.register_tool()", module_info.name)
        #     module.register_tool(mcp, auth)
        # elif hasattr(module, "register_prompt"):
        #     logger.info("Registering prompt via %s.register_prompt()", module_info.name)
        #     module.register_prompt(mcp)
        # elif hasattr(module, "register_resource"):
        #     logger.info("Registering resource via %s.register_resource()", module_info.name)
        #     module.register_resource(mcp)
        # elif hasattr(module, "register_proxy"):
        #     logger.info("Registering proxy via %s.register_resource()", module_info.name)
        #     module.register_resource(mcp)
        else:
            logger.debug("No register function in %s, skipping.", module_info.name)


async def register_all_mcp(mcp: FastMCP, auth: APIRouter):
    """
    Auto-discover and register all MCP tools, prompts, resources, and proxies.
    """
    logger.info("Starting Registering MCP Components")
    await _discover_and_register("server.mcp.tools", mcp=mcp, auth=auth)
    await _discover_and_register("server.mcp.proxies", mcp=mcp)
    # await _discover_and_register("server.mcp.prompts", mcp=mcp)
    logger.info("Finished Registering MCP Components")