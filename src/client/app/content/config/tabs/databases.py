"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectbox

import logging

import httpx
import streamlit as st
from streamlit import session_state as state

from client.app.core import helpers
from client.app.core.api import api_delete, api_get, api_post, api_put
from client.app.core.embed_status import render_active_embed_jobs

LOGGER = logging.getLogger("client.content.config.tabs.databases")

ADD_NEW = "Add New..."


#####################################################
# Functions
#####################################################
def _fetch_database(alias: str) -> dict | None:
    """Fetch a single database config with sensitive fields included."""
    try:
        return api_get(f"databases/{alias}", params={"include_sensitive": "true"})
    except httpx.HTTPStatusError:
        return None


def _on_database_change() -> None:
    """Clear runtime widget state when database selection changes."""
    selected = state.get("runtime_database_selector")
    helpers.clear_runtime_state()
    if selected is not None:
        state["runtime_database_selector"] = selected
    if selected and selected != ADD_NEW:
        helpers.sync_client_setting("database", "alias", selected)


def _drop_vector_store(db_alias: str, table_name: str) -> None:
    """Drop a vector store table via the API and refresh settings."""
    try:
        api_delete(f"databases/{db_alias}/vector-stores/{table_name}", toast=f"Vector store **{table_name}** dropped.")
        helpers.refresh_settings()
        state["runtime_database_selector"] = db_alias
    except httpx.HTTPStatusError as exc:
        st.error(f"Drop failed: {helpers.extract_error_detail(exc)}")


def _handle_form_submit(selected: str, is_new: bool, alias: str, form_data: dict, db_config: dict) -> None:
    """Process database form submission (create or update)."""
    if not is_new:
        changes = {k: v for k, v in form_data.items() if db_config.get(k) != v}
        if not changes and db_config.get("usable"):
            helpers.sync_client_setting("database", "alias", selected)
            st.toast("No changes detected.", icon="ℹ️")
            return

    new_alias = ""
    try:
        if is_new:
            new_alias = alias.strip() if alias else ""
            if not new_alias:
                st.error("Alias is required.")
                return
            form_data["alias"] = new_alias
            with st.spinner("Creating database configuration..."):
                result = api_post(
                    "databases",
                    json=helpers.build_payload(form_data),
                    toast=f"Database **{new_alias}** created.",
                    timeout=45,
                )
        else:
            with st.spinner("Updating database configuration...", show_time=True):
                result = api_put(f"databases/{selected}", json=helpers.build_payload(form_data), timeout=45)
        helpers.refresh_settings()
        active_alias = new_alias if is_new else selected
        if active_alias and not result.get("error"):
            helpers.sync_client_setting("database", "alias", active_alias)
        if is_new:
            state["_pending_db_select"] = new_alias
        if result.get("error"):
            st.warning(f"Saved, but connection failed: {result['error']}")
    except httpx.TimeoutException:
        msg = "Connection attempt timed out — the database may be unreachable or starting up."
        if form_data.get("wallet_password"):
            msg += " If using a wallet, verify the wallet password is correct."
        msg += " Please try again."
        st.error(msg)
    except httpx.HTTPStatusError as exc:
        st.error(f"Error: {helpers.extract_error_detail(exc)}")


def _remove_database(selected: str) -> None:
    """Remove a database configuration via the API."""
    try:
        with st.spinner("Removing database configuration..."):
            api_delete(f"databases/{selected}")
        helpers.refresh_settings()
    except httpx.HTTPStatusError as exc:
        st.error(f"Remove failed: {helpers.extract_error_detail(exc)}")


