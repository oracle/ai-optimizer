"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes a web interface for database configuration using Streamlit (`st`).
It includes a form to input and test database connection settings.
"""
# spell-checker:ignore selectbox

import streamlit as st
from streamlit import session_state as state

from client.utils import api_call, st_common
from common import logging_config

logger = logging_config.logging.getLogger("client.content.config.tabs.database")


#####################################################
# Functions
#####################################################


def _render_database_configuration_form(database_lookup: dict, selected_database_alias: str) -> dict:
    """Render the database configuration form.

    Returns:
        dict: Supplied configuration values
    """
    supplied = {}
    connected = database_lookup[selected_database_alias]["connected"]

    with st.container(border=True):
        supplied["user"] = st.text_input(
            "Database User:",
            value=database_lookup[selected_database_alias]["user"],
            key="database_user",
        )
        supplied["password"] = st.text_input(
            "Database Password:",
            value=database_lookup[selected_database_alias]["password"],
            key="database_password",
            type="password",
        )
        supplied["dsn"] = st.text_input(
            "Database Connect String:",
            value=database_lookup[selected_database_alias]["dsn"],
            key="database_dsn",
        )
        supplied["wallet_password"] = st.text_input(
            "Wallet Password (Optional):",
            value=database_lookup[selected_database_alias]["wallet_password"],
            key="database_wallet_password",
            type="password",
        )

        # Display connection status
        if connected:
            st.success("Current Status: Connected")
        else:
            st.error("Current Status: Disconnected")
            if "database_error" in state:
                st.error(f"Update Failed - {state.database_error}", icon="🚨")

        # Save button
        if st.button("Save Database", key="save_database"):
            if patch_database(selected_database_alias, supplied, connected):
                st.rerun()

    return supplied


def _render_vector_stores_section(database_lookup: dict, selected_database_alias: str) -> None:
    """Render the vector stores display section."""
    st.subheader("Database Vector Storage", divider="red")
    st.write("Existing Vector Storage Tables in Database.")

    with st.container(border=True):
        vector_stores = database_lookup[selected_database_alias]["vector_stores"]
        if vector_stores:
            vs_col_format = st.columns([2, 5, 10, 3, 3, 5, 3])
            headers = ["\u200b", "Alias", "Model", "Chunk", "Overlap", "Dist. Metric", "Index"]

            # Header row
            for col, header in zip(vs_col_format, headers):
                col.markdown(f"**<u>{header}</u>**", unsafe_allow_html=True)

            # Vector store rows
            for vs in vector_stores:
                vector_store = vs["vector_store"].lower()
                fields = ["alias", "model", "chunk_size", "chunk_overlap", "distance_metric", "index_type"]
                # Delete Button in Column1
                vs_col_format[0].button(
                    "",
                    icon="🗑️",
                    key=f"vector_stores_{vector_store}",
                    on_click=drop_vs,
                    args=[vs],
                    help="Drop Vector Storage Table",
                )
                for col, field in zip(vs_col_format[1:], fields):  # Starting from col2
                    col.text_input(
                        field.capitalize(),
                        value=vs[field],
                        label_visibility="collapsed",
                        key=f"vector_stores_{vector_store}_{field}",
                        disabled=True,
                    )
        else:
            st.write("No Vector Stores Found")


def get_databases(force: bool = False) -> None:
    """Get Databases from API Server"""
    if force or "database_configs" not in state or not state.database_configs:
        try:
            logger.info("Refreshing state.database_configs")
            # Validation will be done on currently configured client database
            # validation includes new vector_stores, etc.
            client_database = state.client_settings.get("database", {}).get("alias", {})
            _ = api_call.get(endpoint=f"v1/databases/{client_database}")

            # Update state
            state.database_configs = api_call.get(endpoint="v1/databases")
        except api_call.ApiError as ex:
            logger.error("Unable to populate state.database_configs: %s", ex)
            state.database_configs = {}


def patch_database(name: str, supplied: dict, connected: bool) -> bool:
    """Update Database"""
    # Check if the database configuration is changed, or if not CONNECTED
    rerun = False
    existing = next((item for item in state.database_configs if item["name"] == name), None)
    differences = {key: (existing.get(key), supplied[key]) for key in supplied if existing.get(key) != supplied[key]}
    if differences or not connected:
        rerun = True
        try:
            with st.spinner(text="Updating Database...", show_time=True):
                _ = api_call.patch(
                    endpoint=f"v1/databases/{name}",
                    payload={"json": supplied},
                )
            logger.info("Database updated: %s", name)
            st_common.clear_state_key("database_configs")
        except api_call.ApiError as ex:
            logger.error("Database not updated: %s (%s)", name, ex)
            _ = [d.update(connected=False) for d in state.database_configs if d.get("name") == name]
            state.database_error = str(ex)
    else:
        st.toast("No changes detected.", icon="ℹ️")

    return rerun


def drop_vs(vs: dict) -> None:
    """Drop a Vector Storage Table"""
    api_call.delete(endpoint=f"v1/embed/{vs['vector_store']}")
    get_databases(force=True)


#####################################################
# MAIN
#####################################################
def display_databases() -> None:
    """Streamlit GUI"""
    st.header("Database", divider="red")

    try:
        get_databases()
    except api_call.ApiError:
        st.stop()

    st.subheader("Configuration")
    database_lookup = st_common.state_configs_lookup("database_configs", "name")

    # Get a list of database names, and allow user to select
    selected_database_alias = st.selectbox(
        "Current Database:",
        options=list(database_lookup.keys()),
        index=list(database_lookup.keys()).index(state.client_settings.get("database", {}).get("alias")),
        key="selected_database",
        on_change=st_common.update_client_settings("database"),
    )

    # Render configuration form
    _render_database_configuration_form(database_lookup, selected_database_alias)
    connected = database_lookup[selected_database_alias]["connected"]

    # Only show additional sections if database is connected
    if connected:
        _render_vector_stores_section(database_lookup, selected_database_alias)


if __name__ == "__main__":
    display_databases()
