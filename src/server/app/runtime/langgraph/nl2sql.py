"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LangGraph runtime builder for the NL2SQL agent.
"""
# spell-checker: ignore agentspec litellm langgraph pyagentspec checkpointer

from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from server.app.agentspec.agent_nl2sql import DEFAULT_NL2SQL_INSTRUCTION, build_nl2sql_agentspec
from server.app.core.schemas import ClientSettings
from server.app.runtime.common import fetch_prompt_with_fallback
from server.app.runtime.langgraph.loader import load_langgraph_component

PROMPT_NAME = "optimizer_nl2sql-tools-default"


async def build_nl2sql_graph(
    client_settings: ClientSettings,
    server_url: str,
    api_key: str,
    checkpointer: Any = None,
) -> Any:
    """Build a LangGraph agent for NL2SQL with dynamic MCP tool discovery."""
    prompt = await fetch_prompt_with_fallback(server_url, api_key, PROMPT_NAME, DEFAULT_NL2SQL_INSTRUCTION)
    agentspec_agent = build_nl2sql_agentspec(client_settings, server_url, api_key, prompt)
    return await load_langgraph_component(
        agentspec_agent,
        checkpointer=checkpointer or MemorySaver(),
        auth_profile=client_settings.oci.auth_profile,
    )
