"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared WayFlow runtime loading utilities.

Provides prompt fetching with fallback and AgentSpec-to-WayFlow loading
for flows that use MCP tools with API key auth.
"""
# spell-checker: ignore agentspec litellm mcphelpers pyagentspec runtimeloader wayflow wayflowcore

import logging
from typing import Callable, cast

from pyagentspec.flows.flow import Flow as AgentSpecFlow
from wayflowcore.agentspec.runtimeloader import AgentSpecLoader
from wayflowcore.flow import Flow as RuntimeFlow
from wayflowcore.mcp.mcphelpers import enable_mcp_without_auth

from server.app.core.schemas import ClientSettings
from server.app.runtime.wayflow.adapters.litellm import get_litellm_wayflow_plugin

LOGGER = logging.getLogger(__name__)

BuildFlowFn = Callable[[ClientSettings, str, str, str], AgentSpecFlow]


async def load_runtime_flow(
    client_settings: ClientSettings,
    server_url: str,
    api_key: str,
    prompt: str,
    build_fn: BuildFlowFn,
) -> RuntimeFlow:
    """Build an AgentSpec flow and load it into WayFlow.

    Parameters
    ----------
    client_settings:
        ClientSettings object.
    server_url:
        MCP server URL for tool transport.
    api_key:
        API key for MCP server auth.
    prompt:
        System prompt to embed in the flow.
    build_fn:
        AgentSpec flow builder function (e.g. build_nl2sql_flow).
    """
    agentspec_flow = build_fn(client_settings, server_url, api_key, prompt)

    # WayFlow requires OAuth for MCP auth validation, but this project uses
    # API key auth via sensitive_headers. Bypass the OAuth check.
    enable_mcp_without_auth()

    loader = AgentSpecLoader(plugins=[get_litellm_wayflow_plugin()])
    return cast(RuntimeFlow, loader.load_component(agentspec_flow))
