"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LangGraph runtime builder for the VecSearch flow.
"""
# spell-checker: ignore vecsearch agentspec litellm langgraph pyagentspec

from typing import Any

from server.app.agentspec.flow_vecsearch import build_vecsearch_flow
from server.app.core.schemas import ClientSettings
from server.app.runtime.common import fetch_prompt_with_fallback
from server.app.runtime.langgraph.loader import load_langgraph_component

PROMPT_NAME = "optimizer_vs-tools-default"


async def build_vecsearch_graph(
    client_settings: ClientSettings,
    server_url: str,
    api_key: str,
) -> Any:
    """Build a LangGraph flow for VecSearch."""
    prompt = await fetch_prompt_with_fallback(server_url, api_key, PROMPT_NAME)
    agentspec_flow = build_vecsearch_flow(client_settings, server_url, api_key, prompt)
    return await load_langgraph_component(agentspec_flow, auth_profile=client_settings.oci.auth_profile)
