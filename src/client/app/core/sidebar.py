"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore isin mult selectbox selectboxes subtools litellm subtool

import contextlib
import logging

import httpx
import pandas as pd
import streamlit as st
from streamlit import session_state as state

from client.app.core.api import api_get, api_patch, api_post
from client.app.core.auth import is_authenticated
from client.app.core.helpers import (
    enabled_models_lookup,
    selectbox_index,
    state_configs_lookup,
    update_client_settings,
)

LOGGER = logging.getLogger("client.core.sidebar")


def _usable_models_lookup() -> dict[str, dict]:
    """Return enabled LLM models that are also available for use."""
    return {key: cfg for key, cfg in enabled_models_lookup("ll").items() if cfg.get("status") == "available"}


def _vs_embed_key(vs: dict) -> str:
    """Build a '{provider}/{id}' key from a vector store's embedding_model."""
    em = vs.get("embedding_model")
    if isinstance(em, dict) and em:
        return f"{em.get('provider', '')}/{em.get('id', '')}"
    return ""


def _on_model_change() -> None:
    """Callback when the chat model selector changes."""
    selected = state.runtime_chat_model_selector
    if not selected:
        return
    parts = selected.split("/", 1)
    if len(parts) != 2:
        return
    provider, model_id = parts
    update_client_settings({"ll_model": {"provider": provider, "id": model_id}})


def _on_chat_history_change() -> None:
    """Callback when the chat history checkbox changes."""
    update_client_settings({"ll_model": {"chat_history": state.runtime_chat_history_enabled}})


def _clear_server_history() -> None:
    """Clear server-side chat history and local chat messages."""
    with contextlib.suppress(Exception):
        api_patch("chat/history", extra_headers={"client": state.optimizer_client})


def _on_ll_model_param_change(field: str, widget_key: str) -> None:
    """Generic callback for ll_model parameter sliders."""
    update_client_settings({"ll_model": {field: state[widget_key]}})


def _on_tools_change() -> None:
    """Persist the tool multiselect value to the server."""
    update_client_settings({"tools_enabled": state.runtime_tools})


def _on_vs_subtool_change() -> None:
    """Persist vector search sub-tool checkbox changes to the server."""
    vs_update = {}
    for key, widget_key in [
        ("discovery", "runtime_vs_discovery"),
        ("rephrase", "runtime_vs_rephrase"),
        ("grade", "runtime_vs_grade"),
    ]:
        if widget_key in state:
            vs_update[key] = state[widget_key]
    if vs_update:
        update_client_settings({"vector_search": vs_update})


def _on_vs_param_change(field: str, widget_key: str) -> None:
    """Generic callback for vector_search parameter widgets."""
    update_client_settings({"vector_search": {field: state[widget_key]}})


def _on_dds_change() -> None:
    """Persist the Deep Data Security tool-connection toggle (runtime/session-scoped)."""
    update_client_settings({"deep_data_security": {"enabled": state.runtime_dds_enabled}})


def _auto_configure_single_dds_end_user(client_settings: dict, db_alias: str) -> None:
    """Configure the sole DDS end user for the active database once per session."""
    dds = client_settings.get("deep_data_security", {})
    if (
        not client_settings.get("tools_enabled")
        or dds.get("base_alias") == db_alias
        or state.get("_ds_autodefault_alias") == db_alias
    ):
        return

    state["_ds_autodefault_alias"] = db_alias
    if not is_authenticated():
        return

    try:
        users = api_get("deepsec/end-users", extra_headers={"client": state.optimizer_client})
    except httpx.HTTPError as exc:
        LOGGER.debug("Unable to list Deep Data Security end users: %s", exc)
        return
    if len(users) != 1 or not (end_user := users[0].get("name")):
        return

    try:
        response = api_post(
            "deepsec/connect-as",
            json={"end_user": end_user},
            extra_headers={"client": state.optimizer_client},
            timeout=60,
        )
    except httpx.HTTPError as exc:
        LOGGER.debug("Unable to configure Deep Data Security connect-as: %s", exc)
        return

    enabled = dds.get("enabled", False)
    update_client_settings(
        {
            "deep_data_security": {
                "enabled": enabled,
                "end_user": end_user,
                "alias": response.get("alias"),
                "base_alias": response.get("base_alias"),
            }
        }
    )


