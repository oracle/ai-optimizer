"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import json
import logging
from datetime import datetime

import streamlit as st
from streamlit import session_state as state

from client.app.core.api import get_server_settings

LOGGER = logging.getLogger("content.config.tabs.settings")


#############################################################################
# Functions
#############################################################################
def _get_settings_data() -> str:
    """Return settings JSON for download.

    When 'Include Sensitive Settings' is checked, re-fetches from the server
    with ``include_secrets=True`` so the download contains the full payload.
    Otherwise, returns ``state.settings`` as-is (which mirrors the server's
    non-secret response).
    """
    if state.get("runtime_sensitive_settings", False):
        settings_with_secrets = get_server_settings(include_secrets=True)
        if settings_with_secrets is not None:
            return json.dumps(settings_with_secrets, indent=2)
    return json.dumps(state.settings, indent=2)


def _compute_diff(uploaded: dict, current: dict, prefix: str = "") -> list[dict]:
    """Compare uploaded settings against current settings.

    Returns a list of dicts with 'key', 'server', and 'uploaded' for each
    difference found, walking nested dicts recursively.
    """
    diffs = []
    all_keys = sorted(set(list(uploaded.keys()) + list(current.keys())))
    for key in all_keys:
        full_key = f"{prefix}.{key}" if prefix else key
        in_uploaded = key in uploaded
        in_current = key in current

        if in_uploaded and not in_current:
            diffs.append({"key": full_key, "server": "—", "uploaded": uploaded[key]})
        elif in_current and not in_uploaded:
            diffs.append({"key": full_key, "server": current[key], "uploaded": "—"})
        elif isinstance(uploaded[key], dict) and isinstance(current[key], dict):
            diffs.extend(_compute_diff(uploaded[key], current[key], prefix=full_key))
        elif uploaded[key] != current[key]:
            diffs.append(
                {
                    "key": full_key,
                    "server": current[key],
                    "uploaded": uploaded[key],
                }
            )
    return diffs


def _render_upload_settings_section() -> None:
    uploaded_file = st.file_uploader(
        "Upload Settings JSON",
        type=["json"],
        key="runtime_settings_file_uploader",
    )
    if uploaded_file is not None:
        try:
            uploaded_data = json.loads(uploaded_file.read())
        except (json.JSONDecodeError, UnicodeDecodeError):
            st.error("Invalid JSON file.")
            return

        diffs = _compute_diff(uploaded_data, state.settings)
        if not diffs:
            st.info("Settings match the server.")
        else:
            st.warning(f"{len(diffs)} difference(s) found.")
            st.dataframe(
                diffs,
                column_config={
                    "key": st.column_config.TextColumn("Setting"),
                    "server": st.column_config.TextColumn("Server Value"),
                    "uploaded": st.column_config.TextColumn("Uploaded Value"),
                },
                width="stretch",
                hide_index=True,
            )


def _render_download_settings_section() -> None:
    col_left, col_centre, _ = st.columns([3, 4, 3])
    now = datetime.now()
    filename = f"optimizer_settings_{now.strftime('%Y%m%d_%H%M%S')}.json"
    col_centre.checkbox(
        "Include Sensitive Settings",
        key="runtime_sensitive_settings",
        help="Include API Keys and Passwords in Download",
    )
    col_left.download_button(
        label="📥 Download Settings",
        data=_get_settings_data(),
        file_name=filename,
        mime="application/json",
        key="download_settings",
    )


#####################################################
# MAIN
#####################################################
def display_settings():
    """Streamlit GUI"""
    st.header("Optimizer Settings", divider="red")

    upload_settings = st.toggle(
        "Upload",
        key="runtime_settings_upload",
        value=False,
        help="Save or Upload Client Settings.",
    )

    if upload_settings:
        _render_upload_settings_section()
    else:
        _render_download_settings_section()

    st.write(state)
