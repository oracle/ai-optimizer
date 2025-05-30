"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Script initializes a web interface for Oracle Cloud Infrastructure (OCI)
It includes a form to input and test OCI API Access.

Session States Set:
- oci_config: Stores OCI Configuration
"""
# spell-checker:ignore streamlit, ocid, selectbox, genai, oraclecloud

import inspect
import time
import re

import streamlit as st
from streamlit import session_state as state

import client.utils.api_call as api_call
import client.utils.st_common as st_common
from client.content.config.models import get_models

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("client.content.config.oci")


#####################################################
# Functions
#####################################################
def get_oci(force: bool = False) -> dict[str, dict]:
    """Get a dictionary of all OCI Configurations"""
    if "oci_config" not in state or state["oci_config"] == {} or force:
        try:
            response = api_call.get(endpoint="v1/oci")
            state["oci_config"] = {
                item["auth_profile"]: {k: v if v is not None else None for k, v in item.items() if k != "auth_profile"}
                for item in response
            }
            logger.info("State created: state['oci_config']")
        except api_call.ApiError as ex:
            st.error(f"Unable to retrieve oci_configuration: {ex}", icon="🚨")
            state["oci_config"] = {}


def patch_oci(
    auth_profile: str,
    fingerprint: str,
    tenancy: str,
    region: str,
    key_file: str,
    user: str = None,
    security_token_file: str = None,
) -> None:
    """Update OCI"""
    get_oci()
    # Check if the OIC configuration is changed, or no namespace
    if (
        state.oci_config[auth_profile]["user"] != user
        or state.oci_config[auth_profile]["fingerprint"] != fingerprint
        or state.oci_config[auth_profile]["tenancy"] != tenancy
        or state.oci_config[auth_profile]["region"] != region
        or state.oci_config[auth_profile]["key_file"] != key_file
        or state.oci_config[auth_profile]["security_token_file"] != security_token_file
        or not state.oci_config[auth_profile]["namespace"]
    ):
        try:
            if security_token_file:
                state.oci_config[auth_profile]["authentication"] = "security_token"
            _ = api_call.patch(
                endpoint=f"v1/oci/{auth_profile}",
                payload={
                    "json": {
                        "user": user,
                        "fingerprint": fingerprint,
                        "tenancy": tenancy,
                        "region": region,
                        "key_file": key_file,
                        "security_token_file": security_token_file,
                        "authentication": state.oci_config[auth_profile]["authentication"]
                    }
                },
            )
            logger.info("OCI Profile updated: %s", auth_profile)
            st_common.clear_state_key("oci_error")
            get_oci(force=True)
        except api_call.ApiError as ex:
            logger.error("OCI Update failed: %s", ex)
            state.oci_config[auth_profile]["namespace"] = None
            state.oci_error = ex
    else:
        st.info(f"{auth_profile} OCI Configuration - No Changes Detected.", icon="ℹ️")
        time.sleep(2)


def patch_oci_genai(
    auth_profile: str,
    compartment_id: str,
    region: str,
) -> None:
    """Update OCI"""
    get_oci()
    service_endpoint = f"https://inference.generativeai.{region}.oci.oraclecloud.com"
    if (
        state.oci_config[auth_profile]["compartment_id"] != compartment_id
        or state.oci_config[auth_profile]["service_endpoint"] != service_endpoint
    ):
        try:
            _ = api_call.patch(
                endpoint=f"v1/oci/{auth_profile}",
                payload={
                    "json": {
                        **state.oci_config[auth_profile],
                        "compartment_id": compartment_id,
                        "service_endpoint": service_endpoint,
                    }
                },
            )
            st.success(f"{auth_profile} OCI GenAI Configuration - Updated", icon="✅")
            st_common.clear_state_key("oci_error")
            get_oci(force=True)
            get_models(force=True)
        except api_call.ApiError as ex:
            logger.error("OCI Update failed: %s", ex)
            state.oci_error = ex
            try:
                state.oci_config[auth_profile]["namespace"] = None
            except AttributeError:
                pass
    else:
        st.info(f"{auth_profile} OCI GenAI Configuration - No Changes Detected.", icon="ℹ️")
        time.sleep(2)


#####################################################
# MAIN
#####################################################
def main() -> None:
    """Streamlit GUI"""
    st.header("Oracle Cloud Infrastructure", divider="red")
    st.write("Configure OCI for Object Storage Access and OCI GenAI Services.")
    try:
        get_oci()  # Create/Rebuild state
    except api_call.ApiError:
        st.stop()
    st.subheader("Configuration")
    # Set Default Profile
    auth_profile = state.user_settings["oci"]["auth_profile"]
    avail_profiles = [key for key in state.oci_config.keys() if key != "DEFAULT"]
    avail_profiles = ["DEFAULT"] + avail_profiles
    if len(avail_profiles) > 0:
        st.selectbox(
            "Profile:",
            options=avail_profiles,
            index=avail_profiles.index(auth_profile),
            key="selected_oci_profile",
            on_change=st_common.update_user_settings("oci"),
        )
    token_auth = st.checkbox(
        "Use token authentication?",
        key="oci_token_auth",
        value=False,
    )
    with st.form("update_oci_config"):
        user = st.text_input(
            "User OCID:",
            value=state.oci_config[auth_profile]["user"],
            disabled=token_auth,
            key="oci_user",
        )
        security_token_file = st.text_input(
            "Security Token File:",
            value=state.oci_config[auth_profile]["security_token_file"],
            disabled=not token_auth,
            key="oci_security_token_file",
        )
        fingerprint = st.text_input(
            "Fingerprint:",
            value=state.oci_config[auth_profile]["fingerprint"],
            key="oci_fingerprint",
        )
        tenancy = st.text_input(
            "Tenancy OCID:",
            value=state.oci_config[auth_profile]["tenancy"],
            key="oci_tenancy",
        )
        region = st.text_input(
            "Region:",
            value=state.oci_config[auth_profile]["region"],
            help="Region of Source Bucket",
            key="oci_region",
        )
        key_file = st.text_input(
            "Key File:",
            value=state.oci_config[auth_profile]["key_file"],
            key="oci_key_file",
        )
        if not state.oci_config[auth_profile]["namespace"]:
            st.error("Current Status: Unverified")
            if "oci_error" in state:
                st.error(f"Update Failed - {state.oci_error}", icon="🚨")
        else:
            st.success(f"Current Status: Validated - Namespace: {state.oci_config[auth_profile]['namespace']}")

        if st.form_submit_button(label="Save"):
            security_token_file = None if not token_auth else security_token_file
            user = None if token_auth else user
            patch_oci(auth_profile, fingerprint, tenancy, region, key_file, user, security_token_file)
            st.rerun()

    st.subheader("OCI GenAI", divider="red")
    st.write(
        "Configure the Compartment and Region for OCI GenAI Services.  OCI Authentication must be configured above."
    )
    with st.form("update_oci_genai_config"):
        genai_compartment = st.text_input(
            "OCI GenAI Compartment OCID:",
            value=state.oci_config[auth_profile]["compartment_id"],
            placeholder="Compartment OCID for GenAI Services",
            key="oci_genai_compartment",
            disabled=not state.oci_config[auth_profile]["namespace"],
        )
        match = re.search(
            r"\.([a-zA-Z\-0-9]+)\.oci\.oraclecloud\.com", state.oci_config[auth_profile]["service_endpoint"]
        )
        genai_region = match.group(1) if match else None
        genai_region = st.text_input(
            "OCI GenAI Region:",
            value=genai_region,
            help="Region of GenAI Service",
            key="oci_genai_region",
            disabled=not state.oci_config[auth_profile]["namespace"],
        )
        if st.form_submit_button(label="Save", disabled=not state.oci_config[auth_profile]["namespace"]):
            if not (genai_compartment and genai_region):
                st.error("All fields are required.", icon="🛑")
                st.stop()
            patch_oci_genai(auth_profile, genai_compartment, genai_region)
            st.rerun()


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
