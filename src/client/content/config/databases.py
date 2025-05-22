"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes a web interface for database configuration using Streamlit (`st`).
It includes a form to input and test database connection settings.
"""
# spell-checker:ignore streamlit, selectbox, selectai

import inspect
import time
import json
import pandas as pd

import streamlit as st
from streamlit import session_state as state

import client.utils.api_call as api_call
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("client.content.config.database")


#####################################################
# Functions
#####################################################
def get_databases(force: bool = False) -> dict[str, dict]:
    """Get a dictionary of all Databases and Store Vector Store Tables"""
    if "database_config" not in state or state["database_config"] == {} or force:
        try:
            endpoint = "v1/databases"
            response = api_call.get(endpoint=endpoint)
            state["database_config"] = {
                item["name"]: {k: v for k, v in item.items() if k != "name"} for item in response
            }
            logger.info("State created: state['database_config']")
        except api_call.ApiError as ex:
            logger.error("Unable to retrieve databases: %s", ex)
            state["database_config"] = {}


def patch_database(name: str, user: str, password: str, dsn: str, wallet_password: str) -> None:
    """Update Database"""
    get_databases()
    # Check if the database configuration is changed, or if not CONNECTED
    if (
        state.database_config[name]["user"] != user
        or state.database_config[name]["password"] != password
        or state.database_config[name]["dsn"] != dsn
        or state.database_config[name]["wallet_password"] != wallet_password
        or not state.database_config[name]["connected"]
    ):
        try:
            endpoint = f"v1/databases/{name}"
            _ = api_call.patch(
                endpoint=endpoint,
                payload={
                    "json": {
                        "user": user,
                        "password": password,
                        "dsn": dsn,
                        "wallet_password": wallet_password,
                    }
                },
            )
            logger.info("Database updated: %s", name)
            state.database_config[name]["connected"] = True
            get_databases(force=True)
            endpoint = "v1/selectai/enabled"
            selectai = api_call.get(
                            endpoint=endpoint,
            )
            logger.info("SelectAI enabled: %s", selectai["enabled"])
            state.database_config[name]["selectai"] = selectai["enabled"]
        except api_call.ApiError as ex:
            logger.error("Database not updated: %s (%s)", name, ex)
            state.database_config[name]["connected"] = False
            state.database_error = str(ex)
    else:
        st.info(f"{name} Database Configuration - No Changes Detected.", icon="ℹ️")
        time.sleep(2)


def drop_vs(vs: dict) -> None:
    """Drop a Vector Storage Table"""
    api_call.delete(endpoint=f"v1/embed/{vs['vector_store']}")
    get_databases(force=True)


def update_selectai(sai_df: pd.DataFrame ) -> None:
    """Update SelectAI Object List"""
    enabled_objects = sai_df[sai_df["Enabled"]].drop(columns=["Enabled"])
    enabled_objects.columns = enabled_objects.columns.str.lower()
    try:
        endpoint = "v1/selectai/objects"
        result = api_call.patch(
            endpoint=endpoint,
            payload={"json": json.loads(enabled_objects.to_json(orient="records"))}
        )
        logger.info("SelectAI Updated.")
        state.database_config["DEFAULT"]["selectai_objects"] = result
    except api_call.ApiError as ex:
        logger.error("SelectAI not updated: %s", ex)


#####################################################
# MAIN
#####################################################
def main() -> None:
    """Streamlit GUI"""
    st.header("Database", divider="red")
    st.write("Configure the database used for Vector Storage and SelectAI.")
    try:
        get_databases()  # Create/Rebuild state
    except api_call.ApiError:
        st.stop()

    # TODO(gotsysdba) Add select for databases
    name = "DEFAULT"
    st.subheader("Configuration")
    with st.form("update_database_config"):
        user = st.text_input(
            "Database User:",
            value=state.database_config[name]["user"],
            key="database_user",
        )
        password = st.text_input(
            "Database Password:",
            value=state.database_config[name]["password"],
            key="database_password",
            type="password",
        )
        dsn = st.text_input(
            "Database Connect String:",
            value=state.database_config[name]["dsn"],
            key="database_dsn",
        )
        wallet_password = st.text_input(
            "Wallet Password (Optional):",
            value=state.database_config[name]["wallet_password"],
            key="database_wallet_password",
            type="password",
        )
        if state.database_config[name]["connected"]:
            st.success("Current Status: Connected")
        else:
            st.error("Current Status: Disconnected")
            if "database_error" in state:
                st.error(f"Update Failed - {state.database_error}", icon="🚨")

        if st.form_submit_button("Save"):
            patch_database(name, user, password, dsn, wallet_password)
            st.rerun()

    if state.database_config[name]["connected"]:
        # Vector Stores
        #############################################
        st.subheader("Database Vector Storage", divider="red")
        st.write("Existing Vector Storage Tables in Database.")
        with st.container(border=True):
            if state.database_config[name]["vector_stores"]:
                vs_col_format = st.columns([2, 5, 10, 3, 3, 5, 3])
                headers = ["\u200b", "Alias", "Model", "Chunk", "Overlap", "Dist. Metric", "Index"]

                # Header row
                for col, header in zip(vs_col_format, headers):
                    col.markdown(f"**<u>{header}</u>**", unsafe_allow_html=True)

                # Vector store rows
                for vs in state.database_config[name]["vector_stores"]:
                    vector_store = vs["vector_store"].lower()
                    fields = ["alias", "model", "chunk_size", "chunk_overlap", "distance_metric", "index_type"]
                    # Handle button in col1
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

        # Select AI
        #############################################
        st.subheader("SelectAI", divider="red")
        if state.database_config[name]["selectai"]:
            st.write("Tables eligible and enabled/disabled for SelectAI.")
            if state.database_config[name]["selectai_objects"]:
                df = pd.DataFrame(
                    state.database_config[name]["selectai_objects"], columns=["owner", "name", "enabled"]
                )
                df.columns = ["Owner", "Name", "Enabled"]
                sai_df = st.data_editor(
                    df,
                    column_config={
                        "enabled": st.column_config.CheckboxColumn(label="Enabled", help="Toggle to enable or disable")
                    },
                    use_container_width=True,
                    hide_index=True,
                )
                if st.button("Apply SelectAI Changes", type='primary'):
                    changes = sai_df[sai_df["Enabled"] != df["Enabled"]]
                    if not changes.empty:
                        update_selectai(sai_df)
                    else:
                        st.write("No changes detected.")
            else:
                st.write("No tables found for SelectAI.")
        else:
            st.write("Unable to use SelectAI with Database.")


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