#####################################################
# Vector Store Selection Helpers
#####################################################
def _build_vs_dataframe(vector_stores: list[dict]) -> pd.DataFrame:
    """Transform vector store dicts into a DataFrame with selectbox-friendly columns."""
    if not vector_stores:
        return pd.DataFrame()
    df = pd.DataFrame(vector_stores)
    if "embedding_model" in df.columns:
        df["model"] = df["embedding_model"].apply(
            lambda em: f"{em['provider']}/{em['id']}" if isinstance(em, dict) and em else ""
        )
    else:
        df["model"] = ""
    return df


def _vs_store_fields() -> list[tuple[str, str]]:
    """Return vector store selection fields: (label, dataframe_column)."""
    return [
        ("Select Alias:", "alias"),
        ("Select Model:", "model"),
        ("Select Chunk Size:", "chunk_size"),
        ("Select Chunk Overlap:", "chunk_overlap"),
        ("Select Distance Strategy:", "distance_strategy"),
        ("Select Index Type:", "index_type"),
    ]


def _vs_reset_selections() -> None:
    """Reset all vector store selections and persist to server."""
    vs_settings = state["settings"]["client_settings"].get("vector_search", {})
    reset_payload: dict = {
        "alias": None,
        "provider": None,
        "id": None,
        "chunk_size": None,
        "chunk_overlap": None,
        "distance_strategy": None,
        "index_type": None,
        "vector_store": None,
    }
    for _, col in _vs_store_fields():
        vs_settings[col] = ""
    vs_settings["vector_store"] = ""
    state["_vs_key_version"] = state.get("_vs_key_version", 0) + 1
    update_client_settings({"vector_search": reset_payload})


def _vs_get_valid_options(base_df: pd.DataFrame, col: str, selections: dict) -> list:
    """Get valid options for a field, filtered by all OTHER selections."""
    filtered_df = base_df
    for _, other_col in _vs_store_fields():
        if other_col != col and selections.get(other_col):
            filtered_df = filtered_df[filtered_df[other_col] == selections[other_col]]
    return [opt for opt in filtered_df[col].unique().tolist() if opt != ""]


def _vs_auto_select(base_df: pd.DataFrame, selections: dict) -> dict:
    """Auto-select fields with single valid option, clear invalid selections."""
    result = selections.copy()
    changed = True
    while changed:
        changed = False
        for _, col in _vs_store_fields():
            valid_options = _vs_get_valid_options(base_df, col, result)
            if len(valid_options) == 1 and result.get(col) != valid_options[0]:
                result[col] = valid_options[0]
                changed = True
            elif result.get(col) and result[col] not in valid_options:
                result[col] = ""
                changed = True
    return result


def _vs_get_current_selections(key_version: int) -> dict:
    """Get current selections from widget state or client_settings."""
    vs_settings = state["settings"]["client_settings"].get("vector_search", {})
    current_selections = {}
    for _, col in _vs_store_fields():
        widget_key = f"runtime_vs_store_{col}_{key_version}"
        if widget_key in state:
            current_selections[col] = state[widget_key]
        elif col == "model":
            provider = vs_settings.get("provider", "")
            model_id = vs_settings.get("id", "")
            current_selections[col] = f"{provider}/{model_id}" if provider and model_id else ""
        else:
            current_selections[col] = vs_settings.get(col, "")
    return current_selections


def _vs_render_selectbox(
    container, label: str, col: str, base_df: pd.DataFrame, current_selections: dict, key_version: int
) -> str:
    """Render a single vector store selectbox and return its value."""
    valid_options = _vs_get_valid_options(base_df, col, current_selections)
    initial = current_selections[col] if current_selections[col] in valid_options else ""
    all_options = [""] + valid_options
    widget_key = f"runtime_vs_store_{col}_{key_version}"
    return container.selectbox(
        label,
        options=all_options,
        index=all_options.index(initial),
        key=widget_key,
        disabled=not valid_options,
    )


def _vs_render_sidebar_selectboxes(
    container, base_df: pd.DataFrame, current_selections: dict, key_version: int
) -> dict:
    """Render selectboxes in sidebar layout (vertical stack)."""
    selections = {}
    for label, col in _vs_store_fields():
        selections[col] = _vs_render_selectbox(container, label, col, base_df, current_selections, key_version)
    return selections


