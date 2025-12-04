"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectbox

import streamlit as st
from streamlit import session_state as state

from client.utils import st_common
from common import logging_config

logger = logging_config.logging.getLogger("client.utils.st_common")


def tools_sidebar() -> None:
    """Tools Sidebar Settings"""

    # Setup Tool Box
    state.tool_box = {
        "LLM Only": {"description": "Do not use tools", "enabled": True},
        "Vector Search": {"description": "Use AI with Unstructured Data", "enabled": True},
        "NL2SQL": {"description": "Use AI with Structured Data", "enabled": True},
    }

    def _update_set_tool():
        """Update user settings as to which tool is being used"""
        state.client_settings["tools_enabled"] = [state.selected_tool]

    def _disable_tool(tool: str, reason: str = None) -> None:
        """Disable a tool in the tool box"""
        if reason:
            logger.debug("%s Disabled (%s)", tool, reason)
            st.warning(f"{reason}. Disabling {tool}.", icon="⚠️")
        state.tool_box[tool]["enabled"] = False

    if not st_common.is_db_configured():
        logger.debug("Vector Search/NL2SQL Disabled (Database not configured)")
        st.warning("Database is not configured. Disabling Vector Search and NL2SQL tools.", icon="⚠️")
        _disable_tool("Vector Search")
        _disable_tool("NL2SQL")
    else:
        # Check to enable Vector Store
        embed_models_enabled = st_common.enabled_models_lookup("embed")
        db_alias = state.client_settings.get("database", {}).get("alias")
        database_lookup = st_common.state_configs_lookup("database_configs", "name")
        if not embed_models_enabled:
            _disable_tool("Vector Search", "No embedding models are configured and/or enabled.")
        elif not database_lookup[db_alias].get("vector_stores"):
            _disable_tool("Vector Search", "Database has no vector stores.")
        else:
            # Check if any vector stores use an enabled embedding model
            vector_stores = database_lookup[db_alias].get("vector_stores", [])
            usable_vector_stores = [vs for vs in vector_stores if vs.get("model") in embed_models_enabled]
            if not usable_vector_stores:
                _disable_tool("Vector Search", "No vector stores match the enabled embedding models")

    tool_box = [key for key, val in state.tool_box.items() if val["enabled"]]
    current_tool = state.client_settings["tools_enabled"][0]
    if current_tool not in tool_box:
        state.client_settings["tools_enabled"] = ["LLM Only"]
    tool_index = tool_box.index(current_tool) if current_tool in tool_box else 0
    st.sidebar.selectbox(
        "Tool Selection",
        tool_box,
        index=tool_index,
        label_visibility="collapsed",
        on_change=_update_set_tool,
        key="selected_tool",
    )
