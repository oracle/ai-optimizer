"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# spell-checker:ignore selectbox healthz
import json

import streamlit as st
from streamlit import session_state as state

from client.utils import api_call, st_common

from common import logging_config

logger = logging_config.logging.getLogger("client.content.config.tabs.mcp")


###################################
# Functions
###################################
def get_mcp_status() -> dict:
    """Get MCP Status"""
    try:
        return api_call.get(endpoint="v1/mcp/healthz")
    except api_call.ApiError as ex:
        logger.error("Unable to get MCP Status: %s", ex)
        return {}


def get_mcp_client() -> dict:
    """Get MCP Client Configuration"""
    try:
        params = {"server": {state.server["url"]}, "port": {state.server["port"]}}
        mcp_client = api_call.get(endpoint="v1/mcp/client", params=params)
        return json.dumps(mcp_client, indent=2)
    except api_call.ApiError as ex:
        logger.error("Unable to get MCP Client: %s", ex)
        return {}


def get_mcp(force: bool = False) -> list[dict]:
    """Get MCP configs from API Server"""
    if force or "mcp_configs" not in state or not state.mcp_configs:
        logger.info("Refreshing state.mcp_configs")
        endpoints = {
            "tools": "v1/mcp/tools",
            "prompts": "v1/mcp/prompts",
            "resources": "v1/mcp/resources",
        }
        results = {}

        for key, endpoint in endpoints.items():
            try:
                results[key] = api_call.get(endpoint=endpoint)
            except api_call.ApiError as ex:
                logger.error("Unable to get %s: %s", key, ex)
                results[key] = {}

        state.mcp_configs = results


def extract_servers() -> list:
    """Get a list of distinct MCP servers (by prefix)"""
    prefixes = set()

    for _, items in state.mcp_configs.items():
        for item in items or []:  # handle None safely
            name = item.get("name")
            if name and "_" in name:
                prefix = name.split("_", 1)[0]
                prefixes.add(prefix)

    mcp_servers = sorted(prefixes)

    if "optimizer" in mcp_servers:
        mcp_servers.remove("optimizer")
        mcp_servers.insert(0, "optimizer")

    return mcp_servers


@st.dialog(title="Details", width="large")
def mcp_details(mcp_server: str, mcp_type: str, mcp_name: str) -> None:
    """MCP Dialog Box"""
    st.header(f"{mcp_name} - MCP server: {mcp_server}")
    config = next((t for t in state.mcp_configs[mcp_type] if t.get("name") == f"{mcp_server}_{mcp_name}"), None)
    if config.get("description"):
        st.code(config["description"], wrap_lines=True, height="content")
    if config.get("inputSchema"):
        st.subheader("inputSchema", divider="red")
        properties = config["inputSchema"].get("properties", {})
        required_fields = set(config["inputSchema"].get("required", []))
        for name, prop in properties.items():
            req = '<span style="color: red;">(required)</span>' if name in required_fields else ""
            html = f"""
            <h3 style="margin-bottom: 4px;">{name} {req}</h3>
            <ul style="margin: 0 0 8px 20px; padding: 0;">
                <li><b>Description:</b> {prop.get("description", "")}</li>
                <li><b>Type:</b> {prop.get("type", "any")}</li>
                <li><b>Default:</b> {prop.get("default", "None")}</li>
            </ul>
            """
            st.html(html)
    if config.get("outputSchema"):
        st.subheader("outputSchema", divider="red")
    if config.get("arguments"):
        st.subheader("arguments", divider="red")
    if config.get("annotations"):
        st.subheader("annotations", divider="red")
    if config.get("meta"):
        st.subheader("meta", divider="red")


def render_configs(mcp_server: str, mcp_type: str, configs: list) -> None:
    """Render rows of the MCP type"""
    data_col_widths = [0.8, 0.2]
    table_col_format = st.columns(data_col_widths, vertical_alignment="center")
    col1, col2 = table_col_format
    col1.markdown("Name", unsafe_allow_html=True)
    col2.markdown("&#x200B;")
    for mcp_name in configs:
        col1.text_input(
            "Name",
            value=mcp_name,
            label_visibility="collapsed",
            disabled=True,
        )
        col2.button(
            "Details",
            on_click=mcp_details,
            key=f"{mcp_server}_{mcp_name}_details",
            kwargs={"mcp_server": mcp_server, "mcp_type": mcp_type, "mcp_name": mcp_name},
        )


#############################################################################
# MAIN
#############################################################################
def display_mcp() -> None:
    """Streamlit GUI"""
    st.header("Model Context Protocol", divider="red")
    try:
        get_mcp()
    except api_call.ApiError:
        st.stop()
    mcp_status = get_mcp_status()
    if mcp_status.get("status") == "ready":
        st.markdown(f"""
                    The {mcp_status["name"]} is running.  
                    **Version**: {mcp_status["version"]}
                    """)
        with st.expander("Client Configuration"):
            st.code(get_mcp_client(), language="json")
    else:
        st.error("MCP Server is not running!", icon="🛑")
        st.stop()

    selected_mcp_server = st.selectbox(
        "Configured MCP Server(s):",
        options=extract_servers(),
        key="selected_mcp_server",
    )
    if state.mcp_configs["tools"]:
        tools_lookup = st_common.state_configs_lookup("mcp_configs", "name", "tools")
        mcp_tools = [key.split("_", 1)[1] for key in tools_lookup if key.startswith(f"{selected_mcp_server}_")]
        if mcp_tools:
            st.subheader("Tools", divider="red")
            render_configs(selected_mcp_server, "tools", mcp_tools)
    if state.mcp_configs["prompts"]:
        prompts_lookup = st_common.state_configs_lookup("mcp_configs", "name", "prompts")
        mcp_prompts = [key.split("_", 1)[1] for key in prompts_lookup if key.startswith(f"{selected_mcp_server}_")]
        if mcp_prompts:
            st.subheader("Prompts", divider="red")
            render_configs(selected_mcp_server, "prompts", mcp_prompts)
    if state.mcp_configs["resources"]:
        st.subheader("Resources", divider="red")
        resources_lookup = st_common.state_configs_lookup("mcp_configs", "name", "resources")
        mcp_resources = [key.split("_", 1)[1] for key in resources_lookup if key.startswith(f"{selected_mcp_server}_")]
        if mcp_resources:
            st.subheader("Resources", divider="red")
            render_configs(selected_mcp_server, "resources", mcp_resources)


if __name__ == "__main__":
    display_mcp()
