"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore streamlit, selectbox, mult, iloc, selectai, isin

from io import BytesIO
from typing import Any, Union, get_args
import pandas as pd

import streamlit as st
from streamlit import session_state as state

import client.utils.api_call as api_call

import common.help_text as help_text
import common.logging_config as logging_config
from common.schema import PromptPromptType, PromptNameType, SelectAISettings, ClientIdType

# Import the MCP initialization function
try:
    from launch_server import initialize_mcp_engine_with_model
except ImportError:
    initialize_mcp_engine_with_model = None

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
        id: config
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


def switch_prompt(prompt_type: PromptPromptType, prompt_name: PromptNameType) -> None:
    """Auto Switch Prompts when not set to Custom"""
    current_prompt = state.client_settings["prompts"][prompt_type]
    if current_prompt != "Custom" and current_prompt != prompt_name:
        state.client_settings["prompts"][prompt_type] = prompt_name
        st.info(f"Prompt Engineering - {prompt_name} Prompt has been set.", icon="ℹ️")


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
            if config.get("name") == state.client_settings["database"]["alias"]
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
    if button_col.button("Clear", disabled=not chat_history_enable, use_container_width=True):
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
            "max_completion_tokens": ll_models_enabled[default_ll_model]["max_completion_tokens"],
        }
        state.client_settings["ll_model"].update(defaults)

    selected_model = state.client_settings["ll_model"]["model"]
    ll_idx = list(ll_models_enabled.keys()).index(selected_model)
    if not state.client_settings["selectai"]["enabled"]:
        # Store the previous model to detect changes
        previous_model = selected_model
        selected_model = st.sidebar.selectbox(
            "Chat model:",
            options=list(ll_models_enabled.keys()),
            index=ll_idx,
            key="selected_ll_model_model",
            on_change=update_client_settings("ll_model"),
            disabled=state.client_settings["selectai"]["enabled"],
        )

        # If the model has changed, reinitialize the MCP engine
        if selected_model != previous_model and initialize_mcp_engine_with_model:
            try:
                # Instead of creating a new event loop, we'll set a flag to indicate
                # that the MCP engine needs to be reinitialized
                state.mcp_needs_reinit = selected_model
                logger.info(f"MCP engine marked for reinitialization with model: {selected_model}")
            except Exception as e:
                logger.error(f"Failed to mark MCP engine for reinitialization with model {selected_model}: {e}")

    # Temperature
    temperature = ll_models_enabled[selected_model]["temperature"]
    user_temperature = state.client_settings["ll_model"]["temperature"]
    max_value = 2.0
    if state.client_settings["selectai"]["enabled"]:
        user_temperature = 1.0
        max_value = 1.0
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
    max_completion_tokens = ll_models_enabled[selected_model]["max_completion_tokens"]
    user_completion_tokens = state.client_settings["ll_model"]["max_completion_tokens"]
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
        on_change=update_client_settings("ll_model"),
    )

    # Top P
    if not state.client_settings["selectai"]["enabled"]:
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
    """SelectAI Sidebar Settings, conditional if all sorts of bs setup"""

    def update_set_tool():
        """Update user settings as to which tool is being used"""
        state.client_settings["vector_search"]["enabled"] = state.selected_tool == "Vector Search"
        state.client_settings["selectai"]["enabled"] = state.selected_tool == "SelectAI"

    disable_selectai = not is_db_configured()
    disable_vector_search = not is_db_configured()

    if disable_selectai and disable_vector_search:
        logger.debug("Vector Search/SelectAI Disabled (Database not configured)")
        st.warning("Database is not configured. Disabling Vector Search and SelectAI tools.", icon="⚠️")
        state.client_settings["selectai"]["enabled"] = False
        state.client_settings["vector_search"]["enabled"] = False
        switch_prompt("sys", "Basic Example")
    else:
        # Client Settings
        db_alias = state.client_settings["database"]["alias"]
        oci_auth_profile = state.client_settings["oci"]["auth_profile"]

        # Lookups
        oci_lookup = state_configs_lookup("oci_configs", "auth_profile")
        database_lookup = state_configs_lookup("database_configs", "name")

        tools = [
            ("LLM Only", "Do not use tools", False),
            ("SelectAI", "Use AI with Structured Data", disable_selectai),
            ("Vector Search", "Use AI with Unstructured Data", disable_vector_search),
        ]

        # SelectAI Requirements
        if not oci_lookup[oci_auth_profile]["namespace"]:
            logger.debug("SelectAI Disabled (OCI not configured.)")
            st.warning("OCI is not fully configured.  Disabling SelectAI.", icon="⚠️")
            tools = [t for t in tools if t[0] != "SelectAI"]
        elif not database_lookup[db_alias]["selectai"]:
            logger.debug("SelectAI Disabled (Database not Compatible.)")
            st.warning("Database not SelectAI Compatible.  Disabling SelectAI.", icon="⚠️")
            tools = [t for t in tools if t[0] != "SelectAI"]
        elif len(database_lookup[db_alias]["selectai_profiles"]) == 0:
            logger.debug("SelectAI Disabled (No profiles found.)")
            st.warning("Database has no SelectAI Profiles.  Disabling SelectAI.", icon="⚠️")
            tools = [t for t in tools if t[0] != "SelectAI"]

        # Vector Search Requirements
        embed_models_enabled = enabled_models_lookup("embed")
        if not embed_models_enabled:
            logger.debug("Vector Search Disabled (no Embedding Models)")
            st.warning("No embedding models are configured and/or enabled. Disabling Vector Search.", icon="⚠️")
            tools = [t for t in tools if t[0] != "Vector Search"]
        elif not database_lookup[db_alias].get("vector_stores"):
            logger.debug("Vector Search Disabled (Database has no vector stores.)")
            st.warning("Database has no Vector Stores. Disabling Vector Search.", icon="⚠️")
            tools = [t for t in tools if t[0] != "Vector Search"]

        tool_box = [name for name, _, disabled in tools if not disabled]
        if len(tool_box) > 1:
            st.sidebar.subheader("Toolkit", divider="red")
            tool_index = next(
                (
                    i
                    for i, t in enumerate(tools)
                    if (t[0] == "SelectAI" and state.client_settings["selectai"]["enabled"])
                    or (t[0] == "Vector Search" and state.client_settings["vector_search"]["enabled"])
                ),
                0,
            )
            st.sidebar.selectbox(
                "Tool Selection",
                tool_box,
                index=tool_index,
                label_visibility="collapsed",
                on_change=update_set_tool,
                key="selected_tool",
            )
            if state.selected_tool == "None":
                switch_prompt("sys", "Basic Example")


