"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore streamlit, selectbox, mult, iloc

import os
from io import BytesIO
from typing import Union
from uuid import uuid4
import pandas as pd

import streamlit as st
from streamlit import session_state as state

from client.content.config.models import get_models
from client.content.config.databases import get_databases
import client.utils.api_call as api_call

import common.help_text as help_text
import common.logging_config as logging_config
from common.schema import ClientIdType, PromptPromptType, PromptNameType

logger = logging_config.logging.getLogger("client.utils.st_common")


#############################################################################
# Common Helpers
#############################################################################
def client_gen_id() -> ClientIdType:
    """Generate a new client ID; can be used to clear history"""
    logger.info("Creating new client identifier")
    return str(uuid4())


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


def switch_prompt(prompt_type: PromptPromptType, prompt_name: PromptNameType) -> None:
    """Auto Switch Prompts when not set to Custom"""
    current_prompt = state["user_settings"]["prompts"][prompt_type]
    if current_prompt != "Custom" and current_prompt != prompt_name:
        state.user_settings["prompts"][prompt_type] = prompt_name
        st.info(f"Prompt Engineering - {prompt_name} Prompt has been set.", icon="ℹ️")


def patch_settings() -> None:
    """Patch user settings on Server"""
    try:
        api_call.patch(
            endpoint="v1/settings",
            payload={"json": state.user_settings},
            params={"client": state.user_settings["client"]},
        )
    except api_call.ApiError as ex:
        logger.error("%s Settings Update failed: %s", state.user_settings["client"], ex)


#############################################################################
# State Helpers
#############################################################################
def clear_state_key(state_key: str) -> None:
    """Generic clear key from state, handles if key isn't in state"""
    state.pop(state_key, None)
    logger.debug("State cleared: %s", state_key)


def update_user_settings(
    user_setting: str,
) -> None:
    """Update user settings"""
    for setting_key, setting_value in state.user_settings[user_setting].items():
        widget_key = f"selected_{user_setting}_{setting_key}"
        widget_value = state.get(widget_key, setting_value)
        if state.get(widget_key, setting_value) != setting_value:
            logger.info("Updating user_settings['%s']['%s'] to %s", user_setting, setting_key, widget_value)
            state.user_settings[user_setting][setting_key] = widget_value
    # Destroying user Client
    clear_state_key("user_client")


def is_db_configured() -> bool:
    """Verify that a database is configured"""
    get_databases()
    return state.database_config[state.user_settings["rag"]["database"]].get("connected")


def set_server_state() -> None:
    """initialize Streamlit Session State"""
    if "server" not in state:
        logger.info("Initializing state.server")
        state.server = {"url": os.getenv("API_SERVER_URL", "http://localhost")}
        state.server["port"] = int(os.getenv("API_SERVER_PORT", "8000"))
        state.server["key"] = os.getenv("API_SERVER_KEY")
        logger.info("Server State: %s", state.server)


#############################################################################
# Sidebar
#############################################################################
def history_sidebar() -> None:
    """History Sidebar"""
    st.sidebar.subheader("History and Context", divider="red")
    checkbox_col, button_col = st.sidebar.columns(2)
    chat_history_enable = checkbox_col.checkbox(
        "Enable?",
        value=True,
        key="selected_ll_model_chat_history",
        on_change=update_user_settings("ll_model"),
    )
    if button_col.button("Clear", disabled=not chat_history_enable, use_container_width=True):
        # Establish a new thread
        state.user_settings["client"] = client_gen_id()
        clear_state_key("user_client")


