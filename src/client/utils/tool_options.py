"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectbox subtools

import logging

import streamlit as st
from streamlit import session_state as state

from client.utils import st_common
from common import help_text

LOGGER = logging.getLogger("client.utils.st_common")


def tools_sidebar(show_vs_subtools: bool = True) -> None:
    """Tools Sidebar Settings

    Args:
        show_vs_subtools: Whether to show VS sub-tool options (rephrase, grade).
            Set to False for testbed page where these don't apply.
    """

    st.sidebar.subheader("Toolkit", divider="red")

    # Setup Tool Box
    state.tool_box = {
        "Vector Search": {"description": "Use AI with Unstructured Data", "enabled": True},
        "NL2SQL": {"description": "Use AI with Structured Data", "enabled": True},
    }

    def _update_set_tool():
        """Update user settings as to which tool is being used"""
        state.client_settings["tools_enabled"] = [state.selected_tools]

    def _update_vs_subtools():
        """Update user settings as to which vector search subtools are enabled"""
        state.client_settings["vector_search"]["discovery"] = state.selected_vs_discovery
        if "selected_vs_rephrase" in state:
            state.client_settings["vector_search"]["rephrase"] = state.selected_vs_rephrase
        if "selected_vs_grade" in state:
            state.client_settings["vector_search"]["grade"] = state.selected_vs_grade

    def _disable_tool(tool: str, reason: str = None) -> None:
        """Disable a tool in the tool box"""
        if reason:
            LOGGER.debug("%s Disabled (%s)", tool, reason)
            st.warning(f"{reason}. Disabling {tool}.", icon="⚠️")
        state.tool_box[tool]["enabled"] = False

    if not st_common.is_db_configured():
        LOGGER.debug("Vector Search/NL2SQL Disabled (Database not configured)")
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

    # Remove any tools_enabled entries that are no longer available in tool_box
    tools_enabled = state.client_settings.get("tools_enabled", [])
    valid_tools = [tool for tool in tools_enabled if tool in tool_box]
    if valid_tools != tools_enabled:
        state.client_settings["tools_enabled"] = valid_tools

    st.sidebar.multiselect(
        "Tool Selection",
        options=tool_box,
        default=state.client_settings["tools_enabled"],
        placeholder="Language Model Only",
        label_visibility="collapsed",
        on_change=_update_set_tool,
        key="selected_tools",
    )
    state.client_settings["tools_enabled"] = state.selected_tools

    # Vector Search Sub-Tools
    if "Vector Search" in state.client_settings["tools_enabled"]:
        st.sidebar.checkbox(
            "Store Discovery",
            help=help_text.help_dict["vector_search_discovery"],
            value=state.client_settings["vector_search"]["discovery"],
            key="selected_vs_discovery",
            on_change=_update_vs_subtools,
        )
        if show_vs_subtools:
            st.sidebar.checkbox(
                "Prompt Rephrase",
                help=help_text.help_dict["vector_search_rephrase"],
                value=state.client_settings["vector_search"]["rephrase"],
                key="selected_vs_rephrase",
                on_change=_update_vs_subtools,
            )
            st.sidebar.checkbox(
                "Document Grading",
                help=help_text.help_dict["vector_search_grade"],
                value=state.client_settings["vector_search"]["grade"],
                key="selected_vs_grade",
                on_change=_update_vs_subtools,
            )
