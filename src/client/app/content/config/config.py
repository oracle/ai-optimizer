"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: ignore agentspec

import logging

import streamlit as st
from streamlit import session_state as state

from client.app.content.config.tabs.agentspec import display_agentspec
from client.app.content.config.tabs.databases import display_databases
from client.app.content.config.tabs.mcp import display_mcp
from client.app.content.config.tabs.models import display_models
from client.app.content.config.tabs.oci import display_oci
from client.app.content.config.tabs.settings import display_settings
from client.app.content.config.tabs.users import display_users
from client.app.core.auth import is_admin

LOGGER = logging.getLogger("content.config.config")


def main() -> None:
    """Streamlit GUI"""
    show_users = is_admin() and state.get("auth_mode") == "local_users"
    tab_definitions = [("💾 Settings", display_settings)]
    if show_users:
        tab_definitions.append(("👥 Users", display_users))
    tab_definitions.extend(
        [
            ("🗄️ Databases", display_databases),
            ("🤖 Models", display_models),
            ("☁️ OCI", display_oci),
            ("🔗 MCP", display_mcp),
            ("🧬 AgentSpec", display_agentspec),
        ]
    )
    tab_labels = [label for label, _display in tab_definitions]
    default_tab = tab_labels[0]
    if "config_active_tab" not in state or state.config_active_tab not in tab_labels:
        state.config_active_tab = default_tab

    def _remember_active_tab() -> None:
        """Persist the current tab label so we can restore it later."""
        state.config_active_tab = state.get("config_tabs", default_tab)

    tabs = st.tabs(
        tab_labels,
        key="config_tabs",
        default=state.config_active_tab,
        on_change=_remember_active_tab,
    )
    _remember_active_tab()

    active_index = tab_labels.index(state.config_active_tab)
    with tabs[active_index]:
        tab_definitions[active_index][1]()


if __name__ == "__main__":
    main()
