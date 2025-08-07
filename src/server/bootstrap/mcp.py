"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
from typing import List, Optional
import os

from server.bootstrap.configfile import ConfigStore
from common.schema import MCPSettings, MCPModelConfig, MCPToolConfig
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("bootstrap.mcp")

# Global configuration holders
MCP_SETTINGS: Optional[MCPSettings] = None
MCP_MODELS: List[MCPModelConfig] = []
MCP_TOOLS: List[MCPToolConfig] = []

def load_mcp_settings(config: dict) -> None:
    """Load MCP configuration from config file"""
    global MCP_SETTINGS, MCP_MODELS, MCP_TOOLS
    
    # Convert to settings object first
    mcp_settings = MCPSettings(
        models=[MCPModelConfig(**model) for model in config.get("models", [])],
        tools=[MCPToolConfig(**tool) for tool in config.get("tools", [])],
        default_model=config.get("default_model"),
        enabled=config.get("enabled", True)
    )
    
    # Set globals
    MCP_SETTINGS = mcp_settings
    MCP_MODELS = mcp_settings.models
    MCP_TOOLS = mcp_settings.tools

    logger.info("Loaded %i MCP Models and %i Tools", len(MCP_MODELS), len(MCP_TOOLS))

def main() -> MCPSettings:
    """Bootstrap MCP Configuration"""
    logger.debug("*** Bootstrapping MCP - Start")

    # Load from ConfigStore if available
    configuration = ConfigStore.get()
    if configuration and configuration.mcp_configs:
        logger.debug("Using MCP configs from ConfigStore")
        # Convert list of MCPModelConfig objects to MCPSettings
        mcp_settings = MCPSettings(
            models=configuration.mcp_configs,
            tools=[],  # No tools in the current schema
            default_model=configuration.mcp_configs[0].model_id if configuration.mcp_configs else None,
            enabled=True
        )
    else:
        # Default MCP configuration
        mcp_settings = MCPSettings(
            models=[
                MCPModelConfig(
                    model_id="llama3.1",
                    service_type="ollama",
                    base_url=os.environ.get("ON_PREM_OLLAMA_URL", "http://localhost:11434"),
                    enabled=True,
                    streaming=False,
                    temperature=1.0,
                    max_tokens=2048
                )
            ],
            tools=[
                MCPToolConfig(
                    name="file_reader",
                    description="Read contents of files",
                    parameters={
                        "path": "string",
                        "encoding": "string"
                    },
                    enabled=True
                )
            ],
            default_model=None,
            enabled=True
        )

    logger.info("Loaded %i MCP Models and %i Tools", len(mcp_settings.models), len(mcp_settings.tools))
    logger.debug("*** Bootstrapping MCP - End")
    logger.info("MCP Settings: %s", mcp_settings.model_dump_json())
    return mcp_settings


if __name__ == "__main__":
    main()