def _vs_render_main_selectboxes(container, base_df: pd.DataFrame, current_selections: dict, key_version: int) -> dict:
    """Render selectboxes in main layout (3 rows of 2 columns)."""
    selections = {}
    fields = _vs_store_fields()

    columns = [
        *container.columns([0.6, 1.4]),
        *container.columns([1, 1]),
        *container.columns([1, 1]),
    ]

    for idx, (label, col) in enumerate(fields):
        selections[col] = _vs_render_selectbox(columns[idx], label, col, base_df, current_selections, key_version)

    return selections


def _disable_tool(tool: str, reason: str | None = None) -> None:
    """Disable a tool in the tool box, optionally showing a warning."""
    if reason:
        LOGGER.debug("%s Disabled (%s)", tool, reason)
        st.warning(f"{reason} Disabling {tool}.", icon="⚠️")
    state.tool_box[tool]["enabled"] = False


def _is_small_model(client_settings: dict) -> bool:
    """Check if the active LLM is a small model via its model_config entry."""
    ll = client_settings.get("ll_model", {})
    provider = ll.get("provider", "")
    model_id = ll.get("id", "")
    key = f"{provider}/{model_id}"
    model_configs = state_configs_lookup("model_configs", "id")
    cfg = model_configs.get(model_id) or model_configs.get(key, {})
    return cfg.get("small_model", False)


def _render_vs_subtools(vs_settings: dict, small_model: bool) -> None:
    """Render Vector Search sub-tool checkboxes (rephrase, grade).

    CPU-mode detection and auto-disable are handled by the caller (toolkit_sidebar) so they also
    cover Store Discovery; here we only render the checkboxes and the re-enable warning.
    """
    st.sidebar.checkbox(
        "Prompt Rephrase",
        help=state.optimizer_help.get("vector_search_rephrase", ""),
        value=vs_settings.get("rephrase", True),
        key="runtime_vs_rephrase",
        on_change=_on_vs_subtool_change,
    )
    st.sidebar.checkbox(
        "Document Grading",
        help=state.optimizer_help.get("vector_search_grade", ""),
        value=vs_settings.get("grade", True),
        key="runtime_vs_grade",
        on_change=_on_vs_subtool_change,
    )

    if small_model and (vs_settings.get("rephrase") or vs_settings.get("grade")):
        st.sidebar.warning("Enabling on small models increases response time")


def _apply_cpu_optimization(client_settings: dict, vs_settings: dict, show_vs_subtools: bool) -> bool:
    """Disable newly available Vector Search controls once for each small model."""
    small_model = _is_small_model(client_settings)
    model_id = client_settings.get("ll_model", {}).get("id", "")
    model_changed = state.get("_previous_ll_model_for_cpu") != model_id
    processed_controls = set(state.get("_cpu_optimized_controls", ())) if not model_changed else set()
    state["_previous_ll_model_for_cpu"] = model_id
    available_controls = {"discovery"}
    if show_vs_subtools:
        available_controls.update({"rephrase", "grade"})

    if small_model:
        st.sidebar.info("CPU Mode: Additional tools auto-disabled")
        controls_to_disable = available_controls - processed_controls
        if controls_to_disable:
            LOGGER.info("Small model detected (%s)", model_id)
            disabled = {key: False for key in ("discovery", "rephrase", "grade") if key in controls_to_disable}
            vs_settings.update(disabled)
            for key in disabled:
                widget_key = f"runtime_vs_{key}"
                if widget_key in state:
                    state[widget_key] = False
            update_client_settings({"vector_search": disabled})
    state["_cpu_optimized_controls"] = processed_controls | available_controls
    return small_model


def _check_vector_search_availability(db_config: dict) -> None:
    """Disable Vector Search if embedding models or vector stores are misconfigured."""
    embed_models_enabled = enabled_models_lookup("embed")
    if not embed_models_enabled:
        _disable_tool("Vector Search", "No embedding models are configured and/or enabled.")
        return
    if not db_config.get("vector_stores"):
        _disable_tool("Vector Search", "Database has no vector stores.")
        return
    vector_stores = db_config.get("vector_stores", [])
    usable_vector_stores = [vs for vs in vector_stores if _vs_embed_key(vs) in embed_models_enabled]
    if not usable_vector_stores:
        _disable_tool("Vector Search", "No vector stores match the enabled embedding models.")


