"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Script initializes a web interface for Oracle Cloud Infrastructure (OCI)
It includes a form to input and test OCI API Access.
"""
# spell-checker:ignore streamlit, ocid, selectbox, genai, oraclecloud

import inspect
import re

import streamlit as st
from streamlit import session_state as state

import client.utils.api_call as api_call
import client.utils.st_common as st_common
from client.utils.st_footer import remove_footer

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("client.content.config.oci")


#####################################################
# Functions
#####################################################
def get_oci(force: bool = False) -> None:
    """Get a dictionary of all OCI Configurations"""
    if force or "oci_configs" not in state or not state.oci_configs:
        try:
            logger.info("Refreshing state.oci_configs")
            state.oci_configs = api_call.get(endpoint="v1/oci")
        except api_call.ApiError as ex:
            st.error(f"Unable populate state.oci_configs: {ex}", icon="🚨")
            state.oci_configs = {}


def patch_oci(auth_profile: str, supplied: dict, namespace: str) -> bool:
    """Update OCI"""
    rerun = False
    # Check if the OIC configuration is changed, or no namespace
    existing = next((item for item in state.oci_configs if item["auth_profile"] == auth_profile), None)
    differences = {key: (existing.get(key), supplied[key]) for key in supplied if existing.get(key) != supplied[key]}
    if differences or not namespace:
        rerun = True
        try:
            if supplied["security_token_file"]:
                supplied["authentication"] = "security_token"

            with st.spinner(text="Updating OCI Profile...", show_time=True):
                _ = api_call.patch(
                    endpoint=f"v1/oci/{auth_profile}",
                    payload={"json": supplied},
                )
            logger.info("OCI Profile updated: %s", auth_profile)
        except api_call.ApiError as ex:
            logger.error("OCI Update failed: %s", ex)
            state.oci_error = ex
        st_common.clear_state_key("oci_configs")
        if supplied.get("service_endpoint"):
            st_common.clear_state_key("model_configs")
    else:
        st.toast("No Changes Detected.", icon="ℹ️")

    return rerun


#####################################################
# MAIN
#####################################################
def main() -> None:
    """Streamlit GUI"""
    remove_footer()
    st.header("Oracle Cloud Infrastructure", divider="red")
    st.write("Configure OCI for Object Storage Access and OCI GenAI Services.")
    try:
        get_oci()
    except api_call.ApiError:
        st.stop()

    st.subheader("Configuration")
    oci_lookup = st_common.state_configs_lookup("oci_configs", "auth_profile")
    if len(oci_lookup) > 0:
        selected_oci_auth_profile = st.selectbox(
            "Profile:",
            options=list(oci_lookup.keys()),
            index=list(oci_lookup.keys()).index(state.client_settings["oci"]["auth_profile"]),
            key="selected_oci",
            on_change=st_common.update_client_settings("oci"),
        )
    else:
        selected_oci_auth_profile = "DEFAULT"

    token_auth = st.checkbox(
        "Use token authentication?",
        key="oci_token_auth",
        value=False,
    )
    namespace = oci_lookup[selected_oci_auth_profile]["namespace"]
    # Store supplied values in dictionary
    supplied = {}
    with st.container(border=True):
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
        supplied["key_file"] = st.text_input(
            "Key File:",
            value=oci_lookup[selected_oci_auth_profile]["key_file"],
            key="oci_key_file",
        )
        if namespace:
            st.success(f"Current Status: Validated - Namespace: {namespace}")
        else:
            st.error("Current Status: Unverified")
            if "oci_error" in state:
                st.error(f"Update Failed - {state.oci_error}", icon="🚨")

        if st.button("Save Configuration", key="save_oci"):
            # Modify based on token usage
            supplied["security_token_file"] = None if not token_auth else supplied["security_token_file"]
            supplied["user"] = None if token_auth else supplied["user"]

            if patch_oci(selected_oci_auth_profile, supplied, namespace):
                st.rerun()

    st.subheader("OCI GenAI", divider="red")
    st.write("""
        Configure the Compartment and Region for OCI GenAI Services.
        OCI Authentication must be configured above.
        """)
    with st.container(border=True):
        supplied["compartment_id"] = st.text_input(
            "OCI GenAI Compartment OCID:",
            value=oci_lookup[selected_oci_auth_profile]["compartment_id"],
            placeholder="Compartment OCID for GenAI Services",
            key="oci_genai_compartment_id",
            disabled=not namespace,
        )
        match = re.search(
            r"\.([a-zA-Z\-0-9]+)\.oci\.oraclecloud\.com", oci_lookup[selected_oci_auth_profile]["service_endpoint"]
        )
        supplied["service_endpoint"] = match.group(1) if match else None
        supplied["service_endpoint"] = st.text_input(
            "OCI GenAI Region:",
            value=oci_lookup[selected_oci_auth_profile]["service_endpoint"],
            help="Region of GenAI Service",
            key="oci_genai_region",
            disabled=not namespace,
        )

        if st.button("Save OCI GenAI", key="save_oci_genai", disabled=not namespace):
            if not (supplied["compartment_id"] and supplied["service_endpoint"]):
                st.error("All fields are required.", icon="🛑")
                st.stop()
            if patch_oci(selected_oci_auth_profile, supplied, namespace):
                st.rerun()


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
