"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore isin mult selectbox

import logging
from typing import Any, Optional

import httpx
import streamlit as st
from streamlit import session_state as state

from client.app.core.api import api_get, api_put, get_server_settings

LOGGER = logging.getLogger("client.core.helpers")


#############################################################################
# State Helpers
#############################################################################
def state_configs_lookup(state_configs_name: str, key: str, section: Optional[str] = None) -> dict[str, dict[str, Any]]:
    """Convert state.<state_configs_name> into a lookup based on key"""
    configs = state["settings"][state_configs_name]
    if section:
        configs = configs.get(section, [])
    return {config[key]: config for config in configs if key in config}


def selectbox_index(options: list, value: Any, default: int = 0) -> int:
    """Return the index of value in options, or default if not found."""
    try:
        return options.index(value)
    except ValueError:
        return default


#############################################################################
# Common Helpers
#############################################################################
def refresh_settings(clear_runtime: bool = True) -> None:
    """Re-fetch settings from server and update session state."""
    settings = get_server_settings(client=state.optimizer_client)
    if settings is not None:
        state.settings = settings
        state.pop("mcp_configs", None)
        # Invalidate per-profile sensitive-field caches on refresh.
        state.pop("_oci_sensitive_loaded", None)
        state.pop("_template_export", None)
        if clear_runtime:
            clear_runtime_state()


def sync_client_setting(key: str, field: str, value: str) -> None:
    """Persist a client_settings change to both session state and the server.

    Args:
        key: Top-level key in client_settings (e.g. "database", "oci").
        field: Field within the nested object (e.g. "alias", "auth_profile").
        value: The new value to set.
    """
    state["settings"]["client_settings"].setdefault(key, {})[field] = value
    try:
        result = api_put(
            "settings",
            json={key: {field: value}},
            params={"client": state.optimizer_client},
        )
        state["settings"]["client_settings"] = result
    except httpx.HTTPStatusError:
        pass


def clear_runtime_state() -> None:
    """Purge all 'runtime_' keys from session state to force widget refresh."""
    for key in list(state.keys()):
        if isinstance(key, str) and key.startswith("runtime_"):
            del state[key]


def build_payload(form_data: dict) -> dict:
    """Build a request payload from form data, excluding None values."""
    return {k: v for k, v in form_data.items() if v is not None}


def extract_error_detail(exc: httpx.HTTPStatusError) -> str:
    """Extract detail message from an HTTP error response."""
    return exc.response.json().get("detail", str(exc)) if exc.response.content else str(exc)


def bool_to_emoji(value: bool) -> str:
    """Convert boolean to emoji for display."""
    return "✅" if value else "❌"


def update_client_settings(payload: dict) -> dict | None:
    """PUT a client_settings update to the server and sync session state.

    Returns the updated client_settings dict on success, or None on error
    (after showing a toast).
    """
    try:
        result = api_put(
            "settings",
            json=payload,
            params={"client": state.optimizer_client},
        )
        state["settings"]["client_settings"] = result
        return result
    except httpx.HTTPStatusError as exc:
        st.toast(extract_error_detail(exc), icon="⚠️")
        return None


def load_chat_history(client_id: str) -> list[dict]:
    """Load conversation history for the given client from the server."""
    try:
        data = api_get("chat/history", extra_headers={"client": client_id})
        return data.get("messages", [])
    except httpx.HTTPError:
        return []


#############################################################################
# Model Helpers
#############################################################################
def unique_file_payload(uploaded_files: Any) -> list[tuple]:
    """Convert Streamlit UploadedFile(s) to de-duplicated multipart form tuples."""
    if not isinstance(uploaded_files, list):
        uploaded_files = [uploaded_files]
    seen: set[str] = set()
    files: list[tuple] = []
    for f in uploaded_files:
        if f.name not in seen:
            seen.add(f.name)
            files.append(("files", (f.name, f.getvalue(), getattr(f, "type", "application/octet-stream"))))
    return files


def enabled_models_lookup(model_type: str) -> dict[str, dict[str, Any]]:
    """Create a lookup of enabled `type` models"""
    all_models = state_configs_lookup("model_configs", "id")
    enabled_models = {
        f"{config.get('provider')}/{id}": config
        for id, config in all_models.items()
        if config.get("type") == model_type and config.get("enabled") is True
    }
    return enabled_models
