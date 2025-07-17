"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script initializes a web interface for setting the chatbot instr using Streamlit (`st`).

Session States Set:
- prompt_configs: Stores all Prompt Examples
"""
# spell-checker:ignore selectbox

import inspect
import time

import streamlit as st
from streamlit import session_state as state

import client.utils.st_common as st_common
import client.utils.api_call as api_call
import common.logging_config as logging_config
from client.utils.st_footer import remove_footer

logger = logging_config.logging.getLogger("client.tools.prompt_eng")


#####################################################
# Functions
#####################################################
def get_prompts(force: bool = False) -> dict[str, dict]:
    """Get a dictionary of all Prompts"""
    if "prompt_configs" not in state or state.prompt_configs == {} or force:
        try:
            state.prompt_configs = api_call.get(endpoint="v1/prompts")
            logger.info("State created: state['prompt_configs']")
        except api_call.ApiError as ex:
            logger.error("Unable to retrieve prompts: %s", ex)
            state.prompt_configs = {}


def patch_prompt(category: str, name: str, prompt: str) -> None:
    """Update Prompt Instructions"""
    get_prompts()
    # Check if the prompt instructions are changed
    configured_prompt = next(
        item["prompt"] for item in state.prompt_configs if item["name"] == name and item["category"] == category
    )
    if configured_prompt != prompt:
        try:
            _ = api_call.patch(
                endpoint=f"v1/prompts/{category}/{name}",
                payload={"json": {"prompt": prompt}},
            )
            logger.info("Prompt updated: %s (%s)", name, category)
            st_common.clear_state_key(f"selected_prompt_{category}_name")
            st_common.clear_state_key(f"prompt_{category}_prompt")
            st_common.clear_state_key("prompt_configs")
            get_prompts(force=True)  # Refresh the Config
        except api_call.ApiError as ex:
            logger.error("Prompt not updated: %s (%s): %s", name, category, ex)
    else:
        st.info(f"{name} ({category}) Prompt Instructions - No Changes Detected.", icon="ℹ️")
        time.sleep(2)


#############################################################################
# MAIN
#############################################################################
def main():
    """Streamlit GUI"""
    remove_footer()
    st.header("Prompt Engineering")
    st.write("Select which prompts to use and their instructions.  Currently selected prompts are used.")
    try:
        get_prompts()  # Create/Rebuild state
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
            on_change=st_common.update_user_settings("prompts"),
        )
        prompt_sys_prompt = st.text_area(
            "System Instructions:",
            value=sys_dict[selected_prompt_sys_name],
            height=150,
            key="prompt_sys_prompt",
        )
        if st.button("Save Instructions", key="save_sys_prompt"):
            patch_prompt("sys", selected_prompt_sys_name, prompt_sys_prompt)

    st.subheader("Context Prompt")
    ctx_dict = {item["name"]: item["prompt"] for item in state.prompt_configs if item["category"] == "ctx"}
    with st.container(border=True):
        selected_prompt_ctx_name = st.selectbox(
            "Current Context Prompt: ",
            options=list(ctx_dict.keys()),
            index=list(ctx_dict.keys()).index(state.client_settings["prompts"]["ctx"]),
            key="selected_prompts_ctx",
            on_change=st_common.update_user_settings("prompts"),
        )
        prompt_ctx_prompt = st.text_area(
            "Context Instructions:",
            value=ctx_dict[selected_prompt_ctx_name],
            height=150,
            key="prompt_ctx_prompt",
        )
        if st.button("Save Instructions", key="save_ctx_prompt"):
            patch_prompt("ctx", selected_prompt_ctx_name, prompt_ctx_prompt)


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
