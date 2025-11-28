"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore mult selectbox selectboxes

import pandas as pd
import streamlit as st
from streamlit import session_state as state

from client.utils import st_common
from common import logging_config, help_text

logger = logging_config.logging.getLogger("client.utils.vs_selector")


#####################################################
# Vector Search Options
#####################################################
def vector_search_sidebar() -> None:
    """Vector Search Sidebar Settings, conditional if Database/Embeddings are configured"""
    if "Vector Search" not in state.client_settings["tools_enabled"]:
        return

    st.sidebar.subheader("Vector Search", divider="red")

    # Search Type Selection
    vector_search_type_list = ["Similarity", "Maximal Marginal Relevance"]
    vector_search_type = st.sidebar.selectbox(
        "Search Type:",
        vector_search_type_list,
        index=vector_search_type_list.index(state.client_settings["vector_search"]["search_type"]),
        key="selected_vector_search_search_type",
        on_change=st_common.update_client_settings("vector_search"),
    )

    # Render search options based on type
    st.sidebar.number_input(
        "Top K:",
        help=help_text.help_dict["top_k"],
        value=state.client_settings["vector_search"]["top_k"],
        min_value=1,
        max_value=10000,
        key="selected_vector_search_top_k",
        on_change=st_common.update_client_settings("vector_search"),
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
            on_change=st_common.update_client_settings("vector_search"),
        )
    if vector_search_type == "Maximal Marginal Relevance":
        st.sidebar.number_input(
            "Fetch K:",
            help=help_text.help_dict["fetch_k"],
            value=state.client_settings["vector_search"]["fetch_k"],
            min_value=1,
            max_value=10000,
            key="selected_vector_search_fetch_k",
            on_change=st_common.update_client_settings("vector_search"),
        )
        st.sidebar.slider(
            "Degree of Diversity:",
            help=help_text.help_dict["lambda_mult"],
            value=state.client_settings["vector_search"]["lambda_mult"],
            min_value=0.0,
            max_value=1.0,
            step=0.1,
            key="selected_vector_search_lambda_mult",
            on_change=st_common.update_client_settings("vector_search"),
        )

    # Show Vector Store Selection
    vector_store_selection()


#####################################################
# Vector Search Store Options
#####################################################
def _get_vs_fields() -> list[tuple[str, str]]:
    """Return vector store selection fields: (label, dataframe_column)."""
    return [
        ("Select Alias:", "alias"),
        ("Select Model:", "model"),
        ("Select Chunk Size:", "chunk_size"),
        ("Select Chunk Overlap:", "chunk_overlap"),
        ("Select Distance Metric:", "distance_metric"),
        ("Select Index Type:", "index_type"),
    ]


def _reset_selections() -> None:
    """Reset all vector store selections."""
    for _, col in _get_vs_fields():
        state.client_settings["vector_search"][col] = ""
    state.client_settings["vector_search"]["vector_store"] = ""
    # Increment key version to force new widget instances
    state["_vs_key_version"] = state.get("_vs_key_version", 0) + 1


def _get_valid_options(base_df: pd.DataFrame, col: str, selections: dict) -> list:
    """Get valid options for a field, filtered by all OTHER selections."""
    filtered_df = base_df.copy()
    for _, other_col in _get_vs_fields():
        if other_col != col and selections.get(other_col):
            filtered_df = filtered_df[filtered_df[other_col] == selections[other_col]]
    return [opt for opt in filtered_df[col].unique().tolist() if opt != ""]


def _auto_select(base_df: pd.DataFrame, selections: dict) -> dict:
    """Auto-select fields with single valid option, clear invalid selections."""
    result = selections.copy()
    changed = True
    while changed:
        changed = False
        for _, col in _get_vs_fields():
            valid_options = _get_valid_options(base_df, col, result)
            if len(valid_options) == 1 and result.get(col) != valid_options[0]:
                result[col] = valid_options[0]
                changed = True
            elif result.get(col) and result[col] not in valid_options:
                result[col] = ""
                changed = True
    return result


