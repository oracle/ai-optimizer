from typing import Optional, List, Dict, Any
from common.schema import MCPModelConfig, MCPToolConfig, MCPSettings
from server.bootstrap import mcp as mcp_bootstrap
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.core.mcp")

def get_mcp_model(model_id: str) -> Optional[MCPModelConfig]:
    """Get MCP model configuration by ID"""
    for model in mcp_bootstrap.MCP_MODELS:
        if model.model_id == model_id:
            return model
    return None

def get_mcp_tool(tool_name: str) -> Optional[MCPToolConfig]:
    """Get MCP tool configuration by name"""
    for tool in mcp_bootstrap.MCP_TOOLS:
        if tool.name == tool_name:
            return tool
    return None

def update_mcp_settings(settings: Dict[str, Any]) -> MCPSettings:
    """Update MCP settings"""
    if not mcp_bootstrap.MCP_SETTINGS:
        raise ValueError("MCP settings not initialized")
    
    for key, value in settings.items():
        if hasattr(mcp_bootstrap.MCP_SETTINGS, key):
            setattr(mcp_bootstrap.MCP_SETTINGS, key, value)
    
    return mcp_bootstrap.MCP_SETTINGS