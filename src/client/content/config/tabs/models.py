"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes a web interface for model configuration using Streamlit (`st`).

Session States Set:
- model_configs: Stores all Model Configurations
"""
# spell-checker:ignore selectbox

from time import sleep
from typing import Literal, Any
import urllib.parse

import streamlit as st
from streamlit import session_state as state

from client.utils import api_call, st_common
from common import logging_config, help_text

logger = logging_config.logging.getLogger("client.content.config.tabs.models")


###################################
# Functions
###################################
def clear_client_models(model_provider: str, model_id: str) -> None:
    """Clear selected models from client settings if modified"""
    model_keys = [
        ("ll_model", "model"),
        ("testbed", "judge_model"),
        ("testbed", "qa_ll_model"),
        ("testbed", "qa_embed_model"),
    ]
    for section, key in model_keys:
        if state.client_settings[section][key] == f"{model_provider}/{model_id}":
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


# @st.cache_data(show_spinner="Retrieving Supported Models")
def get_supported_models(model_type: str) -> list[dict[str, Any]]:
    """Get list of supported providers; function for Streamlit caching"""
    response = api_call.get(endpoint="v1/models/supported", params={"model_type": model_type})
    return response


def create_model(model: dict) -> None:
    """Add either Language Model or Embed Model"""
    _ = api_call.post(endpoint="v1/models", payload={"json": model})
    st.success(f"Model created: {model['provider']}/{model['id']}")


def patch_model(model: dict) -> None:
    """Update Model Configuration for either Language Models or Embed Models"""
    _ = api_call.patch(endpoint=f"v1/models/{model['provider']}/{model['id']}", payload={"json": model})
    st.success(f"Model updated: {model['id']}")
    # If updated model is the set model and not enabled: unset the user settings
    if not model["enabled"]:
        clear_client_models(model["provider"], model["id"])


def delete_model(model_provider: str, model_id: str) -> None:
    """Update Model Configuration for either Language Models or Embed Models"""
    api_call.delete(endpoint=f"v1/models/{model_provider}/{model_id}")
    st.success(f"Model deleted: {model_provider}/{model_id}")
    sleep(1)
    # If deleted model is the set model; unset the user settings
    clear_client_models(model_provider, model_id)


def _initialize_model(action: str, model_type: str, model_id: str = None, model_provider: str = None) -> dict:
    """Initialize model configuration based on action type"""
    if action == "edit":
        quoted_model_id = urllib.parse.quote(model_id, safe="")
        model = api_call.get(endpoint=f"v1/models/{model_provider}/{quoted_model_id}")
    else:
        model = {"id": "unset", "type": model_type, "provider": "unset", "status": "CUSTOM"}

    if action == "add":
        model["enabled"] = True
    else:
        model["enabled"] = st.checkbox("Enabled", value=True if action == "add" else model["enabled"])

    return model


def _render_provider_selection(model: dict, supported_models: list, action: str) -> tuple[dict, list, bool]:
    """Render provider selection UI and return updated model, provider models, and OCI flag"""
    provider_index = next(
        (i for i, item in enumerate(supported_models) if item["provider"] == model["provider"]), None
    )
    disable_for_oci = model["provider"] == "oci"

    model["provider"] = st.selectbox(
        "Provider (Required):",
        help=help_text.help_dict["model_provider"],
        placeholder="-- Choose the Model's Provider --",
        index=provider_index,
        options=[item["provider"] for item in supported_models],
        key="add_model_provider",
        disabled=action == "edit",
    )

    # Get models for the selected provider
    provider_models = []
    for item in supported_models:
        if item["provider"] == model["provider"]:
            provider_models = item["models"]
            break

    return model, provider_models, disable_for_oci


def _render_model_selection(model: dict, provider_models: list, action: str) -> dict:
    """Render model selection UI and return updated model"""
    model_keys = [m["key"] for m in provider_models]
    model_index = next((i for i, key in enumerate(model_keys) if key == model["id"]), None)

    model["id"] = st.selectbox(
        "Model (Required):",
        help=help_text.help_dict["model_id"],
        placeholder="-- Choose or Enter Model Name --",
        index=model_index,
        options=model_keys,
        key="add_model_id",
        accept_new_options=True,
        disabled=action == "edit" or not model["provider"],
    )

    return model


def _render_api_configuration(model: dict, provider_models: list, disable_for_oci: bool) -> dict:
    """Render API configuration UI and return updated model"""
    api_base = next(
        (m.get("api_base", "") for m in provider_models if m.get("key") == model["id"]),
        model.get("api_base", "")
    )

    model["api_base"] = st.text_input(
        "Provider URL:",
        help=help_text.help_dict["model_url"],
        key="add_model_url",
        value=api_base,
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

    return model


def _render_model_specific_config(model: dict, model_type: str, provider_models: list) -> dict:
    """Render model type specific configuration and return updated model"""
    if model_type == "ll":
        context_length = next(
            (m.get("max_input_tokens", 8192) for m in provider_models if m.get("key") == model["id"]),
            model.get("max_input_tokens", 8192),
        )
        model["context_length"] = st.number_input(
            "Context Length:",
            help=help_text.help_dict["context_length"],
            min_value=0,
            key="add_model_context_length",
            value=context_length,
        )

        max_completion_tokens = next(
            (m.get("max_output_tokens", 4096) for m in provider_models if m.get("key") == model["id"]),
            model.get("max_output_tokens", 4096),
        )
        model["max_completion_tokens"] = st.number_input(
            "Max Completion Tokens:",
            help=help_text.help_dict["max_completion_tokens"],
            min_value=1,
            key="add_model_max_completion_tokens",
            value=max_completion_tokens,
        )
    else:
        output_vector_size = next(
            (m.get("output_vector_size", 8191) for m in provider_models if m.get("key") == model["id"]),
            model.get("output_vector_size", 8191),
        )
        model["max_chunk_size"] = st.number_input(
            "Max Chunk Size:",
            help=help_text.help_dict["chunk_size"],
            min_value=0,
            key="add_model_max_chunk_size",
            value=output_vector_size,
        )

    return model


def _handle_form_submission(model: dict, action: str) -> bool:
    """Handle form submission and return True if successful"""
    button_col_format = st.columns([1.2, 1.4, 6, 1.4])
    action_button, delete_button, _, cancel_button = button_col_format

    try:
        if action == "add" and action_button.button(label="Add", type="primary", width="stretch"):
            create_model(model=model)
            return True
        if action == "edit" and action_button.button(label="Save", type="primary", width="stretch"):
            patch_model(model=model)
            return True
        if action != "add" and delete_button.button(label="Delete", type="secondary", width="stretch"):
            delete_model(model_provider=model["provider"], model_id=model["id"])
            return True
    except api_call.ApiError as ex:
        st.error(f"Failed to {action} model: {ex}")

    if cancel_button.button(label="Cancel", type="secondary"):
        st_common.clear_state_key("model_configs")
        st.rerun()

    return False


@st.dialog("Model Configuration", width="large")
def edit_model(
    model_type: str, action: Literal["add", "edit"], model_id: str = None, model_provider: str = None
) -> None:
    """Model Edit Dialog Box"""
    model = _initialize_model(action, model_type, model_id, model_provider)
    supported_models = get_supported_models(model_type)

    model, provider_models, disable_for_oci = _render_provider_selection(model, supported_models, action)
    model = _render_model_selection(model, provider_models, action)
    model = _render_api_configuration(model, provider_models, disable_for_oci)
    model = _render_model_specific_config(model, model_type, provider_models)

    if _handle_form_submission(model, action):
        sleep(1)
        st_common.clear_state_key("model_configs")
        st.rerun()


def render_model_rows(model_type: str) -> None:
    """Render rows of the models"""
    data_col_widths = [0.08, 0.42, 0.28, 0.12]
    table_col_format = st.columns(data_col_widths, vertical_alignment="center")
    col1, col2, col3, col4 = table_col_format
    col1.markdown("&#x200B;", help="Active", unsafe_allow_html=True)
    col2.markdown("**<u>Model</u>**", unsafe_allow_html=True)
    col3.markdown("**<u>Provider URL</u>**", unsafe_allow_html=True)
    col4.markdown("&#x200B;")
    for model in [m for m in state.model_configs if m.get("type") == model_type]:
        model_id = model["id"]
        model_provider = model["provider"]
        col1.text_input(
            "Enabled",
            value=st_common.bool_to_emoji(model["enabled"]),
            key=f"{model_type}_{model_provider}_{model_id}_enabled",
            label_visibility="collapsed",
            disabled=True,
        )
        col2.text_input(
            "Model",
            value=f"{model_provider}/{model_id}",
            key=f"{model_type}_{model_provider}_{model_id}",
            label_visibility="collapsed",
            disabled=True,
        )
        col3.text_input(
            "Server",
            value=model["api_base"],
            key=f"{model_type}_{model_provider}_{model_id}_api_base",
            label_visibility="collapsed",
            disabled=True,
        )
        col4.button(
            "Edit",
            on_click=edit_model,
            key=f"{model_type}_{model_provider}_{model_id}_edit",
            kwargs={
                "model_type": model_type,
                "action": "edit",
                "model_id": model_id,
                "model_provider": model_provider,
            },
        )

    if st.button(label="Add", type="primary", key=f"add_{model_type}_model"):
        edit_model(model_type=model_type, action="add")


#############################################################################
# MAIN
#############################################################################
def display_models() -> None:
    """Streamlit GUI"""
    st.title("Models")
    st.write("Update, Add, or Delete model configuration parameters.")
    try:
        get_models()
    except api_call.ApiError:
        st.stop()

    st.divider()
    st.header("Language Models")
    render_model_rows("ll")

    st.divider()
    st.header("Embedding Models")
    render_model_rows("embed")


if __name__ == "__main__":
    display_models()
