"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes a web interface for model configuration using Streamlit (`st`).

Session States Set:
- ll_model_config: Stores all Language Model Configuration
- embed_model_config: Stores all Embedding Model Configuration

- ll_model_enabled: Stores all Enabled Language Models
- embed_model_enabled: Stores all Enabled Embedding Models
"""
# spell-checker:ignore selectbox

import inspect
from time import sleep
from typing import Literal
import urllib.parse

import streamlit as st
from streamlit import session_state as state
from client.utils.st_footer import render_models_footer

import client.utils.api_call as api_call
import client.utils.st_common as st_common

import common.help_text as help_text
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("client.content.config.models")


###################################
# Functions
###################################
def get_models(force: bool = False) -> None:
    """Get Models from API Server"""
    if force or "model_configs" not in state or not state.model_configs:
        try:
            logger.info("Refreshing state.model_configs")
            state.model_configs = api_call.get(endpoint="v1/models")
        except api_call.ApiError as ex:
            logger.error("Unable to populate state.model_configs: %s", ex)
            state.model_configs = {}


@st.cache_data
def get_model_apis(model_type: str = None) -> list:
    """Get list of valid APIs; function for Streamlit caching"""
    response = api_call.get(endpoint="v1/models/api", params={"model_type": model_type})
    return response


def create_model(model: dict) -> None:
    """Add either Language Model or Embed Model"""
    api_call.post(endpoint="v1/models", params={"name": model["name"]}, payload={"json": model})
    st.success(f"Model created: {model['name']}")
    sleep(1)
    st_common.clear_state_key("model_configs")


def patch_model(model: dict) -> None:
    """Update Model Configuration for either Language Models or Embed Models"""
    try:
        _ = api_call.patch(endpoint=f"v1/models/{model['name']}", payload={"json": model})
        st.success(f"Model updated: {model['name']}")
        sleep(1)
        st_common.clear_state_key("model_configs")
    except api_call.ApiError:
        create_model(model)


def delete_model(model_name: str) -> None:
    """Update Model Configuration for either Language Models or Embed Models"""
    api_call.delete(endpoint=f"v1/models/{model_name}")
    st.success(f"Model deleted: {model_name}")
    sleep(1)
    # If deleted model is the set model; unset the user settings
    if state.client_settings["ll_model"]["model"] == model_name:
        state.client_settings["ll_model"]["model"] = None

    st_common.clear_state_key("model_configs")


@st.dialog("Model Configuration", width="large")
def edit_model(model_type: str, action: Literal["add", "edit"], model_name: str = None) -> None:
    """Model Edit Dialog Box"""
    # Initialize our model request
    if action == "edit":
        name = urllib.parse.quote(model_name, safe="")
        model = api_call.get(endpoint=f"v1/models/{name}")
    else:
        model = {"name": "unset", "type": model_type, "api": "unset", "status": "CUSTOM"}
    with st.form("edit_model"):
        model["enabled"] = st.checkbox("Enabled", value=True if action == "add" else model["enabled"])
        model["name"] = st.text_input(
            "Model Name (Required):",
            help=help_text.help_dict["model_name"],
            value=None if model["name"] == "unset" else model["name"],
            key="add_model_name",
            disabled=action == "edit",
        )
        api_values = get_model_apis(model_type)
        api_index = next((i for i, item in enumerate(api_values) if item == model["api"]), None)
        model["api"] = st.selectbox(
            "API (Required):",
            help=help_text.help_dict["model_api"],
            placeholder="-- Choose the Model's API --",
            index=api_index,
            options=api_values,
            key="add_model_api",
            disabled=action == "edit",
        )
        model["url"] = st.text_input(
            "API URL:",
            help=help_text.help_dict["model_api_url"],
            key="add_model_api_url",
            value=model.get("url", ""),
        )
        model["api_key"] = st.text_input(
            "API Key:",
            help=help_text.help_dict["model_api_key"],
            key="add_model_api_key",
            type="password",
            value=model.get("api_key", ""),
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
        button_col_format = st.columns([1.2, 1.4, 6, 1.4])
        action_button, delete_button, _, cancel_button = button_col_format
        try:
            if action == "add" and action_button.form_submit_button(
                label="Add", type="primary", use_container_width=True
            ):
                create_model(model=model)
                st.rerun()
            if action == "edit" and action_button.form_submit_button(
                label="Save", type="primary", use_container_width=True
            ):
                patch_model(model=model)
                st.rerun()
            if action != "add" and delete_button.form_submit_button(
                label="Delete", type="secondary", use_container_width=True
            ):
                delete_model(model_name=model["name"])
                st.rerun()
        except api_call.ApiError as ex:
            st.error(f"Failed to {action} model: {ex}")
        if cancel_button.form_submit_button(label="Cancel", type="secondary"):
            st.rerun()


def render_model_rows(model_type):
    """Render rows of the models"""
    data_col_widths = [0.05, 0.25, 0.2, 0.28, 0.12]
    table_col_format = st.columns(data_col_widths, vertical_alignment="center")
    col1, col2, col3, col4, col5 = table_col_format
    col1.markdown("&#x200B;", help="Active", unsafe_allow_html=True)
    col2.markdown("**<u>Model Name</u>**", unsafe_allow_html=True)
    col3.markdown("**<u>API</u>**", unsafe_allow_html=True)
    col4.markdown("**<u>API Server</u>**", unsafe_allow_html=True)
    col5.markdown("&#x200B;")
    for model in [m for m in state.model_configs if m.get("type") == model_type]:
        model_name = model["name"]
        col1.text_input(
            "Enabled",
            value="✅" if model["enabled"] else "⚪",
            key=f"{model_type}_{model_name}_enabled",
            label_visibility="collapsed",
            disabled=True,
        )
        col2.text_input(
            "Model",
            value=model_name,
            label_visibility="collapsed",
            disabled=True,
        )
        col3.text_input(
            "API",
            value=model["api"],
            key=f"{model_type}_{model_name}_api",
            label_visibility="collapsed",
            disabled=True,
        )
        col4.text_input(
            "Server",
            value=model["url"],
            key=f"{model_type}_{model_name}_server",
            label_visibility="collapsed",
            disabled=True,
        )
        col5.button(
            "Edit",
            on_click=edit_model,
            key=f"{model_type}_{model_name}_edit",
            kwargs=dict(model_type=model_type, action="edit", model_name=model_name),
        )

    if st.button(label="Add", type="primary", key=f"add_{model_type}_model"):
        edit_model(model_type=model_type, action="add")


#############################################################################
# MAIN
#############################################################################
def main() -> None:
    """Streamlit GUI"""
    st.header("Models", divider="red")
    st.write("Update, Add, or Delete model configuration parameters.")
    try:
        get_models()
    except api_call.ApiError:
        st.stop()

    # Table Dimensions

    st.divider()
    st.subheader("Language Models")
    render_model_rows("ll")

    st.divider()
    st.subheader("Embedding Models")
    render_model_rows("embed")

    render_models_footer()


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
