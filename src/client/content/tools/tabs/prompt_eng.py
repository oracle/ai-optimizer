"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes a web interface for setting the chatbot instr using Streamlit (`st`).

Session States Set:
- prompt_configs: Stores all Prompt Examples
"""
# spell-checker:ignore selectbox

import json
import time
from datetime import datetime

import streamlit as st
from streamlit import session_state as state

from client.utils import st_common, api_call
from common import logging_config

logger = logging_config.logging.getLogger("client.tools.tabs.prompt_eng")


#####################################################
# Functions
#####################################################
def get_prompts(force: bool = False) -> None:
    """Get Prompts from API Server"""
    if force or "prompt_configs" not in state or not state.prompt_configs:
        try:
            logger.info("Refreshing state.prompt_configs")
            state.prompt_configs = api_call.get(endpoint="v1/mcp/prompts", params={"full": True})
        except api_call.ApiError as ex:
            logger.error("Unable to populate state.prompt_configs: %s", ex)
            state.prompt_configs = []


def _get_prompt_name(prompt_title: str) -> str:
    return next((item["name"] for item in state.prompt_configs if item["title"] == prompt_title), None)


def get_prompt_instructions() -> str:
    """Retrieve selected prompt instructions from cached configs"""
    logger.info("Retrieving Prompt Instructions for %s", state.selected_prompt)
    try:
        prompt = next((item for item in state.prompt_configs if item["title"] == state.selected_prompt), None)
        if prompt:
            state.selected_prompt_instructions = prompt.get("text", "")
        else:
            logger.warning("Prompt %s not found in configs", state.selected_prompt)
            state.selected_prompt_instructions = ""
    except Exception as ex:
        logger.error("Unable to retrieve prompt instructions: %s", ex)
        st_common.clear_state_key("selected_prompt_instructions")


def patch_prompt(new_prompt_instructions: str) -> bool:
    """Update Prompt Instructions"""
    rerun = False

    # Check if the prompt instructions are changed
    if state.selected_prompt_instructions == new_prompt_instructions:
        st.info("Prompt Instructions - No Changes Detected.", icon="ℹ️")
        return rerun

    try:
        prompt_name = _get_prompt_name(state.selected_prompt)
        response = api_call.patch(
            endpoint=f"v1/mcp/prompts/{prompt_name}",
            payload={"json": {"instructions": new_prompt_instructions}},
        )
        logger.info(response)
        rerun = True
    except api_call.ApiError as ex:
        st.error(f"Prompt not updated: {ex}")
        logger.error("Prompt not updated: %s", ex)
        rerun = False
    st_common.clear_state_key("prompt_configs")

    return rerun


def save_all_prompts() -> str:
    """Export all prompts to JSON format"""
    try:
        # Refresh prompts to get latest data
        get_prompts(force=True)

        now = datetime.now()
        saved_time = now.strftime("%d-%b-%YT%H%M").upper()

        prompts_data = {"export_timestamp": saved_time, "prompts": state.prompt_configs}

        return json.dumps(prompts_data, indent=2)
    except Exception as ex:
        logger.error("Failed to export prompts: %s", ex)
        st.error(f"Failed to export prompts: {ex}")
        return ""


def apply_uploaded_prompts(uploaded_file) -> None:
    """Import prompts from uploaded JSON file"""
    try:
        # Parse uploaded JSON
        uploaded_data = json.loads(uploaded_file.read().decode("utf-8"))

        # Extract prompts from the uploaded data
        uploaded_prompts = uploaded_data.get("prompts", [])
        if not uploaded_prompts:
            st.error("No prompts found in uploaded file")
            return

        # Validate prompt structure
        for prompt in uploaded_prompts:
            if not all(key in prompt for key in ["name", "text"]):
                st.error(f"Invalid prompt structure in uploaded file. Missing required fields: {prompt}")
                return

        # Apply each prompt override
        success_count = 0
        for prompt in uploaded_prompts:
            try:
                api_call.patch(
                    endpoint=f"v1/mcp/prompts/{prompt['name']}",
                    payload={"json": {"instructions": prompt["text"]}},
                )
                logger.info("Updated prompt: %s", prompt["name"])
                success_count += 1
            except api_call.ApiError as ex:
                logger.warning("Failed to update prompt %s: %s", prompt["name"], ex)
                st.warning(f"Failed to update prompt '{prompt['name']}': {ex}")

        if success_count > 0:
            st.success(f"Successfully imported {success_count} prompt(s)", icon="✅")
            # Clear cache and refresh
            st_common.clear_state_key("prompt_configs")
            time.sleep(1)  # Brief pause for cache to update
            return
        st.error("No prompts were successfully imported")
    except json.JSONDecodeError:
        st.error("Invalid JSON file format")
    except Exception as ex:
        logger.error("Failed to import prompts: %s", ex)
        st.error(f"Failed to import prompts: {ex}")


def reset_all_prompts() -> bool:
    """Reset all prompts to their default values"""
    try:
        response = api_call.post(endpoint="v1/mcp/prompts/reset")
        logger.info("Reset prompts response: %s", response)
        st.toast(response["message"], icon="✅")

        # Clear cache and refresh
        st_common.clear_state_key("prompt_configs")
        time.sleep(1)  # Brief pause for cache to update
        return True

    except api_call.ApiError as ex:
        st.error(f"Failed to reset prompts: {ex}")
        logger.error("Failed to reset prompts: %s", ex)
        return False


#############################################################################
# MAIN
#############################################################################
def display_prompt_eng():
    """Streamlit GUI"""
    st.header("Prompt Engineering")
    st.write("Review/Edit System Prompts and their Instructions.")
    try:
        get_prompts()
    except api_call.ApiError:
        st.stop()

    all_prompts = st_common.state_configs_lookup("prompt_configs", "title")
    if "selected_prompt_instructions" not in state:
        if "selected_prompt" not in state:
            state.selected_prompt = list(all_prompts.keys())[0]
        get_prompt_instructions()
    with st.container(border=True, height="stretch"):
        st.selectbox(
            "Select Prompt: ",
            options=list(all_prompts.keys()),
            key="selected_prompt",
            on_change=get_prompt_instructions,
        )
        st.text_area(
            "Description:", value=all_prompts[state.selected_prompt]["description"], height="content", disabled=True
        )
        new_prompt_instructions = st.text_area(
            "System Instructions:", value=state.selected_prompt_instructions, height="content"
        )
        if st.button("Save Instructions", key="save_sys_prompt"):
            if patch_prompt(new_prompt_instructions):
                st.rerun()

    # Bulk operations section
    st.header("Bulk Prompt Operations", divider="red")
    col_left, col_right = st.columns([8, 2])
    upload_prompts = col_left.toggle(
        "Upload", key="selected_upload_prompts", value=False, help="Save or Upload Prompts.", width="stretch"
    )
    with col_right:
        if st.button(
            "🔄 Reset Prompts", key="reset_prompts", help="Reset all prompts to their default values", width="stretch"
        ):
            if reset_all_prompts():
                st.rerun()

    if not upload_prompts:
        prompts_json = save_all_prompts()
        now = datetime.now()
        filename = f"optimizer_prompts_{now.strftime('%Y%m%d_%H%M%S')}.json"
        st.download_button(
            label="📥 Download Prompts",
            data=prompts_json,
            file_name=filename,
            mime="application/json",
            key="download_prompts",
        )
    else:
        uploaded_file = st.file_uploader(
            "Upload Prompts",
            type="json",
            key="upload_prompts_file",
            help="Upload a JSON file containing prompts to import",
        )
        if uploaded_file is not None:
            if st.button(
                "📤 Upload Prompts",
                key="upload_prompts",
                help="Import prompts from the uploaded JSON file",
            ):
                apply_uploaded_prompts(uploaded_file)
                time.sleep(3)
                st.rerun()


if __name__ == "__main__":
    display_prompt_eng()
