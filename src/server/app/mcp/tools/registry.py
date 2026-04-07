"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP tool registration lifecycle.
"""
# spell-checker:ignore fastmcp

import logging

from .vs_discovery import register_discovery_tool
from .vs_grade import register_grade_tool
from .vs_rephrase import register_rephrase_tool
from .vs_retriever import register_retriever_tool

LOGGER = logging.getLogger(__name__)


def register_mcp_tools() -> None:
    """Register all MCP vector-search tools with FastMCP."""
    register_discovery_tool()
    register_grade_tool()
    register_rephrase_tool()
    register_retriever_tool()
    LOGGER.info("Registered 4 MCP tool(s)")
