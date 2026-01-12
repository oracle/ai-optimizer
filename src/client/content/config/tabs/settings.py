"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script allows importing/exporting configurations using Streamlit (`st`).
"""

# spell-checker:ignore streamlit mvnw obaas ollama vllm

import time
import os
import io
import json
import tempfile
import zipfile
import shutil
from pathlib import Path
from datetime import datetime

import yaml

# Streamlit
import streamlit as st
from streamlit import session_state as state

# Utilities
from client.utils import api_call, st_common
from client.content.config.tabs.models import get_models

from common import logging_config

logger = logging_config.logging.getLogger("client.content.config.tabs.settings")


#############################################################################
# Functions
#############################################################################


def _handle_key_comparison(
    key: str,
    current: dict,
    uploaded: dict,
    differences: dict,
    new_path: str,
    sensitive_keys: set,
) -> None:
    """Handle comparison for a single key between current and uploaded settings."""
    is_sensitive = key in sensitive_keys

    if key not in current:
        if is_sensitive:
            differences["Override on Upload"][new_path] = "present in uploaded only"
        else:
            differences["Missing in Current"][new_path] = {"uploaded": uploaded[key]}
    elif key not in uploaded:
        if is_sensitive:
            # Silently update uploaded to match current
            uploaded[key] = current[key]
        else:
            differences["Missing in Uploaded"][new_path] = {"current": current[key]}
    else:
        # Both present — compare
        if is_sensitive:
            if current[key] != uploaded[key]:
                differences["Value Mismatch"][new_path] = {
                    "current": current[key],
                    "uploaded": uploaded[key],
                }
        else:
            child_diff = compare_settings(current[key], uploaded[key], new_path)
            for diff_type, diff_dict in differences.items():
                diff_dict.update(child_diff[diff_type])


def _render_download_settings_section() -> None:
    """Render the download settings section."""
    settings = get_settings(state.selected_sensitive_settings)
    st.json(settings, expanded=False)
    col_left, col_centre, _ = st.columns([3, 4, 3])
    now = datetime.now()
    filename = f"optimizer_settings_{now.strftime('%Y%m%d_%H%M%S')}.json"
    col_left.download_button(
        label="📥 Download Settings",
        data=save_settings(settings),
        file_name=filename,
        mime="application/json",
        key="download_settings",
    )
    col_centre.checkbox(
        "Include Sensitive Settings",
        key="selected_sensitive_settings",
        help="Include API Keys and Passwords in Download",
    )


def _render_upload_settings_section() -> None:
    """Render the upload settings section."""
    uploaded_file = st.file_uploader("Upload the Settings file", type="json")
    if uploaded_file is not None:
        uploaded_settings = json.loads(uploaded_file.read().decode("utf-8"))
        try:
            settings = get_settings(True)
            logger.info("Comparing Settings between Current and Uploaded")
            differences = compare_settings(current=settings, uploaded=uploaded_settings)
            # Remove empty difference groups
            differences = {k: v for k, v in differences.items() if v}
            # Show differences
            if differences:
                st.subheader("Differences found:")
                st.json(differences, expanded=True)
                if st.button(
                    "📤 Apply New Settings",
                    key="upload_settings",
                    help="Import settings from the uploaded JSON file",
                ):
                    apply_uploaded_settings(uploaded_settings)
                    time.sleep(3)
                    st.rerun()
            else:
                st.write("No differences found. The current configuration matches the saved settings.")
        except json.JSONDecodeError:
            st.error("Error: The uploaded file is not a valid.")
    else:
        st.info("Please upload a Settings file.")


def _get_model_configs() -> tuple[dict, dict, str]:
    """Get model configurations and determine Spring AI config type.

    Returns:
        tuple: (ll_config, embed_config, spring_ai_conf)
    """
    try:
        model_lookup = st_common.enabled_models_lookup(model_type="ll")
        ll_config = model_lookup[state.client_settings["ll_model"]["model"]] | state.client_settings["ll_model"]
    except KeyError:
        ll_config = {}

    try:
        model_lookup = st_common.enabled_models_lookup(model_type="embed")
        embed_config = (
            model_lookup[state.client_settings["vector_search"]["model"]] | state.client_settings["vector_search"]
        )
    except KeyError:
        embed_config = {}

    spring_ai_conf = spring_ai_conf_check(ll_config, embed_config)
    return ll_config, embed_config, spring_ai_conf


def _render_source_code_templates_section() -> None:
    """Render the source code templates section."""
    st.header("Source Code Templates", divider="red")

    ll_config, embed_config, spring_ai_conf = _get_model_configs()
    logger.info("config found: %s", spring_ai_conf)

    if spring_ai_conf == "hybrid":
        st.markdown(
            f"""
            The current configuration combination of embedding and language models
            is currently **not supported** for Spring AI and LangChain MCP templates.
            - Language Model:  **{ll_config.get("model", "Unset")}**
            - Embedding Model: **{embed_config.get("model", "Unset")}**
        """
        )
    else:
        settings = get_settings(state.selected_sensitive_settings)
        col_left, col_centre, _ = st.columns([3, 4, 3])
        with col_left:
            st.download_button(
                label="Download LangchainMCP",
                data=langchain_mcp_zip(settings),  # Generate zip on the fly
                file_name="langchain_mcp.zip",  # Zip file name
                mime="application/zip",  # Mime type for zip file
                disabled=spring_ai_conf == "hybrid",
            )
        with col_centre:
            if spring_ai_conf != "hosted_vllm":
                st.download_button(
                    label="Download SpringAI",
                    data=spring_ai_zip(spring_ai_conf, ll_config, embed_config),  # Generate zip on the fly
                    file_name="spring_ai.zip",  # Zip file name
                    mime="application/zip",  # Mime type for zip file
                    disabled=spring_ai_conf == "hybrid",
                )


def get_settings(include_sensitive: bool = False):
    """Get Server-Side Settings"""
    try:
        settings = api_call.get(
            endpoint="v1/settings",
            params={
                "client": state.client_settings["client"],
                "full_config": True,
                "incl_sensitive": include_sensitive,
            },
        )
        return settings
    except api_call.ApiError as ex:
        if "not found" in str(ex):
            # If client settings not found, create them
            logger.info("Client settings not found, creating new ones")
            api_call.post(
                endpoint="v1/settings",
                params={"client": state.client_settings["client"]},
            )
            settings = api_call.get(
                endpoint="v1/settings",
                params={
                    "client": state.client_settings["client"],
                    "full_config": True,
                    "incl_sensitive": include_sensitive,
                },
            )
            return settings
        raise


def save_settings(settings):
    """Save Settings after changing client"""

    now = datetime.now()
    saved_time = now.strftime("%d-%b-%YT%H%M").upper()

    if "client_settings" in settings and "client" in settings["client_settings"]:
        settings["client_settings"]["client"] = saved_time

    return json.dumps(settings, indent=2)


def _compare_prompt_configs(current_prompts, uploaded_prompts):
    """Compare prompt configs by name and text.

    Returns:
        dict: Dictionary of prompt differences
    """
    current_by_name = {p["name"]: p for p in current_prompts}
    uploaded_by_name = {p["name"]: p for p in uploaded_prompts}

    prompt_diffs = {}
    for name in set(current_by_name.keys()) | set(uploaded_by_name.keys()):
        current_prompt = current_by_name.get(name)
        uploaded_prompt = uploaded_by_name.get(name)

        if not current_prompt:
            prompt_diffs[name] = {
                "status": "Missing in Current",
                "uploaded_text": uploaded_prompt.get("text"),
            }
        elif not uploaded_prompt:
            prompt_diffs[name] = {
                "status": "Missing in Uploaded",
                "current_text": current_prompt.get("text"),
            }
        elif current_prompt.get("text") != uploaded_prompt.get("text"):
            prompt_diffs[name] = {
                "status": "Text differs",
                "current_text": current_prompt.get("text"),
                "uploaded_text": uploaded_prompt.get("text"),
            }

    return prompt_diffs


def _compare_dicts(current, uploaded, path, differences, sensitive_keys):
    """Compare two dictionaries and record differences."""
    keys = set(current.keys()) | set(uploaded.keys())
    for key in keys:
        new_path = f"{path}.{key}" if path else key

        # Skip specific paths
        if new_path == "client_settings.client" or new_path.endswith(".created"):
            continue

        # Special handling for prompt_configs
        if new_path == "prompt_configs":
            current_prompts = current.get(key) or []
            uploaded_prompts = uploaded.get(key) or []
            prompt_diffs = _compare_prompt_configs(current_prompts, uploaded_prompts)
            if prompt_diffs:
                differences["Value Mismatch"][new_path] = prompt_diffs
            continue

        _handle_key_comparison(key, current, uploaded, differences, new_path, sensitive_keys)


def _compare_lists(current, uploaded, path, differences):
    """Compare two lists and record differences."""
    min_len = min(len(current), len(uploaded))

    for i in range(min_len):
        new_path = f"{path}[{i}]"
        child_diff = compare_settings(current[i], uploaded[i], new_path)
        for diff_type, diff_dict in differences.items():
            diff_dict.update(child_diff[diff_type])

    for i in range(min_len, len(current)):
        new_path = f"{path}[{i}]"
        differences["Missing in Uploaded"][new_path] = {"current": current[i]}

    for i in range(min_len, len(uploaded)):
        new_path = f"{path}[{i}]"
        differences["Missing in Current"][new_path] = {"uploaded": uploaded[i]}


def compare_settings(current, uploaded, path=""):
    """Compare current settings with uploaded settings."""
    differences = {
        "Value Mismatch": {},
        "Missing in Uploaded": {},
        "Missing in Current": {},
        "Override on Upload": {},
    }
    sensitive_keys = {"api_key", "password", "wallet_password"}

    if isinstance(current, dict) and isinstance(uploaded, dict):
        _compare_dicts(current, uploaded, path, differences, sensitive_keys)
    elif isinstance(current, list) and isinstance(uploaded, list):
        _compare_lists(current, uploaded, path, differences)
    elif current != uploaded:
        differences["Value Mismatch"][path] = {
            "current": current,
            "uploaded": uploaded,
        }

    return differences


def apply_uploaded_settings(uploaded) -> None:
    """Patch configuration to update the server side"""
    client_id = state.client_settings["client"]
    try:
        response = api_call.post(
            endpoint="v1/settings/load/json",
            params={"client": client_id},
            payload={"json": uploaded},
            timeout=7200,
        )
        st.success(response["message"], icon="✅")
        state.client_settings = api_call.get(endpoint="v1/settings", params={"client": client_id})
        # Clear all *_configs states so they are refreshed on rerun
        for key in list(state.keys()):
            if key.endswith("_configs"):
                st_common.clear_state_key(key)
    except api_call.ApiError as ex:
        st.error(f"Settings for {state.client_settings['client']} - Update Failed", icon="❌")
        logger.error("%s Settings Update failed: %s", state.client_settings["client"], ex)


def spring_ai_conf_check(ll_model: dict, embed_model: dict) -> str:
    """Check if configuration is valid for SpringAI package"""
    if not ll_model or not embed_model:
        return "hybrid"

    ll_provider = ll_model.get("provider", "")
    embed_provider = embed_model.get("provider", "")
    logger.info("llm chat: %s - embeddings: %s", ll_provider, embed_provider)
    if all("hosted_vllm" in p for p in (ll_provider, embed_provider)):
        return "hosted_vllm"
    if all("openai" in p for p in (ll_provider, embed_provider)):
        return "openai"
    if all("ollama" in p for p in (ll_provider, embed_provider)):
        return "ollama"

    return "hybrid"


def spring_ai_obaas(src_dir, file_name, provider, ll_config, embed_config):
    """Get the system prompt for SpringAI export"""

    ## FUTURE FEATURE:
    # Determine which system prompt would be active based on tools_enabled
    # tools_enabled = state.client_settings.get("tools_enabled", [])

    # Select prompt name based on tools configuration
    # if not tools_enabled:
    #     prompt_name = "optimizer_basic-default"
    #     if state.client_settings["vector_search"]["enabled"]:
    #         prompt_name = "optimizer_vs-no-tools-default"
    # else:
    #     # Tools are enabled, use tools-default prompt
    #     prompt_name = "optimizer_tools-default"
    ## Legacy Feature:
    if "Vector Search" in state.client_settings.get("tools_enabled", []):
        prompt_name = "optimizer_vs-tools-default"
    else:
        prompt_name = "optimizer_basic-default"

    # Find the prompt in configs
    sys_prompt_obj = next((item for item in state.prompt_configs if item["name"] == prompt_name), None)

    if sys_prompt_obj:
        # Use the effective text (already resolved to override or default)
        sys_prompt = sys_prompt_obj.get("text")
    else:
        # Fallback to basic prompt if not found
        logger.warning("Prompt %s not found in configs, using fallback", prompt_name)
        sys_prompt = "You are a helpful assistant."

    logger.info("Prompt used in export (%s):\n%s", prompt_name, sys_prompt)
    with open(src_dir / "templates" / file_name, "r", encoding="utf-8") as template:
        template_content = template.read()

    database_lookup = st_common.state_configs_lookup("database_configs", "name")

    logger.info(
        "Database Legacy User:%s",
        database_lookup[state.client_settings["database"]["alias"]]["user"],
    )

    formatted_content = template_content.format(
        provider=provider,
        sys_prompt=f"{sys_prompt}",
        ll_model=ll_config,
        vector_search=embed_config,
        database_config=database_lookup[state.client_settings.get("database", {}).get("alias")],
    )

    if file_name.endswith(".yaml"):
        # Use yaml.dump to properly escape the sys_prompt for YAML
        # default_flow_style=False creates a properly quoted string
        sys_prompt_escaped = yaml.dump(sys_prompt).rstrip('\n...')  # Remove trailing newline and document end marker

        formatted_content = template_content.format(
            provider=provider,
            sys_prompt=sys_prompt_escaped,
            ll_model=ll_config,
            vector_search=embed_config,
            database_config=database_lookup[state.client_settings.get("database", {}).get("alias")],
        )

        yaml_data = yaml.safe_load(formatted_content)
        if provider == "ollama":
            del yaml_data["spring"]["ai"]["openai"]
            yaml_data["spring"]["ai"]["openai"] = {"chat": {"options": {"model": "_"}}}
        if provider == "openai":
            del yaml_data["spring"]["ai"]["ollama"]
            yaml_data["spring"]["ai"]["ollama"] = {"chat": {"options": {"model": "_"}}}

            # check if is formatting a "obaas" template to override openai base url
            # that causes an issue in obaas with "/v1"

            if (
                file_name.find("obaas") != -1
                and yaml_data["spring"]["ai"]["openai"]["base-url"].find("api.openai.com") != -1
            ):
                yaml_data["spring"]["ai"]["openai"]["base-url"] = "https://api.openai.com"
                logger.info(
                    "in spring_ai_obaas(%s) found openai.base-url and changed with https://api.openai.com",
                    file_name,
                )

        formatted_content = yaml.dump(yaml_data)

    return formatted_content


def spring_ai_zip(provider, ll_config, embed_config):
    """Create SpringAI Zip File"""

    # Source directory that you want to copy
    files = ["mvnw", "mvnw.cmd", "pom.xml", "README.md"]

    src_dir = Path(__file__).resolve().parents[3] / "spring_ai"

    # Using TemporaryDirectory
    with tempfile.TemporaryDirectory() as temp_dir:
        dst_dir = os.path.join(temp_dir, "spring_ai")
        logger.info("Starting SpringAI zip processing: %s", dst_dir)

        shutil.copytree(os.path.join(src_dir, "src"), os.path.join(dst_dir, "src"))
        for item in files:
            shutil.copy(os.path.join(src_dir, item), os.path.join(dst_dir))

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for foldername, _, filenames in os.walk(dst_dir):
                for filename in filenames:
                    file_path = os.path.join(foldername, filename)

                    arc_name = os.path.relpath(file_path, dst_dir)  # Make the path relative
                    zip_file.write(file_path, arc_name)
            env_content = spring_ai_obaas(src_dir, "start.sh", provider, ll_config, embed_config)
            yaml_content = spring_ai_obaas(src_dir, "obaas.yaml", provider, ll_config, embed_config)
            zip_file.writestr("start.sh", env_content.encode("utf-8"))
            zip_file.writestr("src/main/resources/application-obaas.yml", yaml_content.encode("utf-8"))
        zip_buffer.seek(0)
    return zip_buffer


def langchain_mcp_zip(settings):
    """Create LangChain MCP Zip File"""

    # Source directory that you want to copy
    src_dir = Path(__file__).resolve().parents[3] / "mcp/rag"

    # Using TemporaryDirectory
    with tempfile.TemporaryDirectory() as temp_dir:
        dst_dir = os.path.join(temp_dir, "langchain_mcp")
        logger.info("Starting langchain mcp zip processing: %s", dst_dir)

        shutil.copytree(src_dir, dst_dir)

        data = save_settings(settings)
        settings_path = os.path.join(dst_dir, "optimizer_settings.json")
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(data)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for foldername, _, filenames in os.walk(dst_dir):
                for filename in filenames:
                    file_path = os.path.join(foldername, filename)

                    arc_name = os.path.relpath(file_path, dst_dir)  # Make the path relative
                    zip_file.write(file_path, arc_name)
        zip_buffer.seek(0)
    return zip_buffer


#####################################################
# MAIN
#####################################################
def display_settings():
    """Streamlit GUI"""
    try:
        get_models()
    except api_call.ApiError:
        st.stop()

    st.header("Client Settings", divider="red")

    if "selected_sensitive_settings" not in state:
        state.selected_sensitive_settings = False

    upload_settings = st.toggle(
        "Upload",
        key="selected_upload_settings",
        value=False,
        help="Save or Upload Client Settings.",
    )

    if not upload_settings:
        _render_download_settings_section()
    else:
        _render_upload_settings_section()

    _render_source_code_templates_section()


if __name__ == "__main__":
    display_settings()
