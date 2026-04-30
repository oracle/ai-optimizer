"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

NL2SQL Agent — AgentSpec definition with dynamic MCP tool discovery.

Defines an AgentSpecAgent that uses an MCPToolBox to dynamically discover
all tools from the MCP server at runtime. The system prompt guides the LLM
to use sqlcl_* tools for database operations.

No runtime imports.
"""
# spell-checker: ignore agentspec litellm pyagentspec sqlcl

from pyagentspec.agent import Agent as AgentSpecAgent
from pyagentspec.mcp import MCPToolBox

from server.app.agentspec.adapters.mcp import build_mcp_transport
from server.app.agentspec.agent_llm_only import build_llm_config
from server.app.core.schemas import ClientSettings

DEFAULT_NL2SQL_INSTRUCTION = (
    "You are a database assistant. Convert natural language questions to SQL "
    "and provide clear answers based on query results."
)


def build_nl2sql_agentspec(
    client_settings: ClientSettings,
    server_url: str,
    api_key: str,
    system_prompt: str,
) -> AgentSpecAgent:
    """Build a pyagentspec Agent definition for NL2SQL with dynamic tool discovery.

    The agent uses an MCPToolBox to discover all available tools from the
    MCP server at runtime. This means new tools (e.g. sqlcl_list-connections)
    are automatically available without code changes.

    Parameters
    ----------
    client_settings:
        The ClientSettings object containing ll_model config.
    server_url:
        MCP server URL for tool transport.
    api_key:
        API key for MCP server auth.
    system_prompt:
        System instruction for the agent.

    Returns
    -------
    AgentSpecAgent
        A pyagentspec Agent ready to be serialized or loaded by a runtime adapter.
    """
    llm_config = build_llm_config(client_settings)
    transport = build_mcp_transport(server_url, api_key)

    return AgentSpecAgent(
        id="nl2sql-agent",
        name="NL2SQL Agent",
        llm_config=llm_config,
        system_prompt=system_prompt,
        tools=[],
        toolboxes=[MCPToolBox(name="sqlcl-tools", client_transport=transport)],
        human_in_the_loop=True,
    )
