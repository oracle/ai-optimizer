"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import logging

import streamlit as st
from streamlit import session_state as state

from client.app.content.config.tabs.settings import display_settings

LOGGER = logging.getLogger("content.config.config")
LOGGER.info("Configuration page loaded")


def main() -> None:
    """Streamlit GUI"""
    tabs_list = []
    if not state.settings["client_disable_settings"]:
        tabs_list.append("💾 Settings")
    if not state.settings["client_disable_db_cfg"]:
        tabs_list.append("🗄️ Databases")
    if not state.settings["client_disable_model_cfg"]:
        tabs_list.append("🤖 Models")
    if not state.settings["client_disable_oci_cfg"]:
        tabs_list.append("☁️ OCI")
    if not state.settings["client_disable_mcp_cfg"]:
        tabs_list.append("🔗 MCP")

    # Only create tabs if there is at least one
    tab_index = 0
    if tabs_list:
        tabs = st.tabs(tabs_list)

        # Map tab objects to content conditionally
        if not state.settings["client_disable_settings"]:
            with tabs[tab_index]:
                display_settings()
            tab_index += 1
        # if not state.disabled["db_cfg"]:
        #     with tabs[tab_index]:
        #         display_databases()
        #     tab_index += 1
        # if not state.disabled["model_cfg"]:
        #     with tabs[tab_index]:
        #         display_models()
        #     tab_index += 1
        # if not state.disabled["oci_cfg"]:
        #     with tabs[tab_index]:
        #         display_oci()
        #     tab_index += 1
        # if not state.disabled["mcp_cfg"]:
        #     with tabs[tab_index]:
        #         display_mcp()
        #     tab_index += 1


if __name__ == "__main__":
    main()
