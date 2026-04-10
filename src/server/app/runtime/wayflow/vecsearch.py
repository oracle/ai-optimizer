"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

WayFlow runtime loader and session for the VecSearch flow.

Takes an AgentSpec Flow definition and loads it into WayFlow for execution.
"""
# spell-checker: ignore vecsearch agentspec pyagentspec wayflow wayflowcore

from wayflowcore.flow import Flow as RuntimeFlow

from server.app.agentspec.flow_vecsearch import build_vecsearch_flow
from server.app.core.schemas import ClientSettings
from server.app.runtime.common import fetch_prompt_with_fallback
from server.app.runtime.wayflow.loader import load_runtime_flow
from server.app.runtime.wayflow.session import FlowSession

PROMPT_NAME = "optimizer_vs-tools-default"

DEFAULT_VECSEARCH_INSTRUCTION = (
    "You are a knowledge assistant. Answer questions based on retrieved documents, "
    "providing clear and accurate responses."
)


async def build_vecsearch_runtime_flow(
    client_settings: ClientSettings,
    server_url: str,
    api_key: str,
) -> RuntimeFlow:
    """Build a WayFlow Flow for VecSearch.

    Fetches the system prompt from MCP, then defines the flow
    via pyagentspec and loads it into WayFlow.

    Parameters
    ----------
    client_settings:
        ClientSettings object containing ll_model and vector_search config.
    server_url:
        Full URL to the MCP endpoint.
    api_key:
        API key for the MCP server.

    Returns
    -------
    RuntimeFlow
        A WayFlow Flow ready for execution.
    """
    prompt = await fetch_prompt_with_fallback(server_url, api_key, PROMPT_NAME, DEFAULT_VECSEARCH_INSTRUCTION)
    return await load_runtime_flow(client_settings, server_url, api_key, prompt, build_vecsearch_flow)


VecSearchFlowSession = FlowSession
"""VecSearch flow session — alias for FlowSession.

VecSearch flow inputs (query, thread_id, model, chat_history) match
the base FlowSession exactly, so no customization is needed.
"""
