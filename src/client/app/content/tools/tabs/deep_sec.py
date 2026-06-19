"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tools tab for managing Oracle Deep Data Security: data roles, end users, and data
grants (column masking and row-level filtering) on the selected database.
"""
# spell-checker:ignore deepsec selectbox

import logging
from urllib.parse import quote

import httpx
import streamlit as st
from streamlit import session_state as state

from client.app.core import helpers
from client.app.core.api import api_delete, api_get, api_post
from client.app.core.auth import is_authenticated, locked_notice

LOGGER = logging.getLogger("client.content.tools.tabs.deep_sec")

_PRIVILEGES = ["SELECT", "INSERT", "UPDATE", "DELETE"]
_COL_MODE_ALL = "All columns"
_COL_MODE_ONLY = "Specific columns"
_COL_MODE_EXCEPT = "All columns except"


def _client_header() -> dict:
    return {"client": state.optimizer_client}


def _error(prefix: str, exc: httpx.HTTPStatusError) -> None:
    st.error(f"{prefix}: {helpers.extract_error_detail(exc)}")


def _render_delete(names: list[str], enabled: bool, endpoint: str, label: str, toast: str, key: str) -> None:
    """Render a selectbox + Drop button for removing a named Deep Data Security object."""
    if not (names and enabled):
        return
    cols = st.columns([3, 1])
    target = cols[0].selectbox(label, names, key=f"{key}_sel")
    if cols[1].button("Drop", key=f"{key}_btn"):
        try:
            api_delete(f"{endpoint}/{quote(target, safe='')}", extra_headers=_client_header(), toast=toast)
            st.rerun()
        except httpx.HTTPStatusError as exc:
            _error("Drop failed", exc)


# ---------------------------------------------------------------------------
# Data roles
# ---------------------------------------------------------------------------


def _render_data_roles(caps: dict, authenticated: bool):
    """Render the data-roles section.

    Returns the fetched roles for reuse by the grant builder, or ``None`` when
    listing is unavailable (the user lacks SELECT on DBA_DATA_ROLES) so callers
    can fall back rather than treat it as "no roles".
    """
    st.subheader("Data Roles")
    roles = None
    if caps.get("list_data_roles"):
        try:
            roles = api_get("deepsec/data-roles", extra_headers=_client_header())
        except httpx.HTTPStatusError as exc:
            _error("Unable to list data roles", exc)
            roles = []
        if roles:
            st.dataframe(roles, hide_index=True, use_container_width=True)
        else:
            st.caption("No data roles defined.")
    else:
        st.info("Listing data roles requires the database user to have SELECT on DBA_DATA_ROLES.")

    with st.form("ds_create_role", clear_on_submit=True):
        name = st.text_input("Data role name")
        mapped_to = st.text_input("Mapped to (optional external application role)")
        can_create = authenticated and caps.get("create_data_role")
        if st.form_submit_button("Create data role", disabled=not can_create) and name:
            try:
                api_post(
                    "deepsec/data-roles",
                    json={"name": name, "mapped_to": mapped_to or None},
                    extra_headers=_client_header(),
                    toast="Data role created.",
                )
                st.rerun()
            except httpx.HTTPStatusError as exc:
                _error("Create failed", exc)

    if roles:
        _render_delete(
            [r["name"] for r in roles],
            bool(authenticated and caps.get("drop_data_role")),
            "deepsec/data-roles",
            "Drop data role",
            "Data role dropped.",
            "ds_role",
        )
    return roles


# ---------------------------------------------------------------------------
# End users
# ---------------------------------------------------------------------------


def _render_end_users(caps: dict, authenticated: bool) -> None:
    st.subheader("End Users")
    users = None
    if caps.get("list_end_users"):
        try:
            users = api_get("deepsec/end-users", extra_headers=_client_header())
        except httpx.HTTPStatusError as exc:
            _error("Unable to list end users", exc)
            users = []
        if users:
            st.dataframe(users, hide_index=True, use_container_width=True)
        else:
            st.caption("No end users defined.")
    else:
        st.info("Listing end users requires the database user to have SELECT on DBA_END_USERS.")

    with st.form("ds_create_user", clear_on_submit=True):
        name = st.text_input("End user name")
        password = st.text_input("Password", type="password")
        can_create = authenticated and caps.get("create_end_user")
        if st.form_submit_button("Create end user", disabled=not can_create) and name and password:
            try:
                api_post(
                    "deepsec/end-users",
                    json={"name": name, "password": password},
                    extra_headers=_client_header(),
                    toast="End user created.",
                )
                st.rerun()
            except httpx.HTTPStatusError as exc:
                _error("Create failed", exc)

    if users:
        _render_delete(
            [u["name"] for u in users],
            bool(authenticated and caps.get("drop_end_user")),
            "deepsec/end-users",
            "Drop end user",
            "End user dropped.",
            "ds_user",
        )


# ---------------------------------------------------------------------------
# Data grants
# ---------------------------------------------------------------------------


def _grant_preview(name, privileges, obj, columns, mode, predicate, grantee) -> str:
    """Build a human-readable preview of the data grant DDL (server is authoritative)."""
    if not (name and privileges and obj and grantee):
        return "-- complete the fields to preview the statement"
    if mode == _COL_MODE_EXCEPT and columns:
        col_clause = f" (ALL COLUMNS EXCEPT {', '.join(columns)})"
    elif mode == _COL_MODE_ONLY and columns:
        col_clause = f" ({', '.join(columns)})"
    else:
        col_clause = ""
    priv_parts = [p if p == "DELETE" else f"{p}{col_clause}" for p in privileges]
    sql = f"CREATE DATA GRANT {name} AS {', '.join(priv_parts)} ON {obj}"
    if predicate:
        sql += f"\n  WHERE {predicate}"
    sql += f"\n  TO {grantee};"
    return sql


def _fetch_columns(obj: str | None) -> list[str]:
    if not obj:
        return []
    try:
        return api_get(f"deepsec/objects/{quote(obj, safe='')}/columns", extra_headers=_client_header())
    except httpx.HTTPStatusError as exc:
        _error("Unable to list columns", exc)
        return []


def _submit_grant(name, privileges, obj, selected_cols, mode, predicate, grantee) -> None:
    if not (name and privileges and obj and grantee):
        st.warning("Name, at least one privilege, an object, and a grantee are required.")
        return
    payload = {
        "name": name,
        "privileges": privileges,
        "object_name": obj,
        "grantee": grantee,
        "columns": selected_cols or None,
        "all_columns_except": mode == _COL_MODE_EXCEPT,
        "predicate": predicate or None,
    }
    try:
        api_post(
            "deepsec/data-grants",
            json=payload,
            extra_headers=_client_header(),
            toast="Data grant created.",
        )
        st.rerun()
    except httpx.HTTPStatusError as exc:
        _error("Create failed", exc)


def _render_grantee_input(roles) -> str | None:
    """Pick the grantee data role.

    *roles* is a list when listing is available, [] when none exist, or None when
    the user cannot list roles — in which case fall back to free-text entry so a
    known role name can still be used.
    """
    if roles is None:
        return st.text_input("Grant to data role (name)", key="ds_grant_grantee_txt") or None
    role_names = [r["name"] for r in roles]
    if not role_names:
        st.info("Create a data role first to grant to.")
        return None
    return st.selectbox("Grant to data role", role_names, key="ds_grant_grantee")


def _render_grant_builder(objects: list, roles, can_manage: bool) -> None:
    obj_names = [o["name"] for o in objects]
    if not obj_names:
        st.info("No tables or views found in the schema to grant on.")
        return

    name = st.text_input("Data grant name", key="ds_grant_name")
    obj = st.selectbox("Object (table/view)", obj_names, key="ds_grant_obj")
    columns = _fetch_columns(obj)
    privileges = st.multiselect("Privileges", _PRIVILEGES, default=["SELECT"], key="ds_grant_privs")
    mode = st.radio(
        "Columns", [_COL_MODE_ALL, _COL_MODE_ONLY, _COL_MODE_EXCEPT], horizontal=True, key="ds_grant_mode"
    )
    selected_cols = st.multiselect("Columns", columns, key="ds_grant_cols") if mode != _COL_MODE_ALL else []
    predicate = st.text_area("Row predicate (optional SQL WHERE for row-level filtering)", key="ds_grant_pred")
    grantee = _render_grantee_input(roles)

    st.code(_grant_preview(name, privileges, obj, selected_cols, mode, predicate, grantee), language="sql")
    if st.button("Create data grant", disabled=not can_manage, key="ds_grant_create"):
        _submit_grant(name, privileges, obj, selected_cols, mode, predicate, grantee)


def _render_data_grants(caps: dict, authenticated: bool, roles) -> None:
    st.subheader("Data Grants")
    try:
        grants = api_get("deepsec/data-grants", extra_headers=_client_header())
    except httpx.HTTPStatusError as exc:
        _error("Unable to list data grants", exc)
        grants = []

    if grants:
        st.dataframe(grants, hide_index=True, use_container_width=True)
    else:
        st.caption("No data grants defined.")

    can_manage = bool(authenticated and caps.get("manage_data_grants"))
    if not can_manage:
        st.caption("Creating data grants requires CREATE DATA GRANT and ADMINISTER ANY DATA GRANT.")

    try:
        objects = api_get("deepsec/objects", extra_headers=_client_header())
    except httpx.HTTPStatusError as exc:
        _error("Unable to load grant builder data", exc)
        return

    _render_grant_builder(objects, roles, can_manage)
    _render_delete(
        sorted({g["name"] for g in grants}),
        can_manage,
        "deepsec/data-grants",
        "Drop data grant",
        "Data grant dropped.",
        "ds_grant",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def display_deep_sec() -> None:
    """Streamlit GUI."""
    st.header("Deep Data Security")
    st.write(
        "Manage Oracle Deep Data Security on the selected database — data roles, end users, "
        "and data grants for column and row-level access control."
    )

    try:
        status = api_get("deepsec/status", extra_headers=_client_header())
    except httpx.HTTPStatusError as exc:
        _error("Deep Data Security is unavailable", exc)
        return

    if not status.get("available"):
        st.warning(
            "Deep Data Security is not available on the selected database. "
            "It requires Oracle AI Database 26ai."
        )
        if status.get("version"):
            st.caption(f"Database version: {status['version']}")
        return

    authenticated = is_authenticated()
    if not authenticated:
        locked_notice()

    missing = status.get("missing_privileges") or []
    if missing:
        st.info("The database user is missing privileges; related actions are disabled: " + ", ".join(missing))

    caps = status.get("capabilities", {})
    tab_roles, tab_users, tab_grants = st.tabs(["Data Roles", "End Users", "Data Grants"])
    with tab_roles:
        roles = _render_data_roles(caps, authenticated)
    with tab_users:
        _render_end_users(caps, authenticated)
    with tab_grants:
        _render_data_grants(caps, authenticated, roles)
