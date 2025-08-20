"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes a web interface for model configuration using Streamlit (`st`).

Session States Set:
- model_configs: Stores all Model Configurations
"""
# spell-checker:ignore selectbox ocigenai

from time import sleep
from typing import Literal
import urllib.parse

import streamlit as st
from streamlit import session_state as state

import client.utils.api_call as api_call
import client.utils.st_common as st_common

import common.help_text as help_text
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("client.content.config.tabs.models")


###################################
# Functions
###################################
def clear_client_models(model_id: str) -> None:
    """Clear selected models from client settings if modified"""
    model_keys = [
        ("ll_model", "model"),
        ("testbed", "judge_model"),
        ("testbed", "qa_ll_model"),
        ("testbed", "qa_embed_model"),
    ]
    for section, key in model_keys:
        if state.client_settings[section][key] == model_id:
            state.client_settings[section][key] = None


def get_models(force: bool = False) -> None:
    """Get Models from API Server"""
    if force or "model_configs" not in state or not state.model_configs:
        try:
            logger.info("Refreshing state.model_configs")
            state.model_configs = api_call.get(endpoint="v1/models", params={"include_disabled": True})
        except api_call.ApiError as ex:
            logger.error("Unable to populate state.model_configs: %s", ex)
            state.model_configs = {}


@st.cache_data(show_spinner="Retrieving Model Providers")
def get_model_providers() -> list:
    """Get list of valid Providers; function for Streamlit caching"""
    response = api_call.get(endpoint="v1/models/provider")
    return response


def create_model(model: dict) -> None:
    """Add either Language Model or Embed Model"""
    _ = api_call.post(endpoint="v1/models", params={"id": model["id"]}, payload={"json": model})
    st.success(f"Model created: {model['id']}")


def patch_model(model: dict) -> None:
    """Update Model Configuration for either Language Models or Embed Models"""
    _ = api_call.patch(endpoint=f"v1/models/{model['id']}", payload={"json": model})
    st.success(f"Model updated: {model['id']}")
    # If updated model is the set model and not enabled: unset the user settings
    if not model["enabled"]:
        clear_client_models(model["id"])


def delete_model(model_id: str) -> None:
    """Update Model Configuration for either Language Models or Embed Models"""
    api_call.delete(endpoint=f"v1/models/{model_id}")
    st.success(f"Model deleted: {model_id}")
    sleep(1)
    # If deleted model is the set model; unset the user settings
    clear_client_models(model_id)


@st.dialog("Model Configuration", width="large")
def edit_model(model_type: str, action: Literal["add", "edit"], model_id: str = None) -> None:
    """Model Edit Dialog Box"""
    # Initialize our model request
    if action == "edit":
        model_id = urllib.parse.quote(model_id, safe="")
        model = api_call.get(endpoint=f"v1/models/{model_id}")
    else:
        model = {"id": "unset", "type": model_type, "provider": "unset", "status": "CUSTOM"}
    with st.form("edit_model"):
        if action == "add":
            model["enabled"] = True  # Server will update based on API URL Accessibility
        else:
            model["enabled"] = st.checkbox("Enabled", value=True if action == "add" else model["enabled"])
        model["id"] = st.text_input(
            "Model ID (Required):",
            help=help_text.help_dict["model_id"],
            value=None if model["id"] == "unset" else model["id"],
            key="add_model_id",
            disabled=action == "edit",
        )
        providers = get_model_providers()
        provider_index = next((i for i, item in enumerate(providers) if item == model["provider"]), None)
        disable_for_oci = model["provider"] == "ocigenai"
        model["provider"] = st.selectbox(
            "Provider (Required):",
            help=help_text.help_dict["model_provider"],
            placeholder="-- Choose the Model's Provider --",
            index=provider_index,
            options=providers,
            key="add_model_provider",
            disabled=action == "edit",
        )
        model["url"] = st.text_input(
            "Provider URL:",
            help=help_text.help_dict["model_url"],
            key="add_model_url",
            value=model.get("url", ""),
            disabled=disable_for_oci,
        )
        model["api_key"] = st.text_input(
            "API Key:",
            help=help_text.help_dict["model_api_key"],
            key="add_model_api_key",
            type="password",
            value=model.get("api_key", ""),
            disabled=disable_for_oci,
        )
        if model_type == "ll":
            model["context_length"] = st.number_input(
                "Context Length:",
                help=help_text.help_dict["context_length"],
                min_value=0,
                key="add_model_context_length",
                value=model.get("context_length", 8192),
            )
            model["temperature"] = st.number_input(
                "Default Temperature:",
                help=help_text.help_dict["temperature"],
                min_value=0.00,
                max_value=2.00,
                key="add_model_temperature",
                value=model.get("temperature", 1.0),
            )
            model["max_completion_tokens"] = st.number_input(
                "Max Completion Tokens:",
                help=help_text.help_dict["max_completion_tokens"],
                min_value=1,
                key="add_model_max_completion_tokens",
                value=model.get("max_completion_tokens", 4096),
            )
            model["frequency_penalty"] = st.number_input(
                "Default Frequency Penalty:",
                help=help_text.help_dict["frequency_penalty"],
                min_value=-2.00,
                max_value=2.00,
                value=model.get("frequency_penalty", 0.5),
                key="add_model_frequency_penalty",
            )
        else:
            model["chunk_size"] = st.number_input(
                "Max Chunk Size:",
                help=help_text.help_dict["chunk_size"],
                min_value=0,
                key="add_model_max_chunk_size",
                value=model.get("chunk_size", 8191),
            )
        submit = False
        button_col_format = st.columns([1.2, 1.4, 6, 1.4])
        action_button, delete_button, _, cancel_button = button_col_format
        try:
            if action == "add" and action_button.form_submit_button(
                label="Add", type="primary", use_container_width=True
            ):
                create_model(model=model)
                submit = True
            if action == "edit" and action_button.form_submit_button(
                label="Save", type="primary", use_container_width=True
            ):
                patch_model(model=model)
                submit = True
            if action != "add" and delete_button.form_submit_button(
                label="Delete", type="secondary", use_container_width=True
            ):
                delete_model(model_id=model["id"])
                submit = True
            if submit:
                sleep(1)
                st_common.clear_state_key("model_configs")
                st.rerun()
        except api_call.ApiError as ex:
            st.error(f"Failed to {action} model: {ex}")
        if cancel_button.form_submit_button(label="Cancel", type="secondary"):
            st_common.clear_state_key("model_configs")
            st.rerun()


def render_model_rows(model_type: str) -> None:
    """Render rows of the models"""
    data_col_widths = [0.07, 0.23, 0.2, 0.28, 0.12]
    table_col_format = st.columns(data_col_widths, vertical_alignment="center")
    col1, col2, col3, col4, col5 = table_col_format
    col1.markdown("&#x200B;", help="Active", unsafe_allow_html=True)
    col2.markdown("**<u>Model ID</u>**", unsafe_allow_html=True)
    col3.markdown("**<u>Provider</u>**", unsafe_allow_html=True)
    col4.markdown("**<u>Provider URL</u>**", unsafe_allow_html=True)
    col5.markdown("&#x200B;")
    for model in [m for m in state.model_configs if m.get("type") == model_type]:
        model_id = model["id"]
        col1.text_input(
            "Enabled",
            value=st_common.bool_to_emoji(model["enabled"]),
            key=f"{model_type}_{model_id}_enabled",
            label_visibility="collapsed",
            disabled=True,
        )
        col2.text_input(
            "Model",
            value=model_id,
            label_visibility="collapsed",
            disabled=True,
        )
        col3.text_input(
            "Provider",
            value=model["provider"],
            key=f"{model_type}_{model_id}_provider",
            label_visibility="collapsed",
            disabled=True,
        )
        col4.text_input(
            "Server",
            value=model["url"],
            key=f"{model_type}_{model_id}_server",
            label_visibility="collapsed",
            disabled=True,
        )
        col5.button(
            "Edit",
            on_click=edit_model,
            key=f"{model_type}_{model_id}_edit",
            kwargs=dict(model_type=model_type, action="edit", model_id=model_id),
        )

    if st.button(label="Add", type="primary", key=f"add_{model_type}_model"):
        edit_model(model_type=model_type, action="add")


#############################################################################
# MAIN
#############################################################################
def display_models() -> None:
    """Streamlit GUI"""
    st.header("Models", divider="red")
    st.write("Update, Add, or Delete model configuration parameters.")
    try:
        get_models()
    except api_call.ApiError:
        st.stop()

    st.divider()
    st.subheader("Language Models")
    render_model_rows("ll")

    st.divider()
    st.subheader("Embedding Models")
    render_model_rows("embed")


if __name__ == "__main__":
    display_models()