def toolkit_sidebar(show_vs_subtools: bool = True) -> None:
    """Tools Sidebar Settings.

    Args:
        show_vs_subtools: Whether to show VS sub-tool options (rephrase, grade).
            Set to False for testbed page where these don't apply.
    """
    if not _usable_models_lookup():
        return

    client_settings = state["settings"]["client_settings"]
    st.sidebar.subheader("Toolkit", divider="red")

    state.tool_box = {
        "Vector Search": {"description": "Use AI with Unstructured Data", "enabled": True},
        "NL2SQL": {"description": "Use AI with Structured Data", "enabled": True},
    }

    # Check database configuration
    db_alias = client_settings.get("database", {}).get("alias")
    database_lookup = state_configs_lookup("database_configs", "alias")
    db_config = database_lookup.get(db_alias) if db_alias else None

    if not db_config or not db_config.get("usable"):
        st.warning("Database is not configured or connected. Some functionality is disabled.", icon="⚠️")
        _disable_tool("Vector Search")
        _disable_tool("NL2SQL")
    else:
        _check_vector_search_availability(db_config)

        if not state["settings"].get("nl2sql_available", False):
            _disable_tool("NL2SQL", "NL2SQL proxy is not available.")

    tool_box = [key for key, val in state.tool_box.items() if val["enabled"]]

    # Prune any tools_enabled entries that are no longer available
    tools_enabled = client_settings.get("tools_enabled", [])
    valid_tools = [tool for tool in tools_enabled if tool in tool_box]
    if valid_tools != tools_enabled:
        client_settings["tools_enabled"] = valid_tools

    st.sidebar.multiselect(
        "Tool Selection",
        options=tool_box,
        default=client_settings["tools_enabled"],
        placeholder="Language Model Only",
        label_visibility="collapsed",
        on_change=_on_tools_change,
        key="runtime_tools",
    )
    client_settings["tools_enabled"] = state.runtime_tools

    _auto_configure_single_dds_end_user(client_settings, db_alias)
    client_settings = state["settings"]["client_settings"]

    # Deep Data Security: connect chat tools as the configured end user. Shown only when a
    # connect-as user is configured for the *currently selected* database (Tools → Deep Data
    # Security); switching the owner database hides it until re-designated.
    dds = client_settings.get("deep_data_security", {})
    if (
        client_settings["tools_enabled"]
        and db_config
        and db_config.get("usable")
        and dds.get("end_user")
        and dds.get("base_alias") == db_alias
    ):
        st.sidebar.checkbox(
            "Deep Data Security",
            help=(
                f"Connect Vector Search and NL2SQL as end user '{dds['end_user']}' so data-access "
                "policies are enforced. Does not affect Language Model only."
            ),
            value=dds.get("enabled", False),
            key="runtime_dds_enabled",
            on_change=_on_dds_change,
        )
        client_settings["deep_data_security"]["enabled"] = state.runtime_dds_enabled

    # Vector Search Sub-Tools
    if "Vector Search" in client_settings["tools_enabled"]:
        vs_settings = client_settings.get("vector_search", {})

        # Testbed does not expose rephrase or grading, so process each control when it first becomes
        # available. After that, reruns preserve any manual re-enablement for the selected model.
        small_model = _apply_cpu_optimization(client_settings, vs_settings, show_vs_subtools)

        st.sidebar.checkbox(
            "Store Discovery",
            help=state.optimizer_help.get("vector_search_discovery", ""),
            value=vs_settings.get("discovery", True),
            key="runtime_vs_discovery",
            on_change=_on_vs_subtool_change,
        )
        if show_vs_subtools:
            _render_vs_subtools(vs_settings, small_model)


def history_sidebar() -> None:
    """Render the History and Context sidebar section."""
    if not _usable_models_lookup():
        return

    ll_model = state["settings"]["client_settings"].get("ll_model", {})

    st.sidebar.subheader("History and Context", divider="red")
    checkbox_col, button_col = st.sidebar.columns(2)
    checkbox_col.checkbox(
        "Enable?",
        value=ll_model.get("chat_history", True),
        key="runtime_chat_history_enabled",
        on_change=_on_chat_history_change,
    )
    button_col.button("Clear", on_click=_clear_server_history)


