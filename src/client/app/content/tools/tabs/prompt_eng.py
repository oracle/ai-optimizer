"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectbox

import json
import logging
import time
from datetime import datetime

import httpx
import streamlit as st
from streamlit import session_state as state

from client.app.core import helpers
from client.app.core.api import api_post, api_put

LOGGER = logging.getLogger("client.content.tools.tabs.prompt_eng")


#####################################################
# Functions
#####################################################
def _on_prompt_change() -> None:
    """Callback when the prompt selectbox changes — sync text into state."""
    if "runtime_prompt_titles" not in state:
        return
    state.prompt_eng_selector_index = state.runtime_prompt_titles.index(state.runtime_prompt_eng_selector)


def _get_prompt_name(prompt_title: str) -> str | None:
    """Return the prompt ``name`` that matches *title* in cached settings."""
    lookup = helpers.state_configs_lookup("prompt_configs", "title")
    config = lookup.get(prompt_title)
    return config["name"] if config else None


def _save_prompt(prompt_name: str | None, new_prompt: str | None, current_prompt: str | None) -> None:
    """PUT the updated prompt text to the server and refresh settings."""
    if new_prompt == current_prompt:
        st.toast("No changes detected.", icon="ℹ️")
        return
    try:
        api_put(f"prompts/{prompt_name}", json={"text": new_prompt}, toast="Prompt saved.")
        helpers.refresh_settings()
    except httpx.HTTPStatusError as exc:
        st.error(f"Prompt not saved: {helpers.extract_error_detail(exc)}")


def _reset_prompt(prompt_name: str) -> None:
    """Reset a single prompt to its factory text."""
    try:
        api_post(f"prompts/{prompt_name}/reset", toast="Prompt reset to default.")
        helpers.refresh_settings()
    except httpx.HTTPStatusError as exc:
        st.error(f"Prompt not reset: {helpers.extract_error_detail(exc)}")


def _export_prompts() -> str:
    """Export prompt configs from session state as JSON."""
    prompts = state["settings"].get("prompt_configs", [])
    if not prompts:
        st.warning("No prompt configurations found.")
        return ""
    now = datetime.now()
    return json.dumps(
        {"export_timestamp": now.strftime("%d-%b-%YT%H%M").upper(), "prompt_configs": prompts},
        indent=2,
    )


def _import_prompts(uploaded_file) -> None:
    """Import prompts from an uploaded JSON file via the settings/import endpoint."""
    try:
        uploaded_data = json.loads(uploaded_file.read().decode("utf-8"))
        prompt_configs = uploaded_data.get("prompt_configs", [])
        if not prompt_configs:
            st.toast("No prompt configurations found in uploaded file.", icon="❌")
            return
        result = api_post("settings/import", json={"prompt_configs": prompt_configs})
        section = result.get("prompt_configs", {})
        updated = section.get("updated", 0)
        skipped = section.get("skipped", 0)
        if updated:
            st.toast(f"Imported {updated} prompt(s).", icon="✅")
            helpers.refresh_settings()
        elif skipped:
            st.toast(f"No changes — {skipped} prompt(s) skipped (unchanged or unrecognized).", icon="ℹ️")
        else:
            st.toast("No prompts were imported.", icon="⚠️")
    except json.JSONDecodeError:
        st.toast("Invalid JSON file format.", icon="❌")
    except httpx.HTTPStatusError as exc:
        st.toast(f"Failed to import prompts: {helpers.extract_error_detail(exc)}", icon="❌")


def _reset_all_prompts() -> None:
    """Reset all prompts to factory defaults via bulk reset endpoint."""
    try:
        api_post("prompts/reset", toast="All prompts reset to defaults.")
        helpers.refresh_settings()
    except httpx.HTTPStatusError as exc:
        st.error(f"Failed to reset prompts: {helpers.extract_error_detail(exc)}")


#####################################################
# MAIN
#####################################################
def display_prompt_eng():
    """Streamlit GUI"""
    st.header("Prompt Engineering")
    st.write("Review/Edit System Prompts and their Instructions.")

    prompt_lookup = helpers.state_configs_lookup("prompt_configs", "title")
    state.runtime_prompt_titles = list(prompt_lookup.keys())
    if "prompt_eng_selector_index" not in state:
        state.prompt_eng_selector_index = 0

    with st.container(border=True, height="stretch"):
        selected_title = st.selectbox(
            "Select Prompt:",
            options=state.runtime_prompt_titles,
            index=state.prompt_eng_selector_index,
            key="runtime_prompt_eng_selector",
            on_change=_on_prompt_change,
        )
        current_prompt = prompt_lookup.get(selected_title, {}).get("text")
        st.text_area(
            "Description:",
            value=prompt_lookup[selected_title]["description"],
            key="runtime_prompt_description",
            height="content",
            disabled=True,
        )
        new_prompt = st.text_area(
            "System Instructions:",
            value=current_prompt,
            height="content",
        )
        prompt_name = _get_prompt_name(selected_title)

        save_col, reset_col, _ = st.columns([2, 3, 5])
        save_col.button(
            "Save Instructions",
            key="runtime_save_prompt",
            type="primary",
            width="stretch",
            on_click=_save_prompt,
            kwargs={"prompt_name": prompt_name, "new_prompt": new_prompt, "current_prompt": current_prompt},
        )
        reset_col.button(
            "Reset Instructions",
            key="runtime_reset_prompt",
            on_click=_reset_prompt,
            kwargs={"prompt_name": prompt_name},
        )

    # Bulk operations
    st.header("Bulk Prompt Operations", divider="red")
    col_left, col_right = st.columns([7, 3])
    if "runtime_prompts_upload_toggle" not in state:
        state.runtime_prompts_upload_toggle = False
    upload_prompts = col_left.toggle(
        "Upload",
        key="runtime_prompts_upload_toggle",
        help="Upload Prompts.",
        width="stretch",
    )
    with col_right:
        st.button(
            "Reset All Prompts",
            icon="🔄",
            key="runtime_reset_prompts",
            help="Reset all prompts to their default values",
            width="stretch",
            on_click=_reset_all_prompts,
        )

    if not upload_prompts:
        prompts_json = _export_prompts()
        if prompts_json:
            now = datetime.now()
            filename = f"optimizer_prompts_{now.strftime('%Y%m%d_%H%M%S')}.json"
            st.download_button(
                label="Download Prompts",
                icon="📥",
                data=prompts_json,
                file_name=filename,
                mime="application/json",
                key="runtime_download_prompts",
            )
    else:
        uploaded_file = st.file_uploader(
            "Upload Prompts",
            type="json",
            key="runtime_prompts_upload_file",
            help="Upload a JSON file containing prompts to import",
        )
        if uploaded_file is not None:
            if st.button(
                "Upload Prompts",
                icon="📤",
                key="runtime_upload_prompts",
                help="Import prompts from the uploaded JSON file",
            ):
                _import_prompts(uploaded_file)
                time.sleep(2)
                st.rerun()
