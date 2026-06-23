"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectbox litellm ollama

import logging
import urllib.parse
from typing import Any, Literal

import httpx
import streamlit as st
from streamlit import session_state as state

from client.app.core import helpers
from client.app.core.api import APIError, api_delete, api_get, api_post, api_post_stream, api_put
from client.app.core.auth import is_authenticated, locked_notice, redacted_password_input

LOGGER = logging.getLogger("client.content.config.tabs.models")


#####################################################
# Functions
#####################################################
def _model_configs_lookup(model_type: str) -> dict[str, dict[str, Any]]:
    """Build {provider/id: config} lookup from model_configs filtered by type."""
    return {
        f"{cfg['provider']}/{cfg['id']}": cfg
        for cfg in state["settings"]["model_configs"]
        if cfg.get("type") == model_type
    }


def _fetch_model(provider: str, model_id: str) -> dict | None:
    """Fetch a single model config with sensitive fields included."""
    try:
        quoted_id = urllib.parse.quote(model_id, safe="")
        return api_get(f"models/{provider}/{quoted_id}", params={"include_sensitive": "true"})
    except (httpx.HTTPStatusError, APIError):
        return None


def _get_supported_models(model_type: str) -> list[dict[str, Any]]:
    """Get list of supported providers and models from LiteLLM."""
    try:
        return api_get("models/supported", params={"model_type": model_type})
    except APIError as exc:
        st.error(f"Could not load supported models: {exc}")
        return []
    except httpx.HTTPStatusError:
        return []


def _clear_client_models(provider: str, model_id: str) -> None:
    """Clear model references from client_settings that match this model."""
    cs = state["settings"]["client_settings"]

    # ll_model uses ModelIdentity dict structure
    ll = cs.get("ll_model", {})
    if isinstance(ll, dict) and ll.get("provider") == provider and ll.get("id") == model_id:
        cs["ll_model"]["id"] = None
        cs["ll_model"]["provider"] = None

    # vector_search uses ModelIdentity for embedding model
    vs = cs.get("vector_search", {})
    if isinstance(vs, dict) and vs.get("provider") == provider and vs.get("id") == model_id:
        cs["vector_search"]["id"] = None
        cs["vector_search"]["provider"] = None

    # testbed has multiple model references
    tb = cs.get("testbed", {})
    if isinstance(tb, dict):
        for key in ("qa_ll_model", "qa_embed_model", "judge_model"):
            ref = tb.get(key)
            if isinstance(ref, dict) and ref.get("provider") == provider and ref.get("id") == model_id:
                tb[key] = None


#####################################################
# CRUD Handlers
#####################################################
def _handle_form_submit(
    model_type: str,
    is_new: bool,
    provider: str,
    model_id: str,
    form_data: dict,
    original_model: dict | None = None,
) -> bool:
    """Process model form submission (create or update). Returns True on success."""
    if not is_new and original_model is not None:
        changes = {k: v for k, v in form_data.items() if original_model.get(k) != v}
        if not changes:
            st.toast("No changes detected.", icon="ℹ️")
            return False

    try:
        if is_new:
            form_data["provider"] = provider
            form_data["id"] = model_id
            form_data["type"] = model_type
            with st.spinner("Creating model configuration..."):
                payload = helpers.build_payload(form_data)
                api_post("models", json=payload, toast=f"Model **{provider}/{model_id}** created.")
        else:
            quoted_id = urllib.parse.quote(model_id, safe="")
            with st.spinner("Updating model configuration..."):
                api_put(f"models/{provider}/{quoted_id}", json=helpers.build_payload(form_data))
                st.toast(f"Model **{provider}/{model_id}** updated.", icon="✅")
            # If updated model is disabled, clear references
            if not form_data.get("enabled", True):
                _clear_client_models(provider, model_id)
        helpers.refresh_settings()
        return True
    except httpx.HTTPStatusError as exc:
        st.error(f"Error: {helpers.extract_error_detail(exc)}")
        return False


def _remove_model(provider: str, model_id: str) -> bool:
    """Delete a model configuration. Returns True on success."""
    try:
        quoted_id = urllib.parse.quote(model_id, safe="")
        with st.spinner("Removing model configuration..."):
            api_delete(f"models/{provider}/{quoted_id}", toast=f"Model **{provider}/{model_id}** deleted.")
        _clear_client_models(provider, model_id)
        helpers.refresh_settings()
        return True
    except httpx.HTTPStatusError as exc:
        st.error(f"Remove failed: {helpers.extract_error_detail(exc)}")
        return False


#####################################################
# Dialog helpers
#####################################################
def _initialize_model(
    action: str, model_type: str, model_id: str | None, model_provider: str | None
) -> dict[str, Any]:
    """Initialize model configuration based on action type."""
    if action == "edit" and model_provider and model_id:
        return _fetch_model(model_provider, model_id) or {}
    return {"id": "", "type": model_type, "provider": "unset", "enabled": True}


