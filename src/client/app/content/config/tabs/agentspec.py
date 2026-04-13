"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore agentspec

import json
import logging

import httpx
import streamlit as st
from streamlit import session_state as state

from client.app.core.api import api_get

LOGGER = logging.getLogger("client.content.config.tabs.agentspec")


###################################
# Functions
###################################
def get_agentspec(force: bool = False) -> None:
    """Get AgentSpec definitions from API Server"""
    if force or "agentspec_specs" not in state or not state.agentspec_specs:
        LOGGER.info("Refreshing state.agentspec_specs")
        try:
            state.agentspec_specs = api_get("agentspec/specs", api_prefix="/v1")
        except httpx.HTTPStatusError as ex:
            LOGGER.error("Unable to get AgentSpec definitions: %s", ex)
            state.agentspec_specs = []


@st.dialog(title="AgentSpec Details", width="large")
def agentspec_details(name: str) -> None:
    """AgentSpec Dialog Box"""
    spec_entry = next((s for s in state.agentspec_specs if s.get("name") == name), None)
    if spec_entry is None:
        st.error(f"AgentSpec not found for {name}")
        return
    st.header(name)
    if spec_entry.get("description"):
        st.subheader("Description", divider="red")
        st.code(spec_entry["description"], wrap_lines=True, height="content")
    st.subheader("Spec", divider="red")
    st.code(json.dumps(spec_entry.get("spec", {}), indent=2), language="json")


def render_specs(specs: list) -> None:
    """Render rows of AgentSpec definitions"""
    data_col_widths = [0.8, 0.2]
    table_col_format = st.columns(data_col_widths, vertical_alignment="center")
    col1, col2 = table_col_format
    col1.markdown("Name", unsafe_allow_html=True)
    col2.markdown("&#x200B;")
    for spec in specs:
        name = spec.get("name", "unknown")
        col1.text_input(
            "Name",
            value=name,
            label_visibility="collapsed",
            disabled=True,
            key=f"agentspec_{name}_input",
        )
        col2.button(
            "Details",
            on_click=agentspec_details,
            key=f"agentspec_{name}_details",
            kwargs={"name": name},
        )


#############################################################################
# MAIN
#############################################################################
def display_agentspec() -> None:
    """Streamlit GUI"""
    st.header("AgentSpec Definitions", divider="red")
    try:
        get_agentspec()
    except httpx.HTTPStatusError:
        st.stop()
    if not state.get("agentspec_specs"):
        st.info("No AgentSpec definitions available.")
        return

    render_specs(state.agentspec_specs)


if __name__ == "__main__":
    display_agentspec()