#####################################################
# SelectAI Options
#####################################################
def selectai_sidebar() -> None:
    """SelectAI Sidebar Settings, conditional if Database/SelectAI are configured"""
    db_alias = state.client_settings["database"]["alias"]
    database_lookup = state_configs_lookup("database_configs", "name")
    if state.client_settings["selectai"]["enabled"]:
        st.sidebar.subheader("SelectAI", divider="red")
        selectai_profiles = database_lookup[db_alias]["selectai_profiles"]
        if not state.client_settings["selectai"]["profile"]:
            state.client_settings["selectai"]["profile"] = selectai_profiles[0]
        st.sidebar.selectbox(
            "Profile:",
            options=selectai_profiles,
            index=selectai_profiles.index(state.client_settings["selectai"]["profile"]),
            key="selected_selectai_profile",
            on_change=update_client_settings("selectai"),
        )
        st.sidebar.selectbox(
            "Action:",
            get_args(SelectAISettings.__annotations__["action"]),
            index=get_args(SelectAISettings.__annotations__["action"]).index(
                state.client_settings["selectai"]["action"]
            ),
            key="selected_selectai_action",
            on_change=update_client_settings("selectai"),
        )


#####################################################
# Vector Search Options
#####################################################
def vector_search_sidebar() -> None:
    """Vector Search Sidebar Settings, conditional if Database/Embeddings are configured"""
    if state.client_settings["vector_search"]["enabled"]:
        st.sidebar.subheader("Vector Search", divider="red")

        switch_prompt("sys", "Vector Search Example")
        ##########################
        # Search
        ##########################
        # TODO(gotsysdba) "Similarity Score Threshold" currently raises NotImplementedError
        # vector_search_type_list =
        # ["Similarity", "Similarity Score Threshold", "Maximal Marginal Relevance"]
        vector_search_type_list = ["Similarity", "Maximal Marginal Relevance"]
        vector_search_type = st.sidebar.selectbox(
            "Search Type:",
            vector_search_type_list,
            index=vector_search_type_list.index(state.client_settings["vector_search"]["search_type"]),
            key="selected_vector_search_search_type",
            on_change=update_client_settings("vector_search"),
        )
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

        ##########################
        # Vector Store
        ##########################
        st.sidebar.subheader("Vector Store", divider="red")
        # Create a DataFrame of all database vector storage tables
        db_alias = state.client_settings["database"]["alias"]
        database_lookup = state_configs_lookup("database_configs", "name")

        vs_df = pd.DataFrame(database_lookup[db_alias].get("vector_stores"))

        def vs_reset() -> None:
            """Reset Vector Store Selections"""
            for key in state.client_settings["vector_search"]:
                if key in (
                    "model",
                    "chunk_size",
                    "chunk_overlap",
                    "distance_metric",
                    "vector_store",
                    "alias",
                    "index_type",
                ):
                    clear_state_key(f"selected_vector_search_{key}")
                    state.client_settings["vector_search"][key] = ""

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
                    selected_value = (
                        state.client_settings["vector_search"][key.removeprefix("selected_vector_search_")] or ""
                    )
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
            embed_models_enabled = enabled_models_lookup("embed")
            filtered = vs_df.copy()
            # Remove vector stores where the model is not enabled
            filtered = vs_df[vs_df["model"].isin(embed_models_enabled.keys())]
            if state.get("selected_vector_search_alias"):
                filtered = filtered[filtered["alias"] == state.selected_vector_search_alias]
            if state.get("selected_vector_search_model"):
                filtered = filtered[filtered["model"] == state.selected_vector_search_model]
            if state.get("selected_vector_search_chunk_size"):
                filtered = filtered[filtered["chunk_size"] == state.selected_vector_search_chunk_size]
            if state.get("selected_vector_search_chunk_overlap"):
                filtered = filtered[filtered["chunk_overlap"] == state.selected_vector_search_chunk_overlap]
            if state.get("selected_vector_search_distance_metric"):
                filtered = filtered[filtered["distance_metric"] == state.selected_vector_search_distance_metric]
            if state.get("selected_vector_search_index_type"):
                filtered = filtered[filtered["index_type"] == state.selected_vector_search_index_type]
            return filtered

        # Initialize filtered options
        filtered_df = update_filtered_df()

        # Render selectbox with updated options
        alias = vs_gen_selectbox(
            "Select Alias:", filtered_df["alias"].unique().tolist(), "selected_vector_search_alias"
        )
        embed_model = vs_gen_selectbox(
            "Select Model:", filtered_df["model"].unique().tolist(), "selected_vector_search_model"
        )
        chunk_size = vs_gen_selectbox(
            "Select Chunk Size:", filtered_df["chunk_size"].unique().tolist(), "selected_vector_search_chunk_size"
        )
        chunk_overlap = vs_gen_selectbox(
            "Select Chunk Overlap:",
            filtered_df["chunk_overlap"].unique().tolist(),
            "selected_vector_search_chunk_overlap",
        )
        distance_metric = vs_gen_selectbox(
            "Select Distance Metric:",
            filtered_df["distance_metric"].unique().tolist(),
            "selected_vector_search_distance_metric",
        )
        index_type = vs_gen_selectbox(
            "Select Index Type:", filtered_df["index_type"].unique().tolist(), "selected_vector_search_index_type"
        )

        if all([alias, embed_model, chunk_size, chunk_overlap, distance_metric, index_type]):
            vs = filtered_df["vector_store"].iloc[0]
            state.client_settings["vector_search"]["vector_store"] = vs
            state.client_settings["vector_search"]["alias"] = alias
            state.client_settings["vector_search"]["model"] = embed_model
            state.client_settings["vector_search"]["chunk_size"] = chunk_size
            state.client_settings["vector_search"]["chunk_overlap"] = chunk_overlap
            state.client_settings["vector_search"]["distance_metric"] = distance_metric
            state.client_settings["vector_search"]["index_type"] = index_type
        else:
            st.error("Please select Vector Store options or disable Vector Search to continue.", icon="❌")
            state.enable_client = False

        # Reset button
        st.sidebar.button("Reset", type="primary", on_click=vs_reset)