#####################################################
# Render Helpers
#####################################################
def _render_databases(database_lookup: dict, database_aliases: list, current_alias: str | None) -> tuple[str, bool]:
    """Render the database configuration form and return (selected_alias, is_new)."""
    st.subheader("Configuration", divider="red")

    # Selector: existing aliases + "Add New..."
    options = database_aliases + [ADD_NEW]

    # Apply pending selection (set before rerun, applied before widget instantiation)
    pending = state.pop("_pending_db_select", None)
    if pending and pending in options:
        state["runtime_database_selector"] = pending

    selected: str = (
        st.selectbox(
            "Database:",
            options=options,
            index=helpers.selectbox_index(options, current_alias),
            key="runtime_database_selector",
            on_change=_on_database_change,
            help="The database used for Vector Search and NL2SQL",
        )
        or ""
    )

    is_new = selected == ADD_NEW

    # Fetch full config (with secrets) for editing existing entries
    if not is_new:  # noqa: SIM108
        db_config = _fetch_database(selected) or database_lookup.get(selected, {})
    else:
        db_config = {}

    # CORE database is locked when connected (persistence database)
    is_core = not is_new and (selected or "").upper() == "CORE"
    fields_disabled = is_core and db_config.get("usable", False)

    # Use selected alias in widget keys so fields reset when selection changes
    key_suffix = selected or "new"

    # When adding a new database and CORE doesn't exist, force alias to CORE
    core_exists = any(a.upper() == "CORE" for a in database_aliases)
    force_core = is_new and not core_exists

    # Configuration Form
    with st.container(border=True):
        if fields_disabled:
            st.info("CORE is the persistence database and cannot be modified while connected.", icon="ℹ️")
        if force_core:
            st.info("The first database must be configured as CORE.", icon="ℹ️")
        alias = st.text_input(
            "Alias:",
            value="CORE" if force_core else ("" if is_new else db_config.get("alias", "")),
            disabled=force_core or not is_new,
            key=f"form_db_alias_{key_suffix}",
        )
        form_data = {
            "username": st.text_input(
                "Username:",
                value=db_config.get("username", "") or "",
                disabled=fields_disabled,
                key=f"form_db_username_{key_suffix}",
            )
            or None,
            "password": st.text_input(
                "Password:",
                value=db_config.get("password", "") or "",
                type="password",
                disabled=fields_disabled,
                key=f"form_db_password_{key_suffix}",
            )
            or None,
            "dsn": st.text_input(
                "DSN (Connect String):",
                value=db_config.get("dsn", "") or "",
                disabled=fields_disabled,
                key=f"form_db_dsn_{key_suffix}",
            )
            or None,
            "wallet_password": st.text_input(
                "Wallet Password:",
                value=db_config.get("wallet_password", "") or "",
                type="password",
                disabled=fields_disabled,
                key=f"form_db_wallet_password_{key_suffix}",
            )
            or None,
        }

        # Connection status
        if not is_new:
            if db_config.get("usable"):
                st.success("Status: Connected")
            else:
                st.error("Status: Disconnected")

        # Action buttons
        save_button, remove_button, _ = st.columns([2, 3, 5])
        save_button.button(
            "Create" if is_new else "Save",
            disabled=fields_disabled,
            type="primary",
            width="stretch",
            on_click=_handle_form_submit,
            kwargs={
                "selected": selected,
                "is_new": is_new,
                "alias": alias,
                "form_data": form_data,
                "db_config": db_config,
            },
        )
        with remove_button:
            if not is_new and not is_core:
                with st.popover("⚠️ Remove Database", disabled=is_core):
                    st.warning(f"Are you sure you want to remove **{selected}**?")
                    if st.button("Confirm Remove", key="confirm_delete_db", type="primary"):
                        _remove_database(selected)

    return selected, is_new


def _render_vector_stores(database_lookup: dict, selected: str) -> None:
    """Render the vector stores table for the selected database."""
    vector_stores = database_lookup[selected].get("vector_stores") or []
    if vector_stores:
        st.subheader("Vector Storage", divider="red")
        st.write("Existing Vector Storage Tables in Database.")
        with st.container(border=True):
            col_widths = [2, 5, 10, 3, 3, 5, 3]
            headers = ["\u200b", "Alias", "Model", "Chunk", "Overlap", "Dist. Strategy", "Index"]

            for col, header in zip(st.columns(col_widths), headers):
                col.markdown(f"**<u>{header}</u>**", unsafe_allow_html=True)

            for vs in vector_stores:
                table_name = vs.get("vector_store", "")
                row_key = table_name.lower()
                cols = st.columns(col_widths)

                cols[0].button(
                    "",
                    icon="🗑️",
                    key=f"runtime_vs_drop_{row_key}",
                    on_click=_drop_vector_store,
                    args=[selected, table_name],
                    help="Drop Vector Storage Table",
                )

                embedding_model = vs.get("embedding_model")

                field_values = [
                    ("alias", vs.get("alias", "")),
                    (
                        "model",
                        f"{embedding_model['provider']}/{embedding_model['id']}"
                        if isinstance(embedding_model, dict) and embedding_model
                        else str(embedding_model or ""),
                    ),
                    ("chunk_size", str(vs.get("chunk_size", ""))),
                    ("chunk_overlap", str(vs.get("chunk_overlap", ""))),
                    ("distance_strategy", str(vs.get("distance_strategy", ""))),
                    ("index_type", vs.get("index_type", "")),
                ]
                for col, (field, value) in zip(cols[1:], field_values):
                    col.text_input(
                        field,
                        value=value,
                        label_visibility="collapsed",
                        key=f"runtime_vs_{row_key}_{field}",
                        disabled=True,
                    )
    else:
        st.write("No Vector Stores Found")


#####################################################
# MAIN
#####################################################
def display_databases() -> None:
    """Streamlit GUI"""

    database_lookup = helpers.state_configs_lookup("database_configs", "alias")
    database_aliases = list(database_lookup.keys())
    current_alias = state["settings"]["client_settings"].get("database", {}).get("alias")

    selected, is_new = _render_databases(database_lookup, database_aliases, current_alias)

    # Auto-sync: if a real DB is shown but not yet active in client_settings, set it now.
    # This handles the case where the server restarted and in-memory client_settings was reset.
    if not is_new and selected and selected != current_alias:
        helpers.sync_client_setting("database", "alias", selected)

    if not is_new:
        _render_vector_stores(database_lookup, selected)

    # Refresh on completion so a newly-created vector store appears
    # in the table above without a manual page refresh.
    render_active_embed_jobs(refresh_on_idle=True)
