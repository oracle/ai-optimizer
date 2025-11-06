"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Script initializes a web interface for Oracle Cloud Infrastructure (OCI)
It includes a form to input and test OCI API Access.
"""
# spell-checker:ignore streamlit ocid selectbox genai oraclecloud
import time
import pandas as pd

import streamlit as st
from streamlit import session_state as state

from client.utils import api_call, st_common
from common import logging_config

logger = logging_config.logging.getLogger("client.content.config.tabs.oci")


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

    # Handle instance_principal and oke_workload_identity
    oci_auth = state.oci_configs[0].get("authentication")
    if len(oci_lookup) == 1 and oci_auth in (
        "instance_principal",
        "oke_workload_identity",
    ):
        st.info("Using OCI Authentication Principals", icon="ℹ️")
        supplied["authentication"] = oci_auth
        supplied["tenancy"] = state.oci_configs[0]["tenancy"]
        disable_config = True

    return supplied, disable_config


def _render_profile_selection(oci_lookup: dict, disable_config: bool) -> str:
    """Render the OCI profile selection UI.

    Returns:
        str: Selected OCI auth profile
    """
    if len(oci_lookup) > 0:
        selected_oci_auth_profile = st.selectbox(
            "Profile:",
            options=list(oci_lookup.keys()),
            index=list(oci_lookup.keys()).index(state.client_settings["oci"]["auth_profile"]),
            key="selected_oci",
            on_change=st_common.update_client_settings("oci"),
            disabled=disable_config,
        )
    else:
        selected_oci_auth_profile = "DEFAULT"

    return selected_oci_auth_profile


def _render_oci_configuration_form(
    oci_lookup: dict, selected_oci_auth_profile: str, disable_config: bool, namespace: str, auth_supplied: dict
) -> dict:
    """Render the OCI configuration form."""
    supplied = {}
    token_auth = st.checkbox("Use token authentication?", key="oci_token_auth", value=False, disabled=disable_config)

    with st.container(border=True):
        if not disable_config:
            supplied["user"] = st.text_input(
                "User OCID:",
                value=oci_lookup[selected_oci_auth_profile]["user"],
                disabled=token_auth,
                key="oci_user",
            )
            supplied["security_token_file"] = st.text_input(
                "Security Token File:",
                value=oci_lookup[selected_oci_auth_profile]["security_token_file"],
                disabled=not token_auth,
                key="oci_security_token_file",
            )
            supplied["key_file"] = st.text_input(
                "Key File:",
                value=oci_lookup[selected_oci_auth_profile]["key_file"],
                key="oci_key_file",
            )
            supplied["fingerprint"] = st.text_input(
                "Fingerprint:",
                value=oci_lookup[selected_oci_auth_profile]["fingerprint"],
                key="oci_fingerprint",
            )
            supplied["tenancy"] = st.text_input(
                "Tenancy OCID:",
                value=oci_lookup[selected_oci_auth_profile]["tenancy"],
                key="oci_tenancy",
            )
        supplied["region"] = st.text_input(
            "Region:",
            value=oci_lookup[selected_oci_auth_profile]["region"],
            help="Region of Source Bucket",
            key="oci_region",
        )

        # Display status
        if namespace:
            st.success(f"Current Status: Validated - Namespace: {namespace}")
        else:
            st.error("Current Status: Unverified")
            if "oci_error" in state:
                st.error(f"Update Failed - {state.oci_error}", icon="🚨")

        # Save button and logic
        if st.button("Save Configuration", key="save_oci"):
            # Modify based on token usage
            if not disable_config:
                supplied["security_token_file"] = None if not token_auth else supplied["security_token_file"]
                supplied["user"] = None if token_auth else supplied["user"]

            # Merge with auth settings before patching
            supplied = {**auth_supplied, **supplied}

            if patch_oci(selected_oci_auth_profile, supplied, namespace):
                st.rerun()

    return supplied


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
                "Large Language": st_common.bool_to_emoji("CHAT" in m["capabilities"]),
                "Embedding": st_common.bool_to_emoji("TEXT_EMBEDDINGS" in m["capabilities"]),
            }
        )

    # Convert to DataFrame and display
    df = pd.DataFrame(table_data)
    st.dataframe(df, hide_index=True)


def _render_oci_genai_section(
    oci_lookup: dict, selected_oci_auth_profile: str, namespace: str, supplied: dict
) -> None:
    """Render the OCI GenAI configuration section."""
    st.subheader("OCI GenAI", divider="red")
    st.write("""
        Configure the Compartment and Region for OCI GenAI Services.
        OCI Authentication must be configured above.
        """)

    with st.container(border=True):
        if "genai_models" not in state:
            state.genai_models = []

        supplied["genai_compartment_id"] = st.text_input(
            "OCI GenAI Compartment OCID:",
            value=oci_lookup[selected_oci_auth_profile]["genai_compartment_id"],
            placeholder="Compartment OCID for GenAI Services",
            key="oci_genai_compartment_id",
            disabled=not namespace,
        )

        if st.button("Check for OCI GenAI Models", key="check_oci_genai", disabled=not namespace):
            if not supplied["genai_compartment_id"]:
                st.error("OCI GenAI Compartment OCID is required.", icon="🛑")
                st.stop()
            with st.spinner("Looking for OCI GenAI Models... please be patient.", show_time=True):
                patch_oci(selected_oci_auth_profile, supplied, namespace, toast=False)
                state.genai_models = get_genai_models()

        if state.genai_models:
            regions = list({item["region"] for item in state.genai_models if "region" in item})
            supplied["genai_region"] = st.selectbox(
                "Region:",
                regions,
                key="selected_genai_region",
            )

            _render_genai_models_table(state.genai_models, supplied["genai_region"])

            if st.button("Enable Region Models", key="enable_oci_region_models", type="primary"):
                with st.spinner("Enabling OCI GenAI Models... please be patient.", show_time=True):
                    patch_oci(selected_oci_auth_profile, supplied, namespace, toast=False)
                    get_oci()
                    create_genai_models()
                    st_common.clear_state_key("model_configs")
                st.success("Oracle GenAI models - Enabled.", icon="✅")
                time.sleep(1)
                st.rerun()


def get_oci(force: bool = False) -> None:
    """Get a dictionary of all OCI Configurations"""
    if force or "oci_configs" not in state or not state.oci_configs:
        try:
            logger.info("Refreshing state.oci_configs")
            state.oci_configs = api_call.get(endpoint="v1/oci")
        except api_call.ApiError as ex:
            st.error(f"Unable populate state.oci_configs: {ex}", icon="🚨")
            state.oci_configs = {}


def get_genai_models() -> list[dict]:
    """Get Subscribed OCI Regions"""
    endpoint = f"v1/oci/genai/{state.client_settings['oci']['auth_profile']}"
    genai_models = api_call.get(endpoint=endpoint)
    return genai_models


def create_genai_models() -> list[dict]:
    """Create OCI GenAI Models"""
    endpoint = f"v1/oci/genai/{state.client_settings['oci']['auth_profile']}"
    genai_models = api_call.post(endpoint=endpoint)
    return genai_models


def patch_oci(auth_profile: str, supplied: dict, namespace: str, toast: bool = True) -> bool:
    """Update OCI"""
    rerun = False
    # Check if the OCI configuration is changed, or no namespace
    existing = next((item for item in state.oci_configs if item["auth_profile"] == auth_profile), None)
    differences = {key: (existing.get(key), supplied[key]) for key in supplied if existing.get(key) != supplied[key]}
    if differences or not namespace:
        rerun = True
        try:
            if supplied.get("authentication") not in (
                "instance_principal",
                "oke_workload_identity",
            ) and supplied.get("security_token_file"):
                supplied["authentication"] = "security_token"

            with st.spinner(text="Updating OCI Profile...", show_time=True):
                _ = api_call.patch(endpoint=f"v1/oci/{auth_profile}", payload={"json": supplied}, toast=toast)
            logger.info("OCI Profile updated: %s", auth_profile)
        except api_call.ApiError as ex:
            logger.error("OCI Update failed: %s", ex)
            state.oci_error = ex
        st_common.clear_state_key("oci_configs")
    else:
        if toast:
            st.toast("No Changes Detected.", icon="ℹ️")

    return rerun


#####################################################
# MAIN
#####################################################
def display_oci() -> None:
    """Streamlit GUI"""
    st.header("Oracle Cloud Infrastructure", divider="red")
    st.write("Configure OCI for Object Storage Access and OCI GenAI Services.")

    try:
        get_oci()
    except api_call.ApiError:
        st.stop()

    st.subheader("Configuration")

    oci_lookup = st_common.state_configs_lookup("oci_configs", "auth_profile")

    # Handle authentication principals
    auth_supplied, disable_config = _handle_authentication_principals(oci_lookup)

    # Render profile selection
    selected_oci_auth_profile = _render_profile_selection(oci_lookup, disable_config)

    namespace = oci_lookup[selected_oci_auth_profile]["namespace"]

    # Render configuration form and merge with auth settings
    form_supplied = _render_oci_configuration_form(
        oci_lookup, selected_oci_auth_profile, disable_config, namespace, auth_supplied
    )
    supplied = {**auth_supplied, **form_supplied}

    # Render GenAI section
    _render_oci_genai_section(oci_lookup, selected_oci_auth_profile, namespace, supplied)


if __name__ == "__main__":
    display_oci()