def lm_sidebar() -> list[str]:
    """Render the model selector and Language Model Parameters sidebar section.

    Returns the list of usable model keys. The returned list is empty when
    no models are available, which callers can use to disable input widgets.
    """
    usable = _usable_models_lookup()
    model_options = list(usable.keys())

    ll_model = state["settings"]["client_settings"].get("ll_model", {})
    current_model = f"{ll_model.get('provider', '')}/{ll_model.get('id', '')}" if ll_model else None

    # Selectbox falls back to index 0 when current_model isn't in options, but
    # on_change only fires on real user input — so persist the auto-selection.
    if model_options and current_model not in model_options:
        provider, model_id = model_options[0].split("/", 1)
        update_client_settings({"ll_model": {"provider": provider, "id": model_id}})
        current_model = model_options[0]

    if model_options:
        st.sidebar.subheader("Language Model Parameters", divider="red")
        st.sidebar.selectbox(
            "Chat Model:",
            options=model_options,
            index=selectbox_index(model_options, current_model),
            key="runtime_chat_model_selector",
            on_change=_on_model_change,
        )
        st.sidebar.slider(
            "Temperature:",
            help=state.optimizer_help["temperature"],
            min_value=0.0,
            max_value=2.0,
            value=float(ll_model.get("temperature", 0.5)),
            step=0.1,
            key="runtime_chat_temperature",
            on_change=_on_ll_model_param_change,
            args=("temperature", "runtime_chat_temperature"),
        )

        max_input = ll_model.get("max_input_tokens") or 4096
        current_max = ll_model.get("max_tokens") or 4096
        st.sidebar.slider(
            "Maximum Output Tokens:",
            help=state.optimizer_help["max_tokens"],
            min_value=1,
            max_value=max_input,
            value=min(current_max, max_input),
            step=1,
            key="runtime_chat_max_tokens",
            on_change=_on_ll_model_param_change,
            args=("max_tokens", "runtime_chat_max_tokens"),
        )

        st.sidebar.slider(
            "Top P:",
            help=state.optimizer_help["top_p"],
            min_value=0.0,
            max_value=1.0,
            value=float(ll_model.get("top_p", 1.0)),
            step=0.1,
            key="runtime_chat_top_p",
            on_change=_on_ll_model_param_change,
            args=("top_p", "runtime_chat_top_p"),
        )

        st.sidebar.slider(
            "Frequency Penalty:",
            help=state.optimizer_help["frequency_penalty"],
            min_value=-2.0,
            max_value=2.0,
            value=float(ll_model.get("frequency_penalty", 0.0)),
            step=0.1,
            key="runtime_chat_frequency_penalty",
            on_change=_on_ll_model_param_change,
            args=("frequency_penalty", "runtime_chat_frequency_penalty"),
        )

        st.sidebar.slider(
            "Presence Penalty:",
            help=state.optimizer_help["presence_penalty"],
            min_value=-2.0,
            max_value=2.0,
            value=float(ll_model.get("presence_penalty", 0.0)),
            step=0.1,
            key="runtime_chat_presence_penalty",
            on_change=_on_ll_model_param_change,
            args=("presence_penalty", "runtime_chat_presence_penalty"),
        )

    return model_options