def _render_provider_selection(model: dict, supported_models: list, action: str) -> tuple[dict, list, bool]:
    """Render provider selection UI and return updated model, provider models, and OCI flag."""
    provider_index = next(
        (i for i, item in enumerate(supported_models) if item["provider"] == model["provider"]), None
    )
    disable_for_oci = model.get("provider") == "oci"

    model["provider"] = st.selectbox(
        "Provider (Required):",
        help=state.optimizer_help["model_provider"],
        placeholder="-- Choose the Model's Provider --",
        index=provider_index,
        options=[item["provider"] for item in supported_models],
        key="add_model_provider",
        disabled=action == "edit" or not is_authenticated(),
    )

    # Get model IDs for the selected provider
    provider_models = []
    for item in supported_models:
        if item["provider"] == model["provider"]:
            provider_models = item["ids"]
            break

    return model, provider_models, disable_for_oci


def _render_model_selection(model: dict, provider_models: list, action: str) -> dict:
    """Render model selection UI and return updated model."""
    model_keys = [m["key"] for m in provider_models]
    model_index = next((i for i, key in enumerate(model_keys) if key == model.get("id")), None)

    # If the current model ID is not in the supported list, add it to the options
    if model_index is None and model.get("id") and model["id"] not in model_keys:
        model_keys.append(model["id"])
        model_index = len(model_keys) - 1

    model["id"] = st.selectbox(
        "Model (Required):",
        help=state.optimizer_help["model_id"],
        placeholder="-- Choose or Enter Model Name --",
        index=model_index,
        options=model_keys,
        key=f"add_model_id_{model.get('provider', '')}",
        accept_new_options=True,
        disabled=action == "edit" or not model.get("provider") or not is_authenticated(),
    )

    return model


def _render_api_configuration(model: dict, provider_models: list, disable_for_oci: bool) -> dict:
    """Render API configuration UI and return updated model."""
    authenticated = is_authenticated()
    litellm_api_base = next(
        (m.get("api_base", "") for m in provider_models if m.get("key") == model.get("id")),
        model.get("api_base", ""),
    )

    model["api_base"] = st.text_input(
        "Provider URL:",
        help=state.optimizer_help["model_url"],
        key="add_model_url",
        value=model.get("api_base", litellm_api_base),
        disabled=disable_for_oci or not authenticated,
    )

    api_key = redacted_password_input(
        "API Key:",
        value=model.get("api_key", ""),
        key="add_model_api_key",
        disabled=disable_for_oci,
        help=state.optimizer_help["model_api_key"],
    )
    if api_key is not None:
        model["api_key"] = api_key

    return model


def _render_model_specific_config(model: dict, model_type: str, provider_models: list) -> dict:
    """Render model type specific configuration and return updated model."""
    if model_type == "ll":
        max_input_tokens = next(
            (m.get("max_input_tokens", 8192) for m in provider_models if m.get("key") == model.get("id")),
            model.get("max_input_tokens", 8192),
        )
        model["max_input_tokens"] = st.number_input(
            "Max Input Tokens (Context Length):",
            help=state.optimizer_help["max_input_tokens"],
            min_value=0,
            key="add_model_max_input_tokens",
            value=max_input_tokens,
            disabled=not is_authenticated(),
        )

        max_tokens = next(
            (m.get("max_tokens", 4096) for m in provider_models if m.get("key") == model.get("id")),
            model.get("max_tokens", 4096),
        )
        model["max_tokens"] = st.number_input(
            "Max Output (Completion) Tokens:",
            help=state.optimizer_help["max_tokens"],
            min_value=1,
            key="add_model_max_tokens",
            value=max_tokens,
            disabled=not is_authenticated(),
        )
    else:
        max_chunk_size = model.get("max_chunk_size")
        if max_chunk_size is None:
            max_chunk_size = next(
                (m.get("max_chunk_size", 8192) for m in provider_models if m.get("key") == model.get("id")),
                8192,
            )
        model["max_chunk_size"] = st.number_input(
            "Max Chunk Size:",
            help=state.optimizer_help["chunk_size"],
            min_value=0,
            key="add_model_max_chunk_size",
            value=max_chunk_size,
            disabled=not is_authenticated(),
        )

    return model


def _handle_dialog_submission(model: dict, model_type: str, action: str, original_model: dict | None = None) -> bool:
    """Handle dialog form submission and return True if successful."""
    authenticated = is_authenticated()
    action_button, delete_button, cancel_button = st.columns([1.5, 7, 1.5])
    try:
        if action == "add" and action_button.button(
            label="Add", type="primary", width="stretch", disabled=not authenticated
        ):
            if not model.get("id") or not model.get("provider"):
                if not model.get("id"):
                    st.error("Model name is required.")
                if not model.get("provider"):
                    st.error("Provider name is required.")
                return False
            success = _handle_form_submit(model_type, True, model["provider"], model["id"], model)
            return success

        if action == "edit" and action_button.button(
            label="Save", type="primary", width="stretch", disabled=not authenticated
        ):
            success = _handle_form_submit(
                model_type,
                False,
                model["provider"],
                model["id"],
                model,
                original_model=original_model,
            )
            return success

        if action != "add" and delete_button.button(
            label="Delete", type="secondary", width="content", disabled=not authenticated
        ):
            success = _remove_model(model["provider"], model["id"])
            return success

    except httpx.HTTPStatusError as exc:
        st.error(f"Failed to {action} model: {helpers.extract_error_detail(exc)}")

    if cancel_button.button(label="Cancel", type="secondary", width="stretch"):
        st.rerun()

    return False


