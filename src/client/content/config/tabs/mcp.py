"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import streamlit as st
from streamlit import session_state as state

import client.utils.api_call as api_call

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("client.content.config.tabs.mcp")


###################################
# Functions
###################################
def get_mcp_status() -> dict:
    """Get MCP Status"""
    try:
        logger.info("Checking MCP Status")
        return api_call.get(endpoint="v1/mcp/healthz")
    except api_call.ApiError as ex:
        logger.error("Unable to get MCP Status: %s", ex)
        return {}

def get_mcp_tools(force: bool = False) -> list[dict]:
    """Get MCP Tools from API Server"""
    if force or "mcp_tools" not in state or not state.mcp_tools:
        try:
            logger.info("Refreshing state.mcp_tools")
            state.mcp_tools = api_call.get(endpoint="v1/mcp/tools")
        except api_call.ApiError as ex:
            logger.error("Unable to populate state.mcp_tools: %s", ex)
            state.mcp_tools = {}


# @st.cache_data(show_spinner="Connecting to MCP Backend...", ttl=60)
# def get_server_capabilities(fastapi_base_url):
#     """Fetches the lists of tools and resources from the FastAPI backend."""
#     try:
#         # Get API key from environment or generate one
#         api_key = os.getenv("API_SERVER_KEY")
#         headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

#         # First check if MCP is enabled and initialized
#         status_response = requests.get(f"{fastapi_base_url}/v1/mcp/status", headers=headers)
#         if status_response.status_code == 200:
#             status = status_response.json()
#             if not status.get("enabled", False):
#                 st.warning("MCP is not enabled. Please enable it in the configuration.")
#                 return {"error": "MCP not enabled"}, {"error": "MCP not enabled"}, {"error": "MCP not enabled"}
#             if not status.get("initialized", False):
#                 st.info("MCP is enabled but not yet initialized. Please select a model first.")
#                 return {"tools": []}, {"static": [], "dynamic": []}, {"prompts": []}

#         tools_response = requests.get(f"{fastapi_base_url}/v1/mcp/tools", headers=headers)
#         tools_response.raise_for_status()
#         tools = tools_response.json()

#         resources_response = requests.get(f"{fastapi_base_url}/v1/mcp/resources", headers=headers)
#         resources_response.raise_for_status()
#         resources = resources_response.json()

#         prompts_response = requests.get(f"{fastapi_base_url}/v1/mcp/prompts", headers=headers)
#         prompts_response.raise_for_status()
#         prompts = prompts_response.json()

#         return tools, resources, prompts
#     except requests.exceptions.RequestException as e:
#         st.error(f"Could not connect to the MCP backend at {fastapi_base_url}. Is it running? Error: {e}")
#         return {"tools": []}, {"static": [], "dynamic": []}, {"prompts": []}


#############################################################################
# MAIN
#############################################################################
def display_mcp() -> None:
    """Streamlit GUI"""
    st.header("Model Context Protocol", divider="red")
    try:
        get_mcp_tools()
    except api_call.ApiError:
        st.stop()
    mcp_status = get_mcp_status()
    if mcp_status.get("status") == "ready":
        st.write(f"The {mcp_status['name']} is running.  Version: {mcp_status['version']}")
    st.write(state.mcp_tools)
