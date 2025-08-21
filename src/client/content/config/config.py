"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import inspect
import streamlit as st
from streamlit import session_state as state

from client.content.config.tabs.settings import get_settings, display_settings
from client.content.config.tabs.oci import get_oci, display_oci
from client.content.config.tabs.databases import get_databases, display_databases
from client.content.config.tabs.models import get_models, display_models


def main() -> None:
    """Streamlit GUI"""
    # Ensure all our configs exist
    get_settings()
    get_databases()
    get_models()
    get_oci()

    tabs_list = []
    if not state.disabled["settings"]:
        tabs_list.append("💾 Settings")
    if not state.disabled["db_cfg"]:
        tabs_list.append("🗄️ Databases")
    if not state.disabled["model_cfg"]:
        tabs_list.append("🤖 Models")
    if not state.disabled["oci_cfg"]:
        tabs_list.append("☁️ OCI")

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


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
