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

from common import logging_config

logger = logging_config.logging.getLogger("client.content.config.tabs.settings")


#############################################################################
# Functions
#############################################################################
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
            api_call.post(endpoint="v1/settings", params={"client": state.client_settings["client"]})
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


def compare_settings(current, uploaded, path=""):
    """Compare current settings with uploaded settings."""
    differences = {"Value Mismatch": {}, "Missing in Uploaded": {}, "Missing in Current": {}, "Override on Upload": {}}

    sensitive_keys = {"api_key", "password", "wallet_password"}

    if isinstance(current, dict) and isinstance(uploaded, dict):
        keys = set(current.keys()) | set(uploaded.keys())
        for key in keys:
            new_path = f"{path}.{key}" if path else key

            # Skip specific path
            if new_path == "client_settings.client":
                continue

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
                        differences["Value Mismatch"][new_path] = {"current": current[key], "uploaded": uploaded[key]}
                else:
                    child_diff = compare_settings(current[key], uploaded[key], new_path)
                    for diff_type, diff_dict in differences.items():
                        diff_dict.update(child_diff[diff_type])

    elif isinstance(current, list) and isinstance(uploaded, list):
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

    else:
        if current != uploaded:
            differences["Value Mismatch"][path] = {"current": current, "uploaded": uploaded}

    return differences


def apply_uploaded_settings(uploaded):
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
    """Get the users CTX Prompt"""

    ctx_prompt = next(
        item["prompt"]
        for item in state.prompt_configs
        if item["name"] == state.client_settings["prompts"]["sys"] and item["category"] == "sys"
    )
    logger.info(f"Prompt used in export:\n{ctx_prompt}")
    with open(src_dir / "templates" / file_name, "r", encoding="utf-8") as template:
        template_content = template.read()

    database_lookup = st_common.state_configs_lookup("database_configs", "name")

    formatted_content = template_content.format(
        provider=provider,
        ctx_prompt=f"{ctx_prompt}",
        ll_model=ll_config,
        vector_search=embed_config,
        database_config=database_lookup[state.client_settings["database"]["alias"]],
    )

    if file_name.endswith(".yaml"):
        ctx_prompt = json.dumps(ctx_prompt, indent=True)  # Converts it into a valid JSON string (preserving quotes)

        formatted_content = template_content.format(
            provider=provider,
            ctx_prompt=ctx_prompt,
            ll_model=ll_config,
            vector_search=embed_config,
            database_config=database_lookup[state.client_settings["database"]["alias"]],
        )

        yaml_data = yaml.safe_load(formatted_content)
        if provider == "ollama":
            del yaml_data["spring"]["ai"]["openai"]
        if provider == "openai":
            del yaml_data["spring"]["ai"]["ollama"]
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
        settings = get_settings(state.selected_sensitive_settings)
        st.json(settings, expanded=False)
        col_left, col_centre, _ = st.columns([3, 4, 3])
        col_left.download_button(
            label="Download Settings",
            data=save_settings(settings),
            file_name="optimizer_settings.json",
        )
        col_centre.checkbox(
            "Include Sensitive Settings",
            key="selected_sensitive_settings",
            help="Include API Keys and Passwords in Download",
        )
    else:
        uploaded_file = st.file_uploader("Upload the Settings file", type="json")
        if uploaded_file is not None:
            uploaded_settings = json.loads(uploaded_file.read().decode("utf-8"))
            # Convert the JSON content to a dictionary
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
                    if st.button("Apply New Settings"):
                        apply_uploaded_settings(uploaded_settings)
                        time.sleep(3)
                        st.rerun()
                else:
                    st.write("No differences found. The current configuration matches the saved settings.")
            except json.JSONDecodeError:
                st.error("Error: The uploaded file is not a valid.")
        else:
            st.info("Please upload a Settings file.")

    st.header("Source Code Templates", divider="red")
    # Merge the User Settings into the Model Config
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

    logger.info("config found: %s", spring_ai_conf)

    if spring_ai_conf == "hybrid":
        st.markdown(f"""
            The current configuration combination of embedding and language models
            is currently **not supported** for Spring AI and LangChain MCP templates.
            - Language Model:  **{ll_config.get("model", "Unset")}**
            - Embedding Model: **{embed_config.get("model", "Unset")}**
        """)
    else:
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


if __name__ == "__main__":
    display_settings()
