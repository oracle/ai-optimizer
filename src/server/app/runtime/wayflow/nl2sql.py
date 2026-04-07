"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

WayFlow runtime loader and session for the NL2SQL agent.

Takes an AgentSpec Agent definition with dynamic MCP tool discovery
and loads it into WayFlow for execution.
"""
# spell-checker: ignore agentspec litellm mcphelpers pyagentspec runtimeloader sqlcl wayflow wayflowcore

import logging
from typing import Any, Optional, Sequence, cast

from wayflowcore.agent import Agent as RuntimeAgent
from wayflowcore.agentspec.runtimeloader import AgentSpecLoader
from wayflowcore.mcp.mcphelpers import enable_mcp_without_auth

from server.app.agentspec.agent_nl2sql import (
    DEFAULT_NL2SQL_INSTRUCTION,
    build_nl2sql_agentspec,
)
from server.app.core.schemas import ClientSettings
from server.app.runtime.common import fetch_prompt_with_fallback
from server.app.runtime.wayflow.adapters.litellm import get_litellm_wayflow_plugin
from server.app.runtime.wayflow.llm_only import AgentChatSession
from server.app.runtime.wayflow.session import update_agent_state

LOGGER = logging.getLogger(__name__)

PROMPT_NAME = "optimizer_nl2sql-tools-default"


async def build_nl2sql_agent(
    client_settings: ClientSettings,
    server_url: str,
    api_key: str,
) -> RuntimeAgent:
    """Build a WayFlow Agent for NL2SQL with dynamic MCP tool discovery.

    Fetches the system prompt from MCP, then defines the agent
    via pyagentspec and loads it into WayFlow.

    Parameters
    ----------
    client_settings:
        ClientSettings object containing ll_model and database config.
    server_url:
        Full URL to the MCP endpoint.
    api_key:
        API key for the MCP server.

    Returns
    -------
    RuntimeAgent
        A WayFlow Agent ready for execution.
    """
    prompt = await fetch_prompt_with_fallback(server_url, api_key, PROMPT_NAME, DEFAULT_NL2SQL_INSTRUCTION)
    agentspec_agent = build_nl2sql_agentspec(client_settings, server_url, api_key, prompt)

    # WayFlow requires OAuth for MCP auth validation, but this project uses
    # API key auth via sensitive_headers. Bypass the OAuth check.
    enable_mcp_without_auth()

    loader = AgentSpecLoader(plugins=[get_litellm_wayflow_plugin()])
    return cast(RuntimeAgent, loader.load_component(agentspec_agent))


class NL2SQLAgentSession(AgentChatSession):
    """NL2SQL agent session with database connection context.

    Augments the agent's system prompt with the configured connection name,
    model, and thread_id so the LLM passes them to sqlcl_* tool calls.
    """

    def __init__(
        self,
        agent: RuntimeAgent,
        client_settings: ClientSettings,
        thread_id: str = "",
        conversation_id: Optional[str] = None,
        span_processors: Optional[Sequence[Any]] = None,
    ):
        super().__init__(agent, conversation_id=conversation_id, span_processors=span_processors)

        connection_name = client_settings.database.alias
        ll_model = client_settings.ll_model
        model = f"{ll_model.provider}/{ll_model.id}"

        # Provide values the LLM should use when a tool's schema asks for
        # these parameters.  The LLM sees each tool's declared parameters
        # via function-calling schemas, so we don't hard-code which tool
        # gets which value — we just supply the values and let the schema
        # drive parameter selection.
        context = "\n\nUse these values when a sqlcl_* tool parameter asks for them:\n"
        context += f"- model: {model}\n"
        if thread_id:
            context += f"- thread_id: {thread_id}\n"
        if connection_name:
            context += f"- connection_name: {connection_name}\n"

        agent.custom_instruction = (agent.custom_instruction or "") + context
        update_agent_state(agent)
