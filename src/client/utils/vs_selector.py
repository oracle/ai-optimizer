"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore isin selectbox

import pandas as pd
import streamlit as st
from streamlit import session_state as state

from client.utils import st_common
from common import logging_config

logger = logging_config.logging.getLogger("client.utils.vs_selector")


def _vs_gen_selectbox(col, label: str, options: list, key: str):
    """Handle selectbox with auto-setting for a single unique value"""
    valid_options = [option for option in options if option != ""]
    if not valid_options:
        disabled = True
        selected_value = ""
    else:
        disabled = False
        selected_value = valid_options[0] if len(valid_options) == 1 else ""

    return col.selectbox(
        label,
        options=[""] + valid_options,
        key=key,
        index=([""] + valid_options).index(selected_value),
        disabled=disabled,
    )


def render_vector_store_selection(container=None) -> None:
    """Render vector store selection controls and handle state updates.

    Automatically uses the currently selected database from session state.

    Args:
        container: Optional Streamlit container (e.g., st.sidebar).
                   If None, uses main area with columns. If provided, stacks vertically.
    """
    # Get current database alias from state and generate vs_df internally
    db_alias = state.client_settings.get("database", {}).get("alias")
    database_lookup = st_common.state_configs_lookup("database_configs", "name")
    vs_df = pd.DataFrame(database_lookup.get(db_alias, {}).get("vector_stores", []))

    ctx = container if container is not None else st

    ctx.subheader("Existing Vector Store", divider="red")

    # Create containers based on layout preference
    # Use columns in main area, stack vertically in sidebar
    if container is None:
        alias_col, model_col = ctx.columns([0.2, 0.8])
        row2_col1, row2_col2 = ctx.columns([0.3, 0.3])
        row3_col1, row3_col2 = ctx.columns([0.3, 0.3])
        containers = [alias_col, model_col, row2_col1, row2_col2, row3_col1, row3_col2]
    else:
        containers = [ctx] * 6

    selectbox_configs = [
        (containers[0], "Select Alias:", "alias", "selected_vector_search_alias"),
        (containers[1], "Select Model:", "model", "selected_vector_search_model"),
        (containers[2], "Select Chunk Size:", "chunk_size", "selected_vector_search_chunk_size"),
        (containers[3], "Select Chunk Overlap:", "chunk_overlap", "selected_vector_search_chunk_overlap"),
        (containers[4], "Select Distance Metric:", "distance_metric", "selected_vector_search_distance_metric"),
        (containers[5], "Select Index Type:", "index_type", "selected_vector_search_index_type"),
    ]

    def reset() -> None:
        """Reset Vector Store Selections"""
        for key in state:
            if key.startswith("selected_vector_search_"):
                st_common.clear_state_key(key)

    # --- Filter the dataframe based on current selections ---
    embed_models_enabled = st_common.enabled_models_lookup("embed")

    # Check if vs_df is empty before filtering
    if vs_df.empty:
        ctx.info("No vector stores found in the selected database.")
        return

    filtered_df = vs_df[vs_df["model"].isin(embed_models_enabled.keys())]
    for _, _, df_col, state_key in selectbox_configs:
        if state.get(state_key):
            filtered_df = filtered_df[filtered_df[df_col] == state[state_key]]

    # --- Render selections ---
    selections = {}
    for col, label, df_col, state_key in selectbox_configs:
        options = filtered_df[df_col].unique().tolist()
        selections[state_key] = _vs_gen_selectbox(col, label, options, state_key)

    if not all(selections.values()):
        ctx.info("Please select existing Vector Store options to continue.")
    else:
        # There should only be one row matching all selected values
        description_value = filtered_df.iloc[0]["description"]
        state.selected_vector_search_description = description_value

    # --- Reset button ---
    ctx.button("Reset", type="primary", on_click=reset)
