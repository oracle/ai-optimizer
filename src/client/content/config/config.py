"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import inspect
import streamlit as st
from streamlit import session_state as state
from client.utils.st_common import style
from client.utils.st_footer import remove_footer

from client.content.config.tabs.settings import display_settings
from client.content.config.tabs.oci import display_oci
from client.content.config.tabs.databases import display_databases
from client.content.config.tabs.models import display_models
from client.content.config.tabs.mcp import display_mcp


def main() -> None:
    """Streamlit GUI"""
    style()
    remove_footer()
    tabs_list = []
    if not state.disabled["settings"]:
        tabs_list.append("💾 Settings")
    if not state.disabled["db_cfg"]:
        tabs_list.append("🗄️ Databases")
    if not state.disabled["model_cfg"]:
        tabs_list.append("🤖 Models")
    if not state.disabled["oci_cfg"]:
        tabs_list.append("☁️ OCI")
    if not state.disabled["mcp_cfg"]:
        tabs_list.append("🔗 MCP")

    # Only create tabs if there is at least one
    tab_index = 0
    if tabs_list:
        tabs = st.tabs(tabs_list)

        # Map tab objects to content conditionally
        if not state.disabled["settings"]:
            with tabs[tab_index]:
                display_settings()
            tab_index += 1
        if not state.disabled["db_cfg"]:
            with tabs[tab_index]:
                display_databases()
            tab_index += 1
        if not state.disabled["model_cfg"]:
            with tabs[tab_index]:
                display_models()
            tab_index += 1
        if not state.disabled["oci_cfg"]:
            with tabs[tab_index]:
                display_oci()
            tab_index += 1
        if not state.disabled["mcp_cfg"]:
            with tabs[tab_index]:
                display_mcp()
            tab_index += 1


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
