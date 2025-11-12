"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore isin mult selectbox

from io import BytesIO
from typing import Any, Union

import streamlit as st
from streamlit import session_state as state

from client.utils import api_call
from common import logging_config, help_text
from common.schema import PromptPromptType, PromptNameType

logger = logging_config.logging.getLogger("client.utils.st_common")


#############################################################################
# State Helpers
#############################################################################
def clear_state_key(state_key: str) -> None:
    """Generic clear key from state, handles if key isn't in state"""
    state.pop(state_key, None)
    logger.debug("State cleared: %s", state_key)


def state_configs_lookup(state_configs_name: str, key: str, section: str = None) -> dict[str, dict[str, Any]]:
    """Convert state.<state_configs_name> into a lookup based on key"""
    configs = getattr(state, state_configs_name)
    if section:
        configs = configs.get(section, [])
    return {config[key]: config for config in configs if key in config}


#############################################################################
# Model Helpers
#############################################################################
def enabled_models_lookup(model_type: str) -> dict[str, dict[str, Any]]:
    """Create a lookup of enabled `type` models"""
    all_models = state_configs_lookup("model_configs", "id")
    enabled_models = {
        f"{config.get('provider')}/{id}": config
        for id, config in all_models.items()
        if config.get("type") == model_type and config.get("enabled") is True
    }
    return enabled_models


#############################################################################
# Common Helpers
#############################################################################
def bool_to_emoji(value):
    "Return an Emoji for Bools"
    return "✅" if value else "⚪"


def local_file_payload(uploaded_files: Union[BytesIO, list[BytesIO]]) -> list:
    """Upload Single file from Streamlit to the Server"""
    # If it's a single file, convert it to a list for consistent processing
    if isinstance(uploaded_files, BytesIO):
        uploaded_files = [uploaded_files]

    # Ensure we are not processing duplicates
    seen_file = set()
    files = [
        ("files", (file.name, file.getvalue(), file.type))
        for file in uploaded_files
        if file.name not in seen_file and not seen_file.add(file.name)
    ]
    return files


def patch_settings() -> None:
    """Patch user settings on Server"""
    try:
        _ = api_call.patch(
            endpoint="v1/settings",
            payload={"json": state.client_settings},
            params={"client": state.client_settings["client"]},
            toast=False,
        )
    except api_call.ApiError as ex:
        logger.error("%s Settings Update failed: %s", state.client_settings["client"], ex)


#############################################################################
# State Helpers
#############################################################################


def update_client_settings(user_setting: str) -> None:
    """Update user settings"""
    for setting_key, setting_value in state.client_settings[user_setting].items():
        widget_key = f"selected_{user_setting}_{setting_key}"
        widget_value = state.get(widget_key, setting_value)
        if state.get(widget_key, setting_value) != setting_value:
            logger.info("Updating client_settings['%s']['%s'] to %s", user_setting, setting_key, widget_value)
            state.client_settings[user_setting][setting_key] = widget_value
    # Destroying user Client
    clear_state_key("user_client")


def is_db_configured() -> bool:
    """Verify that a database is configured"""
    return next(
        (
            config.get("connected")
            for config in state.database_configs
            if config.get("name") == state.client_settings.get("database", {}).get("alias")
        ),
        False,
    )


#############################################################################
# Sidebar
#############################################################################
def history_sidebar() -> None:
    """History Sidebar"""
    st.sidebar.subheader("History and Context", divider="red")
    checkbox_col, button_col = st.sidebar.columns(2)
    chat_history_enable = checkbox_col.checkbox(
        "Enable?",
        value=state.client_settings["ll_model"]["chat_history"],
        key="selected_ll_model_chat_history",
        on_change=update_client_settings("ll_model"),
    )
    if button_col.button("Clear", disabled=not chat_history_enable, width="stretch"):
        # Clean out history
        try:
            api_call.patch(endpoint="v1/chat/history")
        except api_call.ApiError as ex:
            logger.error("Clearing Chat History for %s failed: %s", state.client_settings["client"], ex)
        clear_state_key("user_client")