#####################################################
# Dialog
#####################################################
@st.dialog("Model Configuration", width="large")
def edit_model(
    model_type: str, action: Literal["add", "edit"], model_id: str | None = None, model_provider: str | None = None
) -> None:
    """Model Edit Dialog Box."""
    model = _initialize_model(action, model_type, model_id, model_provider)
    original_model = dict(model) if action == "edit" else None
    if action == "edit":
        model["enabled"] = st.checkbox(
            "Enabled",
            value=model.get("enabled", False),
            disabled=not is_authenticated(),
        )
    supported_models = _get_supported_models(model_type)

    model, provider_models, disable_for_oci = _render_provider_selection(model, supported_models, action)
    model = _render_model_selection(model, provider_models, action)
    model = _render_api_configuration(model, provider_models, disable_for_oci)
    model = _render_model_specific_config(model, model_type, provider_models)

    if _handle_dialog_submission(model, model_type, action, original_model=original_model):
        st.rerun()


#####################################################
# Pull Dialog
#####################################################
@st.dialog("Pull Ollama Model")
def pull_model_dialog(provider: str, model_id: str) -> None:
    """Stream Ollama model pull progress."""
    st.write(f"Pulling **{provider}/{model_id}** from Ollama registry...")
    quoted_id = urllib.parse.quote(model_id, safe="")
    status_text = st.empty()
    progress_bar = st.empty()

    try:
        for event in api_post_stream(f"models/pull/{provider}/{quoted_id}"):
            if "error" in event:
                st.error(f"Pull failed: {event['error']}")
                return
            status = event.get("status", "")
            completed = event.get("completed", 0)
            total = event.get("total", 0)
            if total > 0:
                progress_bar.progress(completed / total, text=status)
            else:
                status_text.text(status)
    except httpx.HTTPStatusError as exc:
        st.error(f"Pull failed: {helpers.extract_error_detail(exc)}")
        return

    helpers.refresh_settings()
    st.success(f"Model **{model_id}** pulled successfully.")


#####################################################
# Table Display
#####################################################
def render_model_rows(model_type: str) -> None:
    """Render rows of the models."""
    models = [m for m in state["settings"]["model_configs"] if m.get("type") == model_type]
    data_col_widths = [0.06, 0.40, 0.34, 0.10, 0.10]

    header_cols = st.columns(data_col_widths, vertical_alignment="center")
    header_cols[0].markdown("&#x200B;", unsafe_allow_html=True, width="content")
    header_cols[1].markdown("**<u>Model</u>**", unsafe_allow_html=True)
    header_cols[2].markdown("**<u>Provider URL</u>**", unsafe_allow_html=True)
    header_cols[3].markdown("&#x200B;")
    header_cols[4].markdown("&#x200B;")

    for model in models:
        model_id = model["id"]
        model_provider = model["provider"]
        enabled = model.get("enabled", False)
        row = st.columns(data_col_widths, vertical_alignment="center")
        row[0].text_input(
            "Enabled",
            value=helpers.bool_to_emoji(enabled),
            key=f"runtime_{model_type}_{model_provider}_{model_id}_{enabled}",
            label_visibility="collapsed",
            disabled=True,
        )
        row[1].text_input(
            "Model",
            value=f"{model_provider}/{model_id}",
            key=f"runtime_{model_type}_{model_provider}_{model_id}",
            label_visibility="collapsed",
            disabled=True,
        )
        row[2].text_input(
            "Server",
            value=model.get("api_base", ""),
            key=f"runtime_{model_type}_{model_provider}_{model_id}_api_base",
            label_visibility="collapsed",
            disabled=True,
        )
        row[3].button(
            "Edit",
            on_click=edit_model,
            key=f"runtime_{model_type}_{model_provider}_{model_id}_edit",
            kwargs={
                "model_type": model_type,
                "action": "edit",
                "model_id": model_id,
                "model_provider": model_provider,
            },
        )
        if model_provider == "ollama" and not model.get("usable", False):
            row[4].button(
                "Pull",
                on_click=pull_model_dialog,
                key=f"runtime_{model_type}_{model_provider}_{model_id}_pull",
                kwargs={"provider": model_provider, "model_id": model_id},
                disabled=not is_authenticated(),
            )

    if st.button(label="Add", type="primary", key=f"add_{model_type}_model", disabled=not is_authenticated()):
        edit_model(model_type=model_type, action="add")


#####################################################
# MAIN
#####################################################
def display_models() -> None:
    """Streamlit GUI"""
    locked_notice()
    st.subheader("Language", divider="red")
    with st.container(border=True):
        render_model_rows("ll")

    st.divider()
    st.subheader("Embedding", divider="red")
    with st.container(border=True):
        render_model_rows("embed")
