"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Script initializes a web interface for Oracle Cloud Infrastructure (OCI)
It includes a form to input and test OCI API Access.
"""
# spell-checker:ignore streamlit ocid selectbox genai oraclecloud

import logging
import time

import httpx
import pandas as pd
import streamlit as st
from streamlit import session_state as state

from client.app.core import helpers
from client.app.core.api import api_delete, api_get, api_post, api_put
from client.app.core.auth import is_authenticated, locked_notice

LOGGER = logging.getLogger("client.content.config.tabs.oci")

ADD_NEW = "Add New..."


#####################################################
# Functions
#####################################################


def _handle_authentication_principals(oci_lookup: dict) -> tuple[dict, bool]:
    """Handle instance_principal and oke_workload_identity authentication.

    Returns:
        tuple: (supplied dict with auth settings, disable_config flag)
    """
    supplied = {}
    disable_config = False

    oci_configs = state["settings"]["oci_configs"]
    oci_auth = oci_configs[0].get("authentication") if oci_configs else None
    if len(oci_lookup) == 1 and oci_auth in (
        "instance_principal",
        "oke_workload_identity",
    ):
        st.info("Using OCI Authentication Principals", icon="ℹ️")
        supplied["authentication"] = oci_auth
        supplied["tenancy"] = oci_configs[0]["tenancy"]
        disable_config = True

    return supplied, disable_config


def _on_oci_change() -> None:
    """Sync client_settings when OCI profile selection changes."""
    selected = state.get("runtime_selected_oci")
    if selected and selected != ADD_NEW:
        helpers.sync_client_setting("oci", "auth_profile", selected)


def _render_profile_selection(oci_lookup: dict, disable_config: bool) -> tuple[str, bool]:
    """Render the OCI profile selection UI.

    Returns:
        tuple: (selected_profile, is_new)
    """
    client_settings = state["settings"].get("client_settings", {})
    current_profile = client_settings.get("oci", {}).get("auth_profile", "DEFAULT")
    options = list(oci_lookup.keys()) + [ADD_NEW]

    # Apply pending selection (set after create, applied before widget)
    pending = state.pop("_pending_oci_select", None)
    if pending and pending in options:
        state["runtime_selected_oci"] = pending

    selected = (
        st.selectbox(
            "Profile:",
            options=options,
            index=helpers.selectbox_index(options, current_profile),
            key="runtime_selected_oci",
            on_change=_on_oci_change,
            disabled=disable_config,
        )
        or ""
    )

    return selected, selected == ADD_NEW


def _render_oci_configuration_form(
    oci_lookup: dict, selected: str, is_new: bool, disable_config: bool, usable: bool, auth_supplied: dict
) -> dict:
    """Render the OCI configuration form."""
    supplied = {}
    cfg = {} if is_new else oci_lookup[selected]
    profile = selected or "new"  # key suffix

    # Validated profiles are fully read-only (like CORE database)
    fields_disabled = not is_new and (disable_config or usable)

    token_auth = st.checkbox(
        "Use token authentication?", key=f"runtime_oci_token_auth_{profile}", value=False, disabled=fields_disabled
    )

    with st.container(border=True):
        if fields_disabled and usable:
            st.info("Profile is validated and read-only. Fields cannot be modified.", icon="ℹ️")

        auth_profile = (
            st.text_input("Profile Name:", value="", key=f"runtime_oci_auth_profile_{profile}") if is_new else selected
        )
        supplied["tenancy"] = st.text_input(
            "Tenancy OCID:",
            value=cfg.get("tenancy", "") or "",
            disabled=fields_disabled,
            key=f"runtime_oci_tenancy_{profile}",
        )
        supplied["region"] = st.text_input(
            "Region:",
            value=cfg.get("region", "") or "",
            help="Region of Source Bucket",
            disabled=fields_disabled,
            key=f"runtime_oci_region_{profile}",
        )
        supplied["user"] = st.text_input(
            "User OCID:",
            value=cfg.get("user", "") or "",
            disabled=fields_disabled or token_auth,
            key=f"runtime_oci_user_{profile}",
        )
        supplied["fingerprint"] = st.text_input(
            "Fingerprint:",
            value=cfg.get("fingerprint", "") or "",
            disabled=fields_disabled,
            key=f"runtime_oci_fingerprint_{profile}",
        )
        supplied["security_token_file"] = st.text_input(
            "Security Token File:",
            value=cfg.get("security_token_file", "") or "",
            disabled=fields_disabled or not token_auth,
            key=f"runtime_oci_security_token_file_{profile}",
        )
        supplied["key_file"] = st.text_input(
            "Key File:",
            value=cfg.get("key_file", "") or "",
            disabled=fields_disabled,
            key=f"runtime_oci_key_file_{profile}",
        )
        if is_new:
            supplied["key_content"] = st.text_area(
                "Key Content:",
                value="",
                help="Paste the private key directly (alternative to Key File path)",
                key=f"runtime_oci_key_content_{profile}",
                height=150,
            )

        # Display status
        if not is_new:
            if usable:
                namespace = cfg.get("namespace")
                st.success(
                    f"Current Status: Validated — Namespace: {namespace}" if namespace else "Current Status: Validated"
                )
            else:
                st.error("Current Status: Unverified")

        # Prepare submission data
        submit_supplied = dict(supplied)
        submit_supplied["security_token_file"] = None if not token_auth else supplied["security_token_file"]
        submit_supplied["user"] = None if token_auth else supplied["user"]
        submit_supplied["key_file"] = None if supplied.get("key_content") else supplied.get("key_file")
        submit_supplied = {**auth_supplied, **submit_supplied}

        # Action buttons
        cols = st.columns([2, 3, 5])
        cols[0].button(
            "Create" if is_new else "Save",
            key=f"save_oci_{profile}",
            disabled=fields_disabled,
            type="primary",
            width="stretch",
            on_click=_handle_oci_submit,
            kwargs={
                "is_new": is_new,
                "auth_profile": auth_profile,
                "selected": selected,
                "supplied": submit_supplied,
            },
        )
        with cols[1]:
            if not is_new:
                with st.popover("⚠️ Remove Profile"):
                    st.warning(f"Are you sure you want to remove **{selected}**?")
                    if st.button("Confirm Remove", key=f"confirm_delete_oci_{profile}", type="primary"):
                        _remove_oci(selected)

    return supplied


def _handle_oci_submit(is_new: bool, auth_profile: str, selected: str, supplied: dict) -> None:
    """Process OCI form submission (create or update)."""
    if is_new:
        _create_oci(auth_profile, supplied)
    else:
        _update_oci(selected, supplied)


def _render_genai_models_table(genai_models: list, genai_region: str) -> None:
    """Render the GenAI models table."""
    filtered_models = [
        m
        for m in genai_models
        if m["region"] == genai_region and ("CHAT" in m["capabilities"] or "TEXT_EMBEDDINGS" in m["capabilities"])
    ]
    table_data = []
    for m in filtered_models:
        table_data.append(
            {
                "Model Name": m["model_name"],
                "Large Language": helpers.bool_to_emoji("CHAT" in m["capabilities"]),
                "Embedding": helpers.bool_to_emoji("TEXT_EMBEDDINGS" in m["capabilities"]),
            }
        )

    # Convert to DataFrame and display
    df = pd.DataFrame(table_data)
    st.dataframe(df, hide_index=True)


def _render_oci_genai_section(oci_lookup: dict, selected_oci_auth_profile: str, usable: bool, supplied: dict) -> None:
    """Render the OCI GenAI configuration section."""
    st.subheader("OCI GenAI", divider="red")
    st.write("""
        Configure the Compartment and Region for OCI GenAI Services.
        OCI Authentication must be configured above.
        """)

    with st.container(border=True):
        if "genai_models" not in state:
            state.genai_models = []

        profile = selected_oci_auth_profile  # key suffix
        supplied["genai_compartment_id"] = st.text_input(
            "OCI GenAI Compartment OCID:",
            value=oci_lookup[selected_oci_auth_profile].get("genai_compartment_id", "") or "",
            placeholder="Compartment OCID for GenAI Services",
            key=f"runtime_oci_genai_compartment_id_{profile}",
            disabled=not usable,
        )

        if st.button("Check for OCI GenAI Models", key=f"check_oci_genai_{profile}", disabled=not usable):
            if not supplied["genai_compartment_id"]:
                st.error("OCI GenAI Compartment OCID is required.", icon="🛑")
                st.stop()
            with st.spinner("Looking for OCI GenAI Models... please be patient.", show_time=True):
                _update_oci(selected_oci_auth_profile, supplied, toast=False)
                state.genai_models = _get_genai_models(selected_oci_auth_profile)

        if state.genai_models:
            regions = list({item["region"] for item in state.genai_models if "region" in item})
            supplied["genai_region"] = (
                st.selectbox(
                    "Region:",
                    regions,
                    key=f"selected_genai_region_{profile}",
                )
                or ""
            )

            _render_genai_models_table(state.genai_models, supplied["genai_region"])

            if st.button("Enable Region Models", key=f"enable_oci_region_models_{profile}", type="primary"):
                with st.spinner("Enabling OCI GenAI Models... please be patient.", show_time=True):
                    if not _update_oci(selected_oci_auth_profile, supplied, toast=False):
                        st.stop()
                    _create_genai_models(selected_oci_auth_profile)
                    helpers.refresh_settings()
                    _get_oci(force=True)
                st.success("Oracle GenAI models - Enabled.", icon="✅")
                time.sleep(1)
                st.rerun()


def _get_oci(force: bool = False) -> None:
    """Populate the OCI configs in session state for display and editing."""
    if force or not state.get("_oci_sensitive_loaded"):
        try:
            LOGGER.info("Refreshing OCI configs (per-profile fetch)")
            masked = api_get("oci")
            detailed: list[dict] = []
            for entry in masked:
                profile = entry.get("auth_profile")
                if not profile:
                    detailed.append(entry)
                    continue
                detailed.append(
                    api_get(f"oci/{profile}", params={"include_sensitive": "true"})
                )
            state["settings"]["oci_configs"] = detailed
            state["_oci_sensitive_loaded"] = True
        except httpx.HTTPStatusError as ex:
            st.error(f"Unable to load OCI configs: {helpers.extract_error_detail(ex)}", icon="🚨")


def _get_genai_models(auth_profile: str) -> list[dict]:
    """Get available GenAI models across subscribed regions."""
    return api_get(f"oci/genai/{auth_profile}", timeout=180)


def _create_genai_models(auth_profile: str) -> None:
    """Create OCI GenAI Models."""
    api_post(f"oci/genai/{auth_profile}", timeout=180)


def _create_oci(auth_profile: str | None, supplied: dict) -> None:
    """Create a new OCI profile."""
    name = auth_profile.strip() if auth_profile else ""
    if not name:
        st.error("Profile Name is required.")
        return
    supplied["auth_profile"] = name
    try:
        with st.spinner("Creating OCI profile..."):
            api_post("oci", json=helpers.build_payload(supplied), toast=f"OCI Profile **{name}** created.")
        _get_oci(force=True)
        state["_pending_oci_select"] = name
    except httpx.HTTPStatusError as exc:
        st.error(f"Error: {helpers.extract_error_detail(exc)}")


def _remove_oci(auth_profile: str) -> None:
    """Remove an OCI profile configuration."""
    try:
        with st.spinner("Removing OCI profile..."):
            api_delete(f"oci/{auth_profile}")
        _get_oci(force=True)
    except httpx.HTTPStatusError as exc:
        st.error(f"Remove failed: {helpers.extract_error_detail(exc)}")


def _update_oci(auth_profile: str, supplied: dict, toast: bool = True) -> bool:
    """Update OCI profile configuration."""
    rerun = False
    oci_configs = state["settings"].get("oci_configs", [])
    existing = next((item for item in oci_configs if item["auth_profile"] == auth_profile), {})
    usable = existing.get("usable", False)
    differences = {key: (existing.get(key), supplied[key]) for key in supplied if existing.get(key) != supplied[key]}

    if differences or not usable:
        rerun = True
        try:
            if supplied.get("authentication") not in (
                "instance_principal",
                "oke_workload_identity",
            ) and supplied.get("security_token_file"):
                supplied["authentication"] = "security_token"

            with st.spinner(text="Updating OCI Profile...", show_time=True):
                api_put(
                    f"oci/{auth_profile}",
                    json=helpers.build_payload(supplied),
                    toast="OCI Profile updated." if toast else None,
                )
            LOGGER.info("OCI Profile updated: %s", auth_profile)
        except httpx.HTTPStatusError as ex:
            LOGGER.error("OCI Update failed: %s", ex)
            st.error(f"Update Failed: {helpers.extract_error_detail(ex)}", icon="🚨")
            _get_oci(force=True)
            return False
        helpers.refresh_settings()
        _get_oci(force=True)
    elif toast:
        st.toast("No Changes Detected.", icon="ℹ️")

    return rerun


#####################################################
# MAIN
#####################################################
def display_oci() -> None:
    """Streamlit GUI"""
    locked_notice()
    st.header("Oracle Cloud Infrastructure", divider="red")
    st.write("Configure OCI for Object Storage Access and OCI GenAI Services.")

    if not is_authenticated():
        return

    _get_oci()

    st.subheader("Configuration")

    oci_lookup = helpers.state_configs_lookup("oci_configs", "auth_profile")

    # Handle authentication principals
    auth_supplied, disable_config = _handle_authentication_principals(oci_lookup)

    # Render profile selection (always shown — includes "Add New...")
    selected, is_new = _render_profile_selection(oci_lookup, disable_config)

    usable = False if is_new else oci_lookup[selected].get("usable", False)

    # Render configuration form and merge with auth settings
    form_supplied = _render_oci_configuration_form(oci_lookup, selected, is_new, disable_config, usable, auth_supplied)
    supplied = {**auth_supplied, **form_supplied}

    # Render GenAI section (only for existing validated profiles)
    if not is_new:
        _render_oci_genai_section(oci_lookup, selected, usable, supplied)