#####################################################
# Large Language Options
#####################################################
def ll_sidebar() -> None:
    """Language Model Sidebar"""
    st.sidebar.subheader("Language Model Parameters", divider="red")
    # If no client_settings defined for model, set to the first available_ll_model
    ll_models_enabled = enabled_models_lookup("ll")
    if state.client_settings["ll_model"].get("model") is None:
        default_ll_model = list(ll_models_enabled.keys())[0]
        defaults = {
            "model": default_ll_model,
            "temperature": ll_models_enabled[default_ll_model]["temperature"],
            "frequency_penalty": ll_models_enabled[default_ll_model]["frequency_penalty"],
            "max_tokens": ll_models_enabled[default_ll_model]["max_tokens"],
        }
        state.client_settings["ll_model"].update(defaults)

    selected_model = state.client_settings["ll_model"]["model"]
    ll_idx = list(ll_models_enabled.keys()).index(selected_model)
    selected_model = st.sidebar.selectbox(
        "Chat model:",
        options=list(ll_models_enabled.keys()),
        index=ll_idx,
        key="selected_ll_model_model",
        on_change=update_client_settings("ll_model"),
    )

    # Temperature
    temperature = ll_models_enabled[selected_model]["temperature"]
    user_temperature = state.client_settings["ll_model"]["temperature"]
    max_value = 2.0
    st.sidebar.slider(
        f"Temperature (Default: {temperature}):",
        help=help_text.help_dict["temperature"],
        value=user_temperature if user_temperature is not None else temperature,
        min_value=0.0,
        max_value=max_value,
        key="selected_ll_model_temperature",
        on_change=update_client_settings("ll_model"),
    )

    # Completion Tokens
    max_tokens = ll_models_enabled[selected_model]["max_tokens"]
    user_completion_tokens = state.client_settings["ll_model"]["max_tokens"]
    st.sidebar.slider(
        "Maximum Output Tokens:",
        help=help_text.help_dict["max_tokens"],
        value=(
            user_completion_tokens
            if user_completion_tokens is not None and user_completion_tokens <= max_tokens
            else max_tokens
        ),
        min_value=1,
        max_value=max_tokens,
        key="selected_ll_model_max_tokens",
        on_change=update_client_settings("ll_model"),
    )

    # Top P
    st.sidebar.slider(
        "Top P (Default: 1.0):",
        help=help_text.help_dict["top_p"],
        value=state.client_settings["ll_model"]["top_p"],
        min_value=0.0,
        max_value=1.0,
        key="selected_ll_model_top_p",
        on_change=update_client_settings("ll_model"),
    )

    # Frequency Penalty
    if "xai" not in state.client_settings["ll_model"]["model"]:
        frequency_penalty = ll_models_enabled[selected_model]["frequency_penalty"]
        user_frequency_penalty = state.client_settings["ll_model"]["frequency_penalty"]
        st.sidebar.slider(
            f"Frequency penalty (Default: {frequency_penalty}):",
            help=help_text.help_dict["frequency_penalty"],
            value=user_frequency_penalty if user_frequency_penalty is not None else frequency_penalty,
            min_value=-2.0,
            max_value=2.0,
            key="selected_ll_model_frequency_penalty",
            on_change=update_client_settings("ll_model"),
        )

        # Presence Penalty
        st.sidebar.slider(
            "Presence penalty (Default: 0.0):",
            help=help_text.help_dict["presence_penalty"],
            value=state.client_settings["ll_model"]["presence_penalty"],
            min_value=-2.0,
            max_value=2.0,
            key="selected_ll_model_presence_penalty",
            on_change=update_client_settings("ll_model"),
        )


