"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tools tab for managing Oracle Deep Data Security: data roles, end users, and data
grants (column masking and row-level filtering) on the selected database.
"""
# spell-checker:ignore deepsec selectbox

import logging
from collections.abc import Callable
from urllib.parse import quote

import httpx
import streamlit as st
from streamlit import session_state as state

from client.app.core import helpers
from client.app.core.api import api_delete, api_get, api_post
from client.app.core.auth import is_authenticated, locked_notice

LOGGER = logging.getLogger("client.content.tools.tabs.deepsec")

_PRIVILEGES = ["SELECT", "INSERT", "UPDATE", "DELETE"]
_COL_MODE_ALL = "All columns"
_COL_MODE_ONLY = "Specific columns"
_COL_MODE_EXCEPT = "All columns except"


def _client_header() -> dict:
    return {"client": state.optimizer_client}


def _error(prefix: str, exc: httpx.HTTPStatusError) -> None:
    st.error(f"{prefix}: {helpers.extract_error_detail(exc)}")


def _db_alias():
    """Alias of the currently selected database."""
    return state["settings"]["client_settings"].get("database", {}).get("alias")


def _db_username() -> str:
    """Username of the connected database, for use in GRANT hints."""
    db_config = helpers.state_configs_lookup("database_configs", "alias").get(_db_alias(), {})
    return db_config.get("username") or "<username>"


def _grant_hint(action: str, grant: str) -> str:
    """A consistent "<action> requires: `GRANT <grant> to <user>;`" privilege hint."""
    return f"{action} requires: `GRANT {grant} to {_db_username()};`"


def _render_table_header(col_widths: list[int], field_specs: list[tuple], *, leading: bool) -> None:
    """Render the underlined header row shared by the data-role/end-user/grant tables."""
    cols = st.columns(col_widths, vertical_alignment="center")
    if leading:
        cols[0].markdown("&#x200B;", unsafe_allow_html=True)
    field_cols = cols[1:] if leading else cols
    for col, (_, header) in zip(field_cols, field_specs):
        col.markdown(f"**<u>{header}</u>**", unsafe_allow_html=True)


def _render_row_fields(cols, field_specs: list[tuple], values: list, key_prefix: str, row_key: str) -> None:
    """Render a row of read-only field cells (shared by all three tables)."""
    for col, (field, _), value in zip(cols, field_specs, values):
        col.text_input(
            field,
            value=value,
            label_visibility="collapsed",
            key=f"{key_prefix}_{row_key}_{field}",
            disabled=True,
        )


#####################################################
# CRUD helpers (return True on success; dialogs rerun on success)
#####################################################
def _create_data_role(name: str, mapped_to: str) -> bool:
    try:
        api_post(
            "deepsec/data-roles",
            json={"name": name, "mapped_to": (mapped_to or "").strip() or None},
            extra_headers=_client_header(),
            toast="Data role created.",
        )
        return True
    except httpx.HTTPStatusError as exc:
        _error("Create failed", exc)
        return False


def _delete_data_role(name: str) -> bool:
    try:
        api_delete(
            f"deepsec/data-roles/{quote(name, safe='')}",
            extra_headers=_client_header(),
            toast="Data role dropped.",
        )
        return True
    except httpx.HTTPStatusError as exc:
        _error("Drop failed", exc)
        return False


def _create_end_user(name: str, schema: str = "") -> bool:
    try:
        api_post(
            "deepsec/end-users",
            json={"name": name, "schema_name": (schema or "").strip() or None},
            extra_headers=_client_header(),
            toast="End user created.",
        )
        return True
    except httpx.HTTPStatusError as exc:
        _error("Create failed", exc)
        return False


def _delete_end_user(name: str) -> bool:
    try:
        api_delete(
            f"deepsec/end-users/{quote(name, safe='')}",
            extra_headers=_client_header(),
            toast="End user dropped.",
        )
        return True
    except httpx.HTTPStatusError as exc:
        _error("Drop failed", exc)
        return False


def _grant_roles(grantee: str, roles: list[str]) -> bool:
    try:
        api_post(
            "deepsec/data-role-grants",
            json={"grantee": grantee, "roles": roles},
            extra_headers=_client_header(),
            toast="Data roles granted.",
        )
        return True
    except httpx.HTTPStatusError as exc:
        _error("Grant failed", exc)
        return False


def _revoke_role(grantee: str, role: str) -> bool:
    try:
        api_delete(
            f"deepsec/data-role-grants/{quote(grantee, safe='')}/{quote(role, safe='')}",
            extra_headers=_client_header(),
            toast="Data role revoked.",
        )
        return True
    except httpx.HTTPStatusError as exc:
        _error("Revoke failed", exc)
        return False


def _delete_data_grant(name: str) -> bool:
    try:
        api_delete(
            f"deepsec/data-grants/{quote(name, safe='')}",
            extra_headers=_client_header(),
            toast="Data grant dropped.",
        )
        return True
    except httpx.HTTPStatusError as exc:
        _error("Drop failed", exc)
        return False


def _set_connect_as(end_user: str) -> bool:
    """Register a managed connect-as connection for *end_user* and record the selection.

    The selection is stored in-memory client settings only (deep_data_security is
    runtime/session-scoped — never persisted/exported).
    """
    try:
        resp = api_post(
            "deepsec/connect-as",
            json={"end_user": end_user},
            extra_headers=_client_header(),
            toast=f"Chat tools will connect as {end_user}.",
            # Registering the managed connection also rebuilds SQLcl's connection store.
            # That setup can exceed the normal UI request timeout on a local database.
            timeout=60,
        )
    except httpx.HTTPStatusError as exc:
        _error("Connect-as failed", exc)
        # A failed re-designation may have torn down a previously-configured (stale) connection
        # and cleared its setting server-side; re-sync so the sidebar doesn't keep showing a
        # connect-as user whose connection no longer exists.
        helpers.refresh_settings(clear_runtime=False)
        return False
    # Preserve the prior enabled flag. A stale re-designation tears down the old managed
    # connection server-side (resetting enabled→False) before re-registering, so a field-merge
    # that omitted enabled would silently disable an already-active override. The sidebar toggle
    # remains the sole control that *changes* enabled — here we only carry it through unchanged.
    enabled = state["settings"]["client_settings"].get("deep_data_security", {}).get("enabled", False)
    helpers.update_client_settings(
        {
            "deep_data_security": {
                "enabled": enabled,
                "end_user": end_user,
                "alias": resp.get("alias"),
                "base_alias": resp.get("base_alias"),
            }
        }
    )
    return True


def _clear_connect_as() -> None:
    """Tear down the managed connect-as connection and clear the in-memory selection."""
    try:
        api_delete("deepsec/connect-as", extra_headers=_client_header(), toast="Connect-as cleared.")
    except httpx.HTTPStatusError as exc:
        _error("Clear failed", exc)
        return
    helpers.update_client_settings(
        {"deep_data_security": {"enabled": False, "end_user": None, "alias": None, "base_alias": None}}
    )


#####################################################
# Shared fetch helpers
#####################################################
def _fetch_data_roles(caps: dict):
    """Fetch data roles, ``[]`` on error, or ``None`` when listing is unavailable."""
    if not caps.get("list_data_roles"):
        return None
    try:
        return api_get("deepsec/data-roles", extra_headers=_client_header())
    except httpx.HTTPStatusError as exc:
        _error("Unable to list data roles", exc)
        return []


def _fetch_end_users(caps: dict):
    """Fetch end users, ``[]`` on error, or ``None`` when listing is unavailable."""
    if not caps.get("list_end_users"):
        return None
    try:
        return api_get("deepsec/end-users", extra_headers=_client_header())
    except httpx.HTTPStatusError as exc:
        _error("Unable to list end users", exc)
        return []


def _fetch_role_grants(caps: dict):
    """Fetch data-role-to-end-user grants, ``[]`` on error/unavailable."""
    if not caps.get("list_data_role_grants"):
        return []
    try:
        return api_get("deepsec/data-role-grants", extra_headers=_client_header())
    except httpx.HTTPStatusError as exc:
        _error("Unable to list data role assignments", exc)
        return []


def _local_role_names(caps: dict) -> list[str]:
    """Names of locally-managed data roles (externally-mapped roles can't be granted to end users)."""
    roles = _fetch_data_roles(caps) or []
    return [r["name"] for r in roles if not r.get("mapped_to")]


def _apply_grant_diff(grantee_for: str, current: set, selected: set, *, by_user: bool) -> bool:
    """Grant/revoke to reconcile *current* with *selected*.

    ``by_user=True``  → *grantee_for* is an end user, the sets are role names.
    ``by_user=False`` → *grantee_for* is a data role, the sets are end-user names.
    """
    ok = True
    added = sorted(selected - current)
    removed = sorted(current - selected)
    if by_user:
        if added:
            ok = _grant_roles(grantee_for, added) and ok
        for role in removed:
            ok = _revoke_role(grantee_for, role) and ok
    else:
        for user in added:
            ok = _grant_roles(user, [grantee_for]) and ok
        for user in removed:
            ok = _revoke_role(user, grantee_for) and ok
    return ok


#####################################################
# Dialog helpers
#####################################################
def _entity_dialog_actions(
    *,
    is_add: bool,
    name: str,
    name_error: str,
    sel: list | None,
    current: set,
    by_user: bool,
    perms: dict,
    create_fn: Callable[[], bool],
    delete_fn: Callable[[], bool],
) -> bool:
    """Render the Create/Save/Delete/Cancel row shared by both entity dialogs; return True on success.

    *perms* carries the ``create``/``assign``/``delete`` enable flags. *create_fn*/*delete_fn* perform the
    create/delete and return True on success; on Create/Save the role assignments are reconciled from
    *current* to *sel*. Cancel reruns the dialog directly.
    """
    action_button, delete_button, cancel_button = st.columns([2, 6, 2])
    if is_add and action_button.button("Create", type="primary", width="stretch", disabled=not perms["create"]):
        if not name:
            st.error(name_error)
            return False
        return create_fn() and (not sel or _apply_grant_diff(name, set(), set(sel), by_user=by_user))
    if not is_add:
        if sel is not None and action_button.button(
            "Save", type="primary", width="stretch", disabled=not perms["assign"]
        ):
            return _apply_grant_diff(name, current, set(sel), by_user=by_user)
        if delete_button.button("Delete", type="secondary", disabled=not perms["delete"]):
            return delete_fn()
    if cancel_button.button("Cancel", width="stretch"):
        st.rerun()
    return False


#####################################################
# Data role dialog
#####################################################
@st.dialog("Data Role")
def _data_role_dialog(caps: dict, authenticated: bool, action: str, name: str = "", mapped_to: str = "") -> None:
    """Create or edit a data role; assign it to end users (local roles only)."""
    is_add = action == "add"
    if is_add:
        name = st.text_input("Data role name", key="ds_role_dlg_name")
        mapped_to = st.text_input("Mapped to (optional external application role)", key="ds_role_dlg_mapped")
    else:
        st.text_input("Data role name", value=name, disabled=True, key="ds_role_dlg_name")
        st.text_input("Mapped to", value=mapped_to or "", disabled=True, key="ds_role_dlg_mapped")

    is_local = not (mapped_to or "").strip()
    sel_users = None
    current_users: set = set()  # end users currently granted this role (fetched once, reused on Save)
    if caps.get("grant_data_roles") and is_local:
        users = _fetch_end_users(caps) or []
        user_names = [u["name"] for u in users]
        if user_names:
            current_users = {g["grantee"] for g in _fetch_role_grants(caps) if g.get("data_role") == name}
            default = [u for u in user_names if u in current_users]
            sel_users = st.multiselect(
                "Assigned end users", user_names, default=default, disabled=not authenticated, key="ds_role_dlg_users"
            )
        elif is_add:
            st.caption("No end users to assign yet.")
    elif not is_local:
        st.caption("Externally-mapped roles are enabled via IAM and cannot be assigned to end users.")
    elif not caps.get("grant_data_roles"):
        st.info(_grant_hint("Assigning end users to data groups", "ANY DATA ROLE"))

    if _entity_dialog_actions(
        is_add=is_add,
        name=name,
        name_error="Data role name is required.",
        sel=sel_users,
        current=current_users,
        by_user=False,
        perms={
            "create": bool(authenticated and caps.get("create_data_role")),
            "assign": bool(authenticated and caps.get("grant_data_roles")),
            "delete": bool(authenticated and caps.get("drop_data_role")),
        },
        create_fn=lambda: _create_data_role(name, mapped_to),
        delete_fn=lambda: _delete_data_role(name),
    ):
        st.rerun()


#####################################################
# End user dialog
#####################################################
@st.dialog("End User")
def _end_user_dialog(caps: dict, authenticated: bool, action: str, name: str = "", schema: str = "") -> None:
    """Create or edit an end user; assign locally-managed data roles."""
    is_add = action == "add"
    if is_add:
        name = st.text_input("End user name", key="ds_user_dlg_name")
        # Default the name-resolution schema to the connected database user's schema.
        schema = st.text_input(
            "Schema (for name resolution)",
            value=_db_username(),
            help="Existing schema that unqualified object names resolve against. Defaults to the connected user.",
            key="ds_user_dlg_schema",
        )
        st.caption("The end user is created with the same password as the connected database user.")
    else:
        st.text_input("End user name", value=name, disabled=True, key="ds_user_dlg_name")
        st.text_input("Schema (for name resolution)", value=schema or "", disabled=True, key="ds_user_dlg_schema")

    sel_roles = None
    # Locally-managed roles currently granted to this user (fetched once, reused on Save). Filtered to
    # local roles so externally-mapped grants are never reconciled away.
    current_roles: set = set()
    if caps.get("grant_data_roles"):
        local_roles = _local_role_names(caps)
        if local_roles:
            local_set = set(local_roles)
            current_roles = {
                g["data_role"]
                for g in _fetch_role_grants(caps)
                if g.get("grantee") == name and g.get("data_role") in local_set
            }
            default = [r for r in local_roles if r in current_roles]
            sel_roles = st.multiselect(
                "Assigned data roles",
                local_roles,
                default=default,
                disabled=not authenticated,
                key="ds_user_dlg_roles",
            )
        elif is_add:
            st.caption("No locally-managed data roles to assign yet.")
    else:
        st.info(_grant_hint("Assigning data roles", "ANY DATA ROLE"))

    if _entity_dialog_actions(
        is_add=is_add,
        name=name,
        name_error="End user name is required.",
        sel=sel_roles,
        current=current_roles,
        by_user=True,
        perms={
            "create": bool(authenticated and caps.get("create_end_user")),
            "assign": bool(authenticated and caps.get("grant_data_roles")),
            "delete": bool(authenticated and caps.get("drop_end_user")),
        },
        create_fn=lambda: _create_end_user(name, schema),
        delete_fn=lambda: _delete_end_user(name),
    ):
        st.rerun()


#####################################################
# Data roles
#####################################################
def _render_data_roles(caps: dict, authenticated: bool):
    """Render the data-roles section.

    Returns the fetched roles for reuse by the grant builder, or ``None`` when
    listing is unavailable (the user lacks SELECT on DBA_DATA_ROLES) so callers
    can fall back rather than treat it as "no roles".
    """
    st.header("Data Roles", divider="red")
    st.write(
        "A role in the database used for fine-grained access to data. "
        "You can grant data privileges (through data grants) and standard database roles to a data role."
    )
    roles = _fetch_data_roles(caps)
    st.subheader("Existing Data Roles")
    if roles is None:
        st.info(_grant_hint("Listing data roles", "SELECT on DBA_DATA_ROLES"))
    elif roles:
        field_specs = [("name", "Name"), ("mapped_to", "Mapped To"), ("enabled_by_default", "Enabled by Default")]
        col_widths = [2, 8, 8, 5]
        with st.container(border=True):
            _render_table_header(col_widths, field_specs, leading=True)
            for role in roles:
                name = role.get("name", "")
                row_key = name.lower()
                cols = st.columns(col_widths, vertical_alignment="center")
                cols[0].button(
                    "Edit",
                    key=f"ds_role_edit_{row_key}",
                    on_click=_data_role_dialog,
                    kwargs={
                        "caps": caps,
                        "authenticated": authenticated,
                        "action": "edit",
                        "name": name,
                        "mapped_to": role.get("mapped_to") or "",
                    },
                )
                field_values = [name, role.get("mapped_to") or "", "Yes" if role.get("enabled_by_default") else "No"]
                _render_row_fields(cols[1:], field_specs, field_values, "ds_role", row_key)
    else:
        st.info("No data roles defined.")

    if caps.get("create_data_role"):
        if st.button("Create Data Role", type="primary", key="ds_role_create_btn", disabled=not authenticated):
            _data_role_dialog(caps=caps, authenticated=authenticated, action="add")
    else:
        st.info(_grant_hint("Creating data roles", "CREATE DATA ROLE"))

    return roles


#####################################################
# End users
#####################################################
def _render_end_users(caps: dict, authenticated: bool) -> None:
    """Render the end-users section."""
    st.header("End Users", divider="red")
    st.write(
        "A database identity that connects through an application. "
        "Data roles are granted to end users to give them fine-grained access to data."
    )
    users = _fetch_end_users(caps)
    st.subheader("Existing End Users")
    if users is None:
        st.info(_grant_hint("Listing end users", "SELECT on DBA_END_USERS"))
    elif users:
        field_specs = [
            ("name", "Name"),
            ("account_status", "Account Status"),
            ("created", "Created"),
        ]
        col_widths = [2, 8, 6, 6]
        with st.container(border=True):
            _render_table_header(col_widths, field_specs, leading=True)
            for user in users:
                name = user.get("name", "")
                row_key = name.lower()
                cols = st.columns(col_widths, vertical_alignment="center")
                cols[0].button(
                    "Edit",
                    key=f"ds_user_edit_{row_key}",
                    on_click=_end_user_dialog,
                    kwargs={
                        "caps": caps,
                        "authenticated": authenticated,
                        "action": "edit",
                        "name": name,
                        "schema": user.get("schema_name") or "",
                    },
                )
                field_values = [
                    name,
                    user.get("account_status") or "",
                    user.get("created") or "",
                ]
                _render_row_fields(cols[1:], field_specs, field_values, "ds_user", row_key)
    else:
        st.info("No end users defined.")

    if caps.get("create_end_user"):
        if st.button("Create End User", type="primary", key="ds_user_create_btn", disabled=not authenticated):
            _end_user_dialog(caps=caps, authenticated=authenticated, action="add")
    else:
        st.info(_grant_hint("Creating end users", "CREATE END USER"))

    if users:
        _render_connect_as(users, authenticated)


_CONNECT_AS_NONE = "— none —"


def _on_connect_as_change() -> None:
    """Apply the 'Connect tools as' selection (set or clear the managed connection)."""
    selection = state.get("ds_connect_as")
    if not selection or selection == _CONNECT_AS_NONE:
        _clear_connect_as()
    else:
        _set_connect_as(selection)


def _render_connect_as(users: list, authenticated: bool) -> None:
    """Choose which end user Vector Search / NL2SQL connect as (Deep Data Security override)."""
    st.caption("Select an end user for **Vector Search** and **NL2SQL** to connect as.")
    db_alias = _db_alias()
    dds = state["settings"]["client_settings"].get("deep_data_security", {})
    # Only reflect the current selection when it belongs to the active database.
    current = dds.get("end_user") if dds.get("base_alias") == db_alias else None
    options = [_CONNECT_AS_NONE] + [u.get("name", "") for u in users]

    # With exactly one end user and no selection yet for this database, connect as that sole user
    # automatically — *establishing* the managed connection, not merely showing it selected.
    # Streamlit never fires on_change for a default index, so without an explicit call here the UI
    # would claim the tools connect as the end user while they kept using the base database user.
    # The per-database sentinel runs this once: after the user clears the selection back to
    # "— none —" we must not immediately re-establish it on the next rerun.
    if current is None and authenticated and len(users) == 1 and state.get("_ds_autodefault_alias") != db_alias:
        state["_ds_autodefault_alias"] = db_alias
        if _set_connect_as(options[1]):
            current = options[1]

    index = options.index(current) if current in options else 0
    st.selectbox(
        "Connect tools as",
        options,
        index=index,
        key="ds_connect_as",
        label_visibility="collapsed",
        on_change=_on_connect_as_change,
        disabled=not authenticated,
    )


#####################################################
# Data grants
#####################################################
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


def _submit_grant(name, privileges, obj, selected_cols, mode, predicate, grantee, *, or_replace: bool) -> bool:
    if not (name and privileges and obj and grantee):
        st.warning("Name, at least one privilege, an object, and a grantee are required.")
        return False
    payload = {
        "name": name,
        "privileges": privileges,
        "object_name": obj,
        "grantee": grantee,
        "columns": selected_cols or None,
        "all_columns_except": mode == _COL_MODE_EXCEPT,
        "predicate": predicate or None,
        "or_replace": or_replace,
    }
    try:
        api_post(
            "deepsec/data-grants",
            json=payload,
            extra_headers=_client_header(),
            toast="Data grant saved." if or_replace else "Data grant created.",
        )
        return True
    except httpx.HTTPStatusError as exc:
        _error("Save failed" if or_replace else "Create failed", exc)
        return False


def _render_grantee_input(roles, default: str = "", key_suffix: str = "") -> str | None:
    """Pick the grantee data role, defaulting to *default* when editing.

    *roles* is a list when listing is available, [] when none exist, or None when
    the user cannot list roles — in which case fall back to free-text entry so a
    known role name can still be used.
    """
    if roles is None:
        txt = st.text_input("Grant to data role (name)", value=default, key=f"ds_grant_grantee_txt_{key_suffix}")
        return txt or None
    role_names = [r["name"] for r in roles]
    # Keep the current grantee selectable on edit even if it isn't a locally-listed role.
    if default and default not in role_names:
        role_names = [default] + role_names
    if not role_names:
        st.info("Create a data role first to grant to.")
        return None
    index = role_names.index(default) if default in role_names else 0
    return st.selectbox("Grant to data role", role_names, index=index, key=f"ds_grant_grantee_{key_suffix}")


def _grant_column_mode(grant: dict) -> str:
    """Reconstruct the column radio mode from a grouped grant's columns/except flag."""
    if not grant.get("columns"):
        return _COL_MODE_ALL
    return _COL_MODE_EXCEPT if grant.get("all_columns_except") else _COL_MODE_ONLY


@st.dialog("Data Grant")
def _data_grant_dialog(caps: dict, authenticated: bool, action: str, roles, grant: dict | None = None) -> None:
    """Create or edit a data grant (column masking / row-level filtering) on a table or view.

    Editing re-issues the grant with CREATE OR REPLACE; the grant name is its identity
    and is read-only. *grant* is a grouped row from :func:`_group_grants` when editing.
    """
    is_add = action == "add"
    grant = grant or {}
    can_manage = bool(authenticated and caps.get("manage_data_grants"))
    # A grant whose columns differ per privilege can't be round-tripped through the single shared
    # column selection — saving would flatten it. Block Save in that case. Add builds a fresh grant
    # (always uniform); edit always receives a _group_grants row, which sets uniform_columns.
    uniform = is_add or grant["uniform_columns"]
    # Per-grant widget keys so editing one grant never inherits another's field state.
    key_suffix = "new" if is_add else (grant.get("name") or "").lower()

    try:
        objects = api_get("deepsec/objects", extra_headers=_client_header())
    except httpx.HTTPStatusError as exc:
        _error("Unable to load grant builder data", exc)
        return
    obj_names = [o["name"] for o in objects]
    if is_add and not obj_names:
        st.info("No tables or views found in the schema to grant on.")
        if st.button("Cancel", width="stretch"):
            st.rerun()
        return

    if is_add:
        name = st.text_input("Data grant name", key=f"ds_grant_name_{key_suffix}")
        obj = st.selectbox("Object (table/view)", obj_names, key=f"ds_grant_obj_{key_suffix}")
    else:
        # Name and target object are the grant's identity — read-only when editing.
        name = grant.get("name", "")
        obj = grant.get("object_name") or ""
        st.text_input("Data grant name", value=name, disabled=True, key=f"ds_grant_name_{key_suffix}")
        st.text_input(
            "Object (table/view)", value=grant.get("object") or obj, disabled=True, key=f"ds_grant_obj_{key_suffix}"
        )
    if not uniform:
        st.warning(
            "This grant applies different column restrictions per privilege, which this builder "
            "cannot edit without changing its meaning. Drop and recreate it, or edit it in SQL."
        )
    columns = _fetch_columns(obj)
    privileges = st.multiselect(
        "Privileges", _PRIVILEGES, default=grant.get("privileges") or ["SELECT"], key=f"ds_grant_privs_{key_suffix}"
    )
    col_modes = [_COL_MODE_ALL, _COL_MODE_ONLY, _COL_MODE_EXCEPT]
    mode = st.radio(
        "Columns",
        col_modes,
        index=col_modes.index(_grant_column_mode(grant)),
        horizontal=True,
        key=f"ds_grant_mode_{key_suffix}",
    )
    selected_cols = (
        st.multiselect(
            "Columns",
            columns,
            default=[c for c in (grant.get("columns") or []) if c in columns],
            key=f"ds_grant_cols_{key_suffix}",
        )
        if mode != _COL_MODE_ALL
        else []
    )
    predicate = st.text_area(
        "Row predicate (optional SQL WHERE for row-level filtering)",
        value=grant.get("predicate") or "",
        key=f"ds_grant_pred_{key_suffix}",
    )
    grantee = _render_grantee_input(roles, default=grant.get("grantee") or "", key_suffix=key_suffix)

    st.code(_grant_preview(name, privileges, obj, selected_cols, mode, predicate, grantee), language="sql")

    action_button, delete_button, cancel_button = st.columns([2, 6, 2])
    if is_add:
        if action_button.button(
            "Create", type="primary", width="stretch", disabled=not can_manage, key=f"ds_grant_create_{key_suffix}"
        ):
            if _submit_grant(name, privileges, obj, selected_cols, mode, predicate, grantee, or_replace=False):
                st.rerun()
    else:
        if action_button.button(
            "Save",
            type="primary",
            width="stretch",
            disabled=not can_manage or not uniform,
            key=f"ds_grant_save_{key_suffix}",
        ):
            if _submit_grant(name, privileges, obj, selected_cols, mode, predicate, grantee, or_replace=True):
                st.rerun()
        if delete_button.button(
            "Delete", type="secondary", disabled=not can_manage, key=f"ds_grant_delete_{key_suffix}"
        ):
            if _delete_data_grant(name):
                st.rerun()
    if cancel_button.button("Cancel", width="stretch"):
        st.rerun()


def _group_grants(grants: list) -> list[dict]:
    """Collapse the per-column/-privilege USER_DATA_GRANTS rows into one row per grant name.

    The builder applies a single column selection to every privilege, so it can only represent a
    grant whose non-DELETE privileges share one column spec. ``uniform_columns`` records whether
    that holds; the edit dialog blocks saving when it does not, to avoid flattening per-privilege
    column restrictions (e.g. ``SELECT(SALARY) + UPDATE(NAME)``) into both privileges on both
    columns.
    """
    grouped: dict[str, dict] = {}
    # name -> privilege -> [columns set, all_columns_except] — used only to detect non-uniform grants.
    priv_specs: dict[str, dict[str, list]] = {}
    for g in grants:
        name = g.get("name", "")
        entry = grouped.setdefault(
            name,
            {
                "name": name,
                "grantee": g.get("grantee") or "",
                "object": "",
                "object_name": "",
                "privileges": [],
                "columns": [],
                "all_columns_except": False,
                "predicate": "",
                "uniform_columns": True,
            },
        )
        owner, obj = g.get("object_owner"), g.get("object_name")
        if obj and not entry["object"]:
            entry["object"] = f"{owner}.{obj}" if owner else obj
            entry["object_name"] = obj
        priv = g.get("privilege")
        if priv and priv not in entry["privileges"]:
            entry["privileges"].append(priv)
        col = g.get("column_name")
        if col and col not in entry["columns"]:
            entry["columns"].append(col)
        if g.get("all_columns_except"):
            entry["all_columns_except"] = True
        if g.get("predicate") and not entry["predicate"]:
            entry["predicate"] = g["predicate"]
        if priv:
            spec = priv_specs.setdefault(name, {}).setdefault(priv, [set(), False])
            if col:
                spec[0].add(col)
            if g.get("all_columns_except"):
                spec[1] = True
    # Faithfully editable only when every non-DELETE privilege shares one (columns, except) spec.
    # DELETE is row-level and carries no columns, so it never counts as a differing spec.
    for name, entry in grouped.items():
        specs = {
            (frozenset(cols), is_except)
            for priv, (cols, is_except) in priv_specs.get(name, {}).items()
            if priv != "DELETE"
        }
        entry["uniform_columns"] = len(specs) <= 1
    return list(grouped.values())


def _render_data_grants(caps: dict, authenticated: bool, roles) -> None:
    """Render the data-grants section."""
    st.header("Data Grants", divider="red")
    st.write(
        "A data grant authorizes a data role to access specific columns (column masking) "
        "and rows (row-level filtering) of a table or view."
    )
    st.subheader("Existing Data Grants")
    try:
        grants = api_get("deepsec/data-grants", extra_headers=_client_header())
    except httpx.HTTPStatusError as exc:
        _error("Unable to list data grants", exc)
        grants = []
    if grants:
        field_specs = [
            ("name", "Name"),
            ("grantee", "Grantee"),
            ("object", "Object"),
            ("privileges", "Privileges"),
            ("columns", "Columns"),
        ]
        # Wider leading column so the "Edit" button isn't squeezed by the five field columns.
        col_widths = [3, 6, 5, 6, 5, 5]
        with st.container(border=True):
            _render_table_header(col_widths, field_specs, leading=True)
            for grant in _group_grants(grants):
                name = grant["name"]
                row_key = name.lower()
                cols = st.columns(col_widths, vertical_alignment="center")
                cols[0].button(
                    "Edit",
                    key=f"ds_grant_edit_{row_key}",
                    on_click=_data_grant_dialog,
                    kwargs={
                        "caps": caps,
                        "authenticated": authenticated,
                        "action": "edit",
                        "roles": roles,
                        "grant": grant,
                    },
                )
                field_values = [
                    name,
                    grant["grantee"],
                    grant["object"],
                    ", ".join(grant["privileges"]),
                    ", ".join(grant["columns"]) or "All",
                ]
                _render_row_fields(cols[1:], field_specs, field_values, "ds_grant", row_key)
    else:
        st.info("No data grants defined.")

    if caps.get("manage_data_grants"):
        if st.button("Create Data Grant", type="primary", key="ds_grant_create_btn", disabled=not authenticated):
            _data_grant_dialog(caps=caps, authenticated=authenticated, action="add", roles=roles)
    else:
        st.info(_grant_hint("Creating data grants", "CREATE DATA GRANT, ADMINISTER ANY DATA GRANT"))


#####################################################
# Entry point
#####################################################


def display_deepsec() -> None:
    """Streamlit GUI."""
    db_alias = _db_alias()
    st.header("Deep Data Security")
    st.write(
        f"Manage Oracle Deep Data Security on the **{db_alias}** database. "
        "Configure data roles, end users, and data grants for column and row-level access control."
    )

    try:
        status = api_get("deepsec/status", extra_headers=_client_header())
    except httpx.HTTPStatusError as exc:
        _error("Deep Data Security is unavailable", exc)
        return

    if not status.get("available"):
        st.warning(
            f"Deep Data Security is not available on the **{db_alias}** database. It requires Oracle AI Database 26ai."
        )
        if status.get("version"):
            st.caption(f"Database version: {status['version']}")
        return

    authenticated = is_authenticated()
    if not authenticated:
        locked_notice()

    caps = status.get("capabilities", {})

    roles = _render_data_roles(caps, authenticated)
    _render_end_users(caps, authenticated)
    _render_data_grants(caps, authenticated, roles)