def _get_current_selections(key_version: int) -> dict:
    """Get current selections from widget state or client settings."""
    current_selections = {}
    for _, col in _get_vs_fields():
        widget_key = f"vs_{col}_{key_version}"
        if widget_key in state:
            current_selections[col] = state[widget_key]
        else:
            current_selections[col] = state.client_settings["vector_search"].get(col, "")
    return current_selections


def _render_selectbox(
    container, label: str, col: str, base_df: pd.DataFrame, current_selections: dict, key_version: int
) -> str:
    """Render a single selectbox and return its value."""
    valid_options = _get_valid_options(base_df, col, current_selections)
    initial = current_selections[col] if current_selections[col] in valid_options else ""
    all_options = [""] + valid_options
    widget_key = f"vs_{col}_{key_version}"
    return container.selectbox(
        label,
        options=all_options,
        index=all_options.index(initial),
        key=widget_key,
        disabled=not valid_options,
    )


def _render_main_selectboxes(container, base_df: pd.DataFrame, current_selections: dict, key_version: int) -> dict:
    """Render selectboxes in main layout (3 rows of 2 columns)."""
    selections = {}
    fields = _get_vs_fields()

    alias_lov, model_lov = container.columns([0.6, 1.4])
    chunk_size_lov, chunk_overlap_lov = container.columns([1, 1])
    distance_lov, index_lov = container.columns([1, 1])
    columns = [alias_lov, model_lov, chunk_size_lov, chunk_overlap_lov, distance_lov, index_lov]

    for idx, (label, col) in enumerate(fields):
        selections[col] = _render_selectbox(columns[idx], label, col, base_df, current_selections, key_version)

    return selections


def _render_sidebar_selectboxes(container, base_df: pd.DataFrame, current_selections: dict, key_version: int) -> dict:
    """Render selectboxes in sidebar layout (vertical stack)."""
    selections = {}
    for label, col in _get_vs_fields():
        selections[col] = _render_selectbox(container, label, col, base_df, current_selections, key_version)
    return selections


def vector_store_selection(location: str = "sidebar") -> None:
    """Vector Search Settings.

    Args:
        location: "sidebar" (default) or "main"
    """
    container = st.sidebar if location == "sidebar" else st
    container.subheader("Vector Store", divider="red")
    info_placeholder = st.empty()

    # Build base dataframe filtered by enabled embed models
    db_alias = state.client_settings.get("database", {}).get("alias")
    database_lookup = st_common.state_configs_lookup("database_configs", "name")
    vs_df = pd.DataFrame(database_lookup.get(db_alias, {}).get("vector_stores", []))
    embed_models_enabled = st_common.enabled_models_lookup("embed")
    base_df = vs_df[vs_df["model"].isin(embed_models_enabled.keys())].copy()

    # Get and validate current selections
    key_version = state.get("_vs_key_version", 0)
    current_selections = _auto_select(base_df, _get_current_selections(key_version))

    # Update client_settings with validated selections
    for _, col in _get_vs_fields():
        state.client_settings["vector_search"][col] = current_selections[col]

    # Render selectboxes based on location
    if location == "main":
        selections = _render_main_selectboxes(container, base_df, current_selections, key_version)
    else:
        selections = _render_sidebar_selectboxes(container, base_df, current_selections, key_version)

    # Update vector_store when all fields are selected
    if all(selections.values()):
        final_df = base_df.copy()
        for _, col in _get_vs_fields():
            final_df = final_df[final_df[col] == selections[col]]
        state.client_settings["vector_search"]["vector_store"] = final_df["vector_store"].iloc[0]
        state.enable_client = True
    else:
        info_placeholder.info("Please select existing Vector Store options to continue.", icon="↙️")
        state.enable_client = False

    container.button("Reset", type="primary", on_click=_reset_selections)