#####################################################
# Tools Options
#####################################################
def tools_sidebar() -> None:
    """Sidebar Settings"""

    state.tool_box = []
    if not is_db_configured():
        logger.debug("Vector Search/NL2SQL Disabled (Database not configured)")
        st.warning("Database is not configured. Disabling Vector Search and NL2SQL tools.", icon="⚠️")
    else:
        # Add tools to tool_box
        state.tool_box = ["Vector Search", "NL2SQL"]

        # Client Settings
        db_alias = state.client_settings.get("database", {}).get("alias")

        # Lookups
        database_lookup = state_configs_lookup("database_configs", "name")

        # Vector Search Requirements
        embed_models_enabled = enabled_models_lookup("embed")

        def _disable_vector_search(reason):
            """Disable Vector Store, and make sure prompt is reset"""
            logger.debug("Vector Search Disabled (%s)", reason)
            st.warning(f"{reason}. Disabling Vector Search.", icon="⚠️")
            state.client_settings["tools_enabled"] = [
                t for t in state.client_settings["tools_enabled"] if t != "Vector Search"
            ]
            state.tool_box = [t for t in state.tool_box if t != "Vector Search"]

        if not embed_models_enabled:
            _disable_vector_search("No embedding models are configured and/or enabled.")
        elif not database_lookup[db_alias].get("vector_stores"):
            _disable_vector_search("Database has no vector stores")

        if len(state.tool_box) > 1:
            st.sidebar.subheader("Toolkit", divider="red")
            st.sidebar.multiselect(
                "Tool Selection",
                default=state.client_settings["tools_enabled"],
                options=state.tool_box,
                placeholder="Language Model Only",
                label_visibility="collapsed",
                key="selected_tools",
            )
            state.client_settings["tools_enabled"] = state.selected_tools


#####################################################
# Vector Search Options
#####################################################
def _render_vector_search_options(vector_search_type: str) -> None:
    """Render vector search parameter controls based on search type."""
    st.sidebar.number_input(
        "Top K:",
        help=help_text.help_dict["top_k"],
        value=state.client_settings["vector_search"]["top_k"],
        min_value=1,
        max_value=10000,
        key="selected_vector_search_top_k",
        on_change=update_client_settings("vector_search"),
    )
    if vector_search_type == "Similarity Score Threshold":
        st.sidebar.slider(
            "Minimum Relevance Threshold:",
            help=help_text.help_dict["score_threshold"],
            value=state.client_settings["vector_search"]["score_threshold"],
            min_value=0.0,
            max_value=1.0,
            step=0.1,
            key="selected_vector_search_score_threshold",
            on_change=update_client_settings("vector_search"),
        )
    if vector_search_type == "Maximal Marginal Relevance":
        st.sidebar.number_input(
            "Fetch K:",
            help=help_text.help_dict["fetch_k"],
            value=state.client_settings["vector_search"]["fetch_k"],
            min_value=1,
            max_value=10000,
            key="selected_vector_search_fetch_k",
            on_change=update_client_settings("vector_search"),
        )
        st.sidebar.slider(
            "Degree of Diversity:",
            help=help_text.help_dict["lambda_mult"],
            value=state.client_settings["vector_search"]["lambda_mult"],
            min_value=0.0,
            max_value=1.0,
            step=0.1,
            key="selected_vector_search_lambda_mult",
            on_change=update_client_settings("vector_search"),
        )


def vector_search_sidebar() -> None:
    """Vector Search Sidebar Settings, conditional if Database/Embeddings are configured"""
    if state.client_settings["vector_search"]["enabled"]:
        st.sidebar.subheader("Vector Search", divider="red")

        # Search Type Selection
        vector_search_type_list = ["Similarity", "Maximal Marginal Relevance"]
        vector_search_type = st.sidebar.selectbox(
            "Search Type:",
            vector_search_type_list,
            index=vector_search_type_list.index(state.client_settings["vector_search"]["search_type"]),
            key="selected_vector_search_search_type",
            on_change=update_client_settings("vector_search"),
        )

        # Render search options based on type
        _render_vector_search_options(vector_search_type)