#####################################################
# Large Language Options
#####################################################
def ll_sidebar() -> None:
    """Language Model Sidebar"""
    st.sidebar.subheader("Language Model Parameters", divider="red")
    # If no user_settings defined for , set to the first available_ll_model
    if state.user_settings["ll_model"].get("model") is None:
        default_ll_model = list(state.ll_model_enabled.keys())[0]
        defaults = {
            "model": default_ll_model,
            "temperature": state.ll_model_enabled[default_ll_model]["temperature"],
            "frequency_penalty": state.ll_model_enabled[default_ll_model]["frequency_penalty"],
            "max_completion_tokens": state.ll_model_enabled[default_ll_model]["max_completion_tokens"],
        }
        state.user_settings["ll_model"].update(defaults)

    ll_idx = list(state.ll_model_enabled.keys()).index(state.user_settings["ll_model"]["model"])
    selected_model = st.sidebar.selectbox(
        "Chat model:",
        options=list(state.ll_model_enabled.keys()),
        index=ll_idx,
        key="selected_ll_model_model",
        on_change=update_user_settings("ll_model"),
    )

    # Temperature
    temperature = state.ll_model_enabled[selected_model]["temperature"]
    user_temperature = state.user_settings["ll_model"]["temperature"]
    st.sidebar.slider(
        f"Temperature (Default: {temperature}):",
        help=help_text.help_dict["temperature"],
        value=user_temperature if user_temperature is not None else temperature,
        min_value=0.0,
        max_value=2.0,
        key="selected_ll_model_temperature",
        on_change=update_user_settings("ll_model"),
    )

    # Completion Tokens
    max_completion_tokens = state.ll_model_enabled[selected_model]["max_completion_tokens"]
    user_completion_tokens = state.user_settings["ll_model"]["max_completion_tokens"]
    st.sidebar.slider(
        f"Maximum Tokens (Default: {max_completion_tokens}):",
        help=help_text.help_dict["max_completion_tokens"],
        value=(
            user_completion_tokens
            if user_completion_tokens is not None and user_completion_tokens <= max_completion_tokens
            else max_completion_tokens
        ),
        min_value=1,
        max_value=max_completion_tokens,
        key="selected_ll_model_max_completion_tokens",
        on_change=update_user_settings("ll_model"),
    )

    # Top P
    st.sidebar.slider(
        "Top P (Default: 1.0):",
        help=help_text.help_dict["top_p"],
        value=state.user_settings["ll_model"]["top_p"],
        min_value=0.0,
        max_value=1.0,
        key="selected_ll_model_top_p",
        on_change=update_user_settings("ll_model"),
    )

    # Frequency Penalty
    frequency_penalty = state.ll_model_enabled[selected_model]["frequency_penalty"]
    user_frequency_penalty = state.user_settings["ll_model"]["frequency_penalty"]
    st.sidebar.slider(
        f"Frequency penalty (Default: {frequency_penalty}):",
        help=help_text.help_dict["frequency_penalty"],
        value=user_frequency_penalty if user_frequency_penalty is not None else frequency_penalty,
        min_value=-2.0,
        max_value=2.0,
        key="selected_ll_model_frequency_penalty",
        on_change=update_user_settings("ll_model"),
    )

    # Presence Penalty
    st.sidebar.slider(
        "Presence penalty (Default: 0.0):",
        help=help_text.help_dict["presence_penalty"],
        value=state.user_settings["ll_model"]["presence_penalty"],
        min_value=-2.0,
        max_value=2.0,
        key="selected_ll_model_presence_penalty",
        on_change=update_user_settings("ll_model"),
    )


