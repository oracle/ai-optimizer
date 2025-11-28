"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes a web interface for setting the chatbot instr using Streamlit (`st`).

Session States Set:
- prompt_configs: Stores all Prompt Examples
"""
# spell-checker:ignore selectbox

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


if __name__ == "__main__":
    display_prompt_eng()