#####################################################
# Vector Search Sidebar
#####################################################
def vector_store_selection(location: str = "sidebar") -> None:
    """Vector Store selection — cross-filtered selectboxes for choosing a specific store.

    Args:
        location: "sidebar" (default) or "main"
    """
    client_settings = state["settings"]["client_settings"]
    vs_settings = client_settings.get("vector_search", {})

    if location == "sidebar" and vs_settings.get("discovery", False):
        return

    container = st.sidebar if location == "sidebar" else st
    container.subheader("Vector Store", divider="red")
    info_placeholder = st.empty()

    # Build base dataframe filtered by enabled embed models
    vs_df = _build_vs_dataframe(
        state_configs_lookup("database_configs", "alias")
        .get(client_settings.get("database", {}).get("alias"), {})
        .get("vector_stores", [])
    )
    base_df = (
        vs_df[vs_df["model"].isin(enabled_models_lookup("embed").keys())].copy()
        if not vs_df.empty and "model" in vs_df.columns
        else vs_df
    )

    # Get and validate current selections
    key_version = state.get("_vs_key_version", 0)
    current_selections = _vs_auto_select(base_df, _vs_get_current_selections(key_version))

    # Sync auto-selected values to widget state so selectboxes reflect them
    for _, col in _vs_store_fields():
        if current_selections[col]:
            state[f"runtime_vs_store_{col}_{key_version}"] = current_selections[col]
        vs_settings[col] = current_selections[col]

    # Render selectboxes based on location
    selections = (
        _vs_render_main_selectboxes(container, base_df, current_selections, key_version)
        if location == "main"
        else _vs_render_sidebar_selectboxes(container, base_df, current_selections, key_version)
    )

    # Update vector_store when all fields are selected
    if all(selections.values()):
        final_df = base_df.copy()
        for _, col in _vs_store_fields():
            final_df = final_df[final_df[col] == selections[col]]
        if not final_df.empty:
            vs_settings["vector_store"] = final_df["vector_store"].iloc[0]
            # Persist the full selection to the server (split model back to provider/id)
            update_payload: dict = {col: selections[col] for _, col in _vs_store_fields() if col != "model"}
            parts = selections["model"].split("/", 1)
            if len(parts) == 2:
                update_payload["provider"] = parts[0]
                update_payload["id"] = parts[1]
            update_payload["vector_store"] = vs_settings["vector_store"]
            update_client_settings({"vector_search": update_payload})
        state.enable_client = True
    else:
        info_placeholder.info("Please select existing Vector Store options to continue.", icon="↙️")
        state.enable_client = False

    container.button("Reset", type="primary", on_click=_vs_reset_selections)


def vector_search_sidebar() -> None:
    """Vector Search Sidebar — search parameters and vector store selection."""
    client_settings = state["settings"]["client_settings"]
    if "Vector Search" not in client_settings.get("tools_enabled", []):
        return

    vs_settings = client_settings.get("vector_search", {})
    st.sidebar.subheader("Vector Search", divider="red")

    # Search Type Selection
    search_type_options = ["Similarity", "Maximal Marginal Relevance"]
    current_search_type = vs_settings.get("search_type", "Similarity")
    st.sidebar.selectbox(
        "Search Type:",
        search_type_options,
        index=selectbox_index(search_type_options, current_search_type),
        key="runtime_vs_search_type",
        on_change=_on_vs_param_change,
        args=("search_type", "runtime_vs_search_type"),
    )
    vector_search_type = state.runtime_vs_search_type

    # Top K
    st.sidebar.number_input(
        "Top K:",
        help=state.optimizer_help.get("top_k", ""),
        value=vs_settings.get("top_k", 4),
        min_value=1,
        max_value=10000,
        key="runtime_vs_top_k",
        on_change=_on_vs_param_change,
        args=("top_k", "runtime_vs_top_k"),
    )

    # Conditional parameters based on search type
    if vector_search_type == "Similarity":
        st.sidebar.slider(
            "Score Threshold:",
            help=state.optimizer_help.get("score_threshold", ""),
            value=float(vs_settings.get("score_threshold", 0.0)),
            min_value=0.0,
            max_value=1.0,
            step=0.05,
            key="runtime_vs_score_threshold",
            on_change=_on_vs_param_change,
            args=("score_threshold", "runtime_vs_score_threshold"),
        )
    if vector_search_type == "Maximal Marginal Relevance":
        st.sidebar.number_input(
            "Fetch K:",
            help=state.optimizer_help.get("fetch_k", ""),
            value=vs_settings.get("fetch_k", 20),
            min_value=1,
            max_value=10000,
            key="runtime_vs_fetch_k",
            on_change=_on_vs_param_change,
            args=("fetch_k", "runtime_vs_fetch_k"),
        )
        st.sidebar.slider(
            "Degree of Diversity:",
            help=state.optimizer_help.get("lambda_mult", ""),
            value=float(vs_settings.get("lambda_mult", 0.5)),
            min_value=0.0,
            max_value=1.0,
            step=0.1,
            key="runtime_vs_lambda_mult",
            on_change=_on_vs_param_change,
            args=("lambda_mult", "runtime_vs_lambda_mult"),
        )

    # Show Vector Store Selection
    vector_store_selection()
