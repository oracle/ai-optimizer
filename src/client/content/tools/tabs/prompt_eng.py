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

import client.utils.st_common as st_common
import client.utils.api_call as api_call

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("client.tools.tabs.prompt_eng")


#####################################################
# Functions
#####################################################
def get_prompts(force: bool = False) -> None:
    """Get Prompts from API Server"""
    if "prompt_configs" not in state or state.prompt_configs == {} or force:
        try:
            logger.info("Refreshing state.prompt_configs")
            state.prompt_configs = api_call.get(endpoint="v1/prompts")
        except api_call.ApiError as ex:
            logger.error("Unable to populate state.prompt_configs: %s", ex)
            state.prompt_configs = {}


def patch_prompt(category: str, name: str, prompt: str) -> bool:
    """Update Prompt Instructions"""
    # Check if the prompt instructions are changed
    rerun = False
    configured_prompt = next(
        item["prompt"] for item in state.prompt_configs if item["name"] == name and item["category"] == category
    )
    if configured_prompt != prompt:
        try:
            rerun = True
            with st.spinner(text="Updating Prompt...", show_time=True):
                _ = api_call.patch(
                    endpoint=f"v1/prompts/{category}/{name}",
                    payload={"json": {"prompt": prompt}},
                )
            logger.info("Prompt updated: %s (%s)", name, category)
        except api_call.ApiError as ex:
            logger.error("Prompt not updated: %s (%s): %s", name, category, ex)
        st_common.clear_state_key("prompt_configs")
    else:
        st.info(f"{name} ({category}) Prompt Instructions - No Changes Detected.", icon="ℹ️")

    return rerun


#############################################################################
# MAIN
#############################################################################
def display_prompt_eng():
    """Streamlit GUI"""
    st.header("Prompt Engineering")
    st.write("Select which prompts to use and their instructions.  Currently selected prompts are used.")
    try:
        get_prompts()
    except api_call.ApiError:
        st.stop()

    st.subheader("System Prompt")
    sys_dict = {item["name"]: item["prompt"] for item in state.prompt_configs if item["category"] == "sys"}
    with st.container(border=True):
        selected_prompt_sys_name = st.selectbox(
            "Current System Prompt: ",
            options=list(sys_dict.keys()),
            index=list(sys_dict.keys()).index(state.client_settings["prompts"]["sys"]),
            key="selected_prompts_sys",
            on_change=st_common.update_client_settings("prompts"),
        )
        prompt_sys_prompt = st.text_area(
            "System Instructions:",
            value=sys_dict[selected_prompt_sys_name],
            height=150,
            key="prompt_sys_prompt",
        )
        if st.button("Save Instructions", key="save_sys_prompt"):
            if patch_prompt("sys", selected_prompt_sys_name, prompt_sys_prompt):
                st.rerun()

    st.subheader("Context Prompt")
    ctx_dict = {item["name"]: item["prompt"] for item in state.prompt_configs if item["category"] == "ctx"}
    with st.container(border=True):
        selected_prompt_ctx_name = st.selectbox(
            "Current Context Prompt: ",
            options=list(ctx_dict.keys()),
            index=list(ctx_dict.keys()).index(state.client_settings["prompts"]["ctx"]),
            key="selected_prompts_ctx",
            on_change=st_common.update_client_settings("prompts"),
        )
        prompt_ctx_prompt = st.text_area(
            "Context Instructions:",
            value=ctx_dict[selected_prompt_ctx_name],
            height=150,
            key="prompt_ctx_prompt",
        )
        if st.button("Save Instructions", key="save_ctx_prompt"):
            if patch_prompt("ctx", selected_prompt_ctx_name, prompt_ctx_prompt):
                st.rerun()


if __name__ == "__main__":
    display_prompt_eng()
