"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# spell-checker:ignore streamable
import os

# from langchain_mcp_adapters.client import MultiServerMCPClient
# from typing import Optional, List, Dict, Any
# from common.schema import MCPModelConfig, MCPToolConfig, MCPSettings
# from server.bootstrap import mcp as mcp_bootstrap
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.core.mcp")


def get_client(server: str = "http://127.0.0.1", port: int = 8000) -> dict:
    """Get the MCP Client Configuration"""
    mcp_client = {
        "mcpServers": {
            "optimizer": {
                "type": "streamableHttp",
                "transport": "streamable_http",
                "url": f"{server}:{port}/mcp/",
                "headers": {"Authorization": f"Bearer {os.getenv('API_SERVER_KEY')}"},
            }
        }
    }

    return mcp_client


# def get_mcp_model(model_id: str) -> Optional[MCPModelConfig]:
#     """Get MCP model configuration by ID"""
#     for model in mcp_bootstrap.MCP_MODELS:
#         if model.model_id == model_id:
#             return model
#     return None


# def get_mcp_tool(tool_name: str) -> Optional[MCPToolConfig]:
#     """Get MCP tool configuration by name"""
#     for tool in mcp_bootstrap.MCP_TOOLS:
#         if tool.name == tool_name:
#             return tool
#     return None


# def update_mcp_settings(settings: Dict[str, Any]) -> MCPSettings:
#     """Update MCP settings"""
#     if not mcp_bootstrap.MCP_SETTINGS:
#         raise ValueError("MCP settings not initialized")

#     for key, value in settings.items():
#         if hasattr(mcp_bootstrap.MCP_SETTINGS, key):
#             setattr(mcp_bootstrap.MCP_SETTINGS, key, value)

#     return mcp_bootstrap.MCP_SETTINGS