#####################################################
# RAG Options
#####################################################
def rag_sidebar() -> None:
    """RAG Sidebar Settings, conditional if Database/Embeddings are configured"""
    st.sidebar.subheader("Retrieval Augmented Generation", divider="red")
    get_models(model_type="embed")
    available_embed_models = list(state.embed_model_enabled.keys())
    if not available_embed_models:
        logger.debug("RAG Disabled (no Embedding Models)")
        st.warning("No embedding models are configured and/or enabled. Disabling RAG.", icon="⚠️")
        disable_rag = True
    else:
        disable_rag = not is_db_configured()

    if disable_rag:
        logger.debug("RAG Disabled (Database not configured)")
        st.warning("Database is not configured. Disabling RAG.", icon="⚠️")
        state.user_settings["rag"]["rag_enabled"] = False
        switch_prompt("sys", "Basic Example")
    elif not state.database_config[state.user_settings["rag"]["database"]].get("vector_stores"):
        logger.debug("RAG Disabled (Database has no vector stores.)")
        st.warning("Database has no Vector Stores. Disabling RAG.", icon="⚠️")
        state.user_settings["rag"]["rag_enabled"] = False
        switch_prompt("sys", "Basic Example")
        disable_rag = True

    rag_enabled = st.sidebar.checkbox(
        "Enable RAG?",
        help=help_text.help_dict["rag"],
        value=state.user_settings["rag"]["rag_enabled"],
        disabled=disable_rag,
        key="selected_rag_rag_enabled",
        on_change=update_user_settings("rag"),
    )

    if rag_enabled:
        switch_prompt("sys", "RAG Example")
        ##########################
        # Search
        ##########################
        # TODO(gotsysdba) "Similarity Score Threshold" currently raises NotImplementedError
        # rag_search_type_list =
        # ["Similarity", "Similarity Score Threshold", "Maximal Marginal Relevance"]
        rag_search_type_list = ["Similarity", "Maximal Marginal Relevance"]
        rag_search_type = st.sidebar.selectbox(
            "Search Type:",
            rag_search_type_list,
            index=rag_search_type_list.index(state.user_settings["rag"]["search_type"]),
            key="selected_rag_search_type",
            on_change=update_user_settings("rag"),
        )
        st.sidebar.number_input(
            "Top K:",
            help=help_text.help_dict["top_k"],
            value=state.user_settings["rag"]["top_k"],
            min_value=1,
            max_value=10000,
            key="selected_rag_top_k",
            on_change=update_user_settings("rag"),
        )
        if rag_search_type == "Similarity Score Threshold":
            st.sidebar.slider(
                "Minimum Relevance Threshold:",
                help=help_text.help_dict["score_threshold"],
                value=state.user_settings["rag"]["score_threshold"],
                min_value=0.0,
                max_value=1.0,
                step=0.1,
                key="selected_rag_score_threshold",
                on_change=update_user_settings("rag"),
            )
        if rag_search_type == "Maximal Marginal Relevance":
            st.sidebar.number_input(
                "Fetch K:",
                help=help_text.help_dict["fetch_k"],
                value=state.user_settings["rag"]["fetch_k"],
                min_value=1,
                max_value=10000,
                key="selected_rag_fetch_k",
                on_change=update_user_settings("rag"),
            )
            st.sidebar.slider(
                "Degree of Diversity:",
                help=help_text.help_dict["lambda_mult"],
                value=state.user_settings["rag"]["lambda_mult"],
                min_value=0.0,
                max_value=1.0,
                step=0.1,
                key="selected_rag_lambda_mult",
                on_change=update_user_settings("rag"),
            )

        ##########################
        # Vector Store
        ##########################
        st.sidebar.subheader("Vector Store", divider="red")
        # Create a DataFrame of all database vector storage tables
        vs_df = pd.DataFrame(state.database_config[state.user_settings["rag"]["database"]].get("vector_stores"))

        def vs_reset() -> None:
            """Reset Vector Store Selections"""
            for key in state["user_settings"]["rag"]:
                if key in (
                    "model",
                    "chunk_size",
                    "chunk_overlap",
                    "distance_metric",
                    "vector_store",
                    "alias",
                    "index_type",
                ):
                    clear_state_key(f"selected_rag_{key}")
                    state["user_settings"]["rag"][key] = ""

        def vs_gen_selectbox(label, options, key):
            """Handle selectbox with auto-setting for a single unique value"""
            valid_options = [option for option in options if option != ""]
            if not valid_options:  # Disable the selectbox if no valid options are available
                disabled = True
                selected_value = ""
            else:
                disabled = False
                if len(valid_options) == 1:  # Pre-select if only one unique option
                    selected_value = valid_options[0]
                    logger.debug("Defaulting %s to %s", key, selected_value)
                else:
                    selected_value = state["user_settings"]["rag"][key.removeprefix("selected_rag_")] or ""
                    logger.debug("User selected %s to %s", key, selected_value)
            return st.sidebar.selectbox(
                label,
                options=[""] + valid_options,
                key=key,
                index=([""] + valid_options).index(selected_value),
                disabled=disabled,
            )

        def update_filtered_df():
            """Dynamically update filtered_df based on selected filters"""
            filtered = vs_df.copy()
            # Remove vector stores where the model is not enabled
            filtered = vs_df[vs_df["model"].isin(state["embed_model_enabled"].keys())]
            if st.session_state.get("selected_rag_alias"):
                filtered = filtered[filtered["alias"] == st.session_state["selected_rag_alias"]]
            if st.session_state.get("selected_rag_model"):
                filtered = filtered[filtered["model"] == st.session_state["selected_rag_model"]]
            if st.session_state.get("selected_rag_chunk_size"):
                filtered = filtered[filtered["chunk_size"] == st.session_state["selected_rag_chunk_size"]]
            if st.session_state.get("selected_rag_chunk_overlap"):
                filtered = filtered[filtered["chunk_overlap"] == st.session_state["selected_rag_chunk_overlap"]]
            if st.session_state.get("selected_rag_distance_metric"):
                filtered = filtered[filtered["distance_metric"] == st.session_state["selected_rag_distance_metric"]]
            if st.session_state.get("selected_rag_index_type"):
                filtered = filtered[filtered["index_type"] == st.session_state["selected_rag_index_type"]]
            return filtered

        # Initialize filtered options
        filtered_df = update_filtered_df()

        # Render selectbox with updated options
        alias = vs_gen_selectbox("Select Alias:", filtered_df["alias"].unique().tolist(), "selected_rag_alias")
        embed_model = vs_gen_selectbox("Select Model:", filtered_df["model"].unique().tolist(), "selected_rag_model")
        chunk_size = vs_gen_selectbox(
            "Select Chunk Size:", filtered_df["chunk_size"].unique().tolist(), "selected_rag_chunk_size"
        )
        chunk_overlap = vs_gen_selectbox(
            "Select Chunk Overlap:", filtered_df["chunk_overlap"].unique().tolist(), "selected_rag_chunk_overlap"
        )
        distance_metric = vs_gen_selectbox(
            "Select Distance Metric:", filtered_df["distance_metric"].unique().tolist(), "selected_rag_distance_metric"
        )
        index_type = vs_gen_selectbox(
            "Select Index Type:", filtered_df["index_type"].unique().tolist(), "selected_rag_index_type"
        )

        if all([alias, embed_model, chunk_size, chunk_overlap, distance_metric, index_type]):
            vs = filtered_df["vector_store"].iloc[0]
            state.user_settings["rag"]["vector_store"] = vs
            state.user_settings["rag"]["alias"] = alias
            state.user_settings["rag"]["model"] = embed_model
            state.user_settings["rag"]["chunk_size"] = chunk_size
            state.user_settings["rag"]["chunk_overlap"] = chunk_overlap
            state.user_settings["rag"]["distance_metric"] = distance_metric
            state.user_settings["rag"]["index_type"] = index_type
        else:
            st.error("Please select Vector Store options or disable RAG to continue.", icon="❌")
            state.enable_client = False

        # Reset button
        st.sidebar.button("Reset", type="primary", on_click=vs_reset)
    else:
        switch_prompt("sys", "Basic Example")
