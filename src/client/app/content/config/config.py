"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import logging

import streamlit as st
from streamlit import session_state as state

from client.app.content.config.tabs.databases import display_databases
from client.app.content.config.tabs.mcp import display_mcp
from client.app.content.config.tabs.models import display_models
from client.app.content.config.tabs.oci import display_oci
from client.app.content.config.tabs.settings import display_settings

LOGGER = logging.getLogger("content.config.config")


def main() -> None:
    """Streamlit GUI"""
    tab_labels = ["💾 Settings", "🗄️ Databases", "🤖 Models", "☁️ OCI", "🔗 MCP"]
    default_tab = tab_labels[0]
    if "config_active_tab" not in state or state.config_active_tab not in tab_labels:
        state.config_active_tab = default_tab

    def _remember_active_tab() -> None:
        """Persist the current tab label so we can restore it later."""
        state.config_active_tab = state.get("config_tabs", default_tab)

    # Only create tabs if there is at least one
    if tab_labels:
        tabs = st.tabs(
            tab_labels,
            key="config_tabs",
            default=state.config_active_tab,
            on_change=_remember_active_tab,
        )
        _remember_active_tab()

        # Map tab objects to content conditionally
        with tabs[0]:
            display_settings()
        with tabs[1]:
            display_databases()
        with tabs[2]:
            display_models()
        with tabs[3]:
            display_oci()
        with tabs[4]:
            display_mcp()


if __name__ == "__main__":
    main()
