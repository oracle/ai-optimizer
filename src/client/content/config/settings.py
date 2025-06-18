"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This script allows importing/exporting configurations using Streamlit (`st`).
"""
# spell-checker:ignore streamlit, mvnw, obaas, ollama

import inspect
import time
import os
import io
import json
import copy
import tempfile
import zipfile
import shutil
from pathlib import Path
import yaml


# Streamlit
import streamlit as st
from streamlit import session_state as state

# Utilities
from client.content.config.databases import patch_database, get_databases
from client.content.config.oci import patch_oci, get_oci
from client.content.tools.prompt_eng import patch_prompt, get_prompts
from client.content.config.models import patch_model, get_models
from client.utils.st_footer import remove_footer

# Schema
from common.schema import Model

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("client.content.config.settings")

# This is set for inclusion so that exported state is intentional
INCLUDE_KEYS = [
    "user_settings",
    "database_config",
    "oci_config",
    "prompts_config",
    "ll_model_config",
    "embed_model_config",
]


#############################################################################
# Functions
#############################################################################
def save_settings():
    """Save Settings"""

    def empty_key(obj):
        """Return a new object with excluded keys set to empty strings"""
        exclude_keys = ["client", "vector_stores", "connected"]
        if not state.selected_sensitive_settings:
            exclude_keys = exclude_keys + ["api_key", "wallet_password", "password"]

        if isinstance(obj, dict):
            # Create a new dictionary to hold the modified keys
            new_dict = {}
            for key, value in obj.items():
                if key in exclude_keys:
                    new_dict[key] = ""
                else:
                    # Recursively handle nested dictionaries or lists
                    new_dict[key] = empty_key(value)
            return new_dict

        elif isinstance(obj, list):
            # Create a new list to hold the modified items
            return [empty_key(item) for item in obj]

        # If the object is neither a dict nor a list, return it unchanged
        return obj

    state_dict = copy.deepcopy(state)
    state_dict_filter = {key: state_dict[key] for key in INCLUDE_KEYS if key in state_dict}
    state_dict_filter = empty_key(state_dict_filter)
    return json.dumps(state_dict_filter, indent=4)


def compare_dicts_recursive(current, uploaded):
    """Recursively Compare the Session State with the Uploaded Settings"""
    diff = {}
    all_keys = set(current.keys()).union(set(uploaded.keys()))

    for key in all_keys:
        if isinstance(current.get(key), dict) and isinstance(uploaded.get(key), dict):
            # Recursively compare nested dictionaries
            nested_diff = compare_dicts_recursive(current[key], uploaded[key])
            if nested_diff:
                diff[key] = nested_diff
        elif current.get(key) != uploaded.get(key) and uploaded.get(key) != "":
            # Report differences for non-dict values
            diff[key] = {"current": current.get(key), "uploaded": uploaded.get(key)}

    return diff


# Function to compare session state with uploaded JSON, ignoring extra keys in session state
def compare_with_uploaded_json(current_state, uploaded_json):
    """Compare session state with uploaded JSON, ignoring extra keys in session state"""
    diff = {}

    for key in uploaded_json:
        if key in current_state:
            if isinstance(current_state[key], dict) and isinstance(uploaded_json[key], dict):
                nested_diff = compare_dicts_recursive(current_state[key], uploaded_json[key])
                if nested_diff:
                    diff[key] = nested_diff
            elif (current_state[key] or "") != (uploaded_json[key] or ""):
                diff[key] = {"current": current_state[key], "uploaded": uploaded_json[key]}

    return diff


def update_session_state_recursive(session_state, updates):
    """Apply settings to the Session State"""
    for key, value in updates.items():
        if value == "" or value is None:
            # Skip empty string values
            continue

        if isinstance(value, dict):
            if key not in session_state:
                session_state[key] = {}
            update_session_state_recursive(session_state[key], value)
        else:
            # Check if the value is different from the current state before updating
            if key not in session_state or session_state[key] != value:
                logger.info("Setting %s to %s", key, value)
                session_state[key] = value


def update_server(updates):
    """Patch configuration to update the server side"""
    for key, value in updates.items():
        if key == "database_config":
            valid_keys = ["name", "user", "password", "dsn", "wallet_password"]
            for name, config in value.items():
                new_config = {"name": name}
                new_config.update(config)
                new_config = {key: value for key, value in new_config.items() if key in valid_keys}
                patch_database(**new_config)
            continue

        if key == "oci_config":
            valid_keys = [
                "auth_profile",
                "user",
                "fingerprint",
                "tenancy",
                "region",
                "key_file",
                "security_token_file",
            ]
            for profile, config in value.items():
                new_config = {"auth_profile": profile}
                new_config.update(config)
                new_config = {key: value for key, value in new_config.items() if key in valid_keys}
                patch_oci(**new_config)
            continue

        if key == "prompts_config":
            for prompt in value:
                patch_prompt(**prompt)
            continue

        if key in {"ll_model_config", "embed_model_config"}:
            for model_name, config in value.items():
                model = Model(**config, name=model_name)
                patch_model(model)
            continue

def spring_ai_conf_check(ll_model, embed_model) -> str:
    """Check if configuration is valid for SpringAI package"""
    if ll_model is None or embed_model is None:
        return "hybrid"

    ll_api = state.ll_model_enabled[ll_model]["api"]
    embed_api = state.embed_model_enabled[embed_model]["api"]

    if "OpenAI" in ll_api and "OpenAI" in embed_api:
        return "openai"
    elif ll_api == "ChatOllama" and "Ollama" in embed_api:
        return "ollama"

    return "hybrid"


def spring_ai_obaas(src_dir, file_name, provider, ll_model):
    """Get the users CTX Prompt"""
    ctx_prompt = next(
        item["prompt"]
        for item in state.prompts_config
        if item["name"] == state.user_settings["prompts"]["ctx"] and item["category"] == "ctx"
    )

    with open(src_dir / "templates" / file_name, "r", encoding="utf-8") as template:
        template_content = template.read()

    formatted_content = template_content.format(
        provider=provider,
        ctx_prompt=f"{ctx_prompt}",
        ll_model=state.user_settings["ll_model"] | state.ll_model_enabled[ll_model],
        vector_search=state.user_settings["vector_search"],
        database_config=state.database_config[state.user_settings["database"]["alias"]],
    )

    if file_name.endswith(".yaml"):
        ctx_prompt = json.dumps(ctx_prompt, indent=True)  # Converts it into a valid JSON string (preserving quotes)

        formatted_content = template_content.format(
            provider=provider,
            ctx_prompt=ctx_prompt,
            ll_model=state.user_settings["ll_model"] | state.ll_model_enabled[ll_model],
            vector_search=state.user_settings["vector_search"],
            database_config=state.database_config[state.user_settings["database"]["alias"]],
        )

        yaml_data = yaml.safe_load(formatted_content)
        if provider == "ollama":
            del yaml_data["spring"]["ai"]["openai"]
        if provider == "openai":
            del yaml_data["spring"]["ai"]["ollama"]
        formatted_content = yaml.dump(yaml_data)

    return formatted_content


def spring_ai_zip(provider, ll_model):
    """Create SpringAI Zip File"""
    # Source directory that you want to copy
    files = ["mvnw", "mvnw.cmd", "pom.xml", "README.md"]

    src_dir = Path(__file__).resolve().parents[2] / "spring_ai"

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
            env_content = spring_ai_obaas(src_dir, "start.sh", provider, ll_model)
            yaml_content = spring_ai_obaas(src_dir, "obaas.yaml", provider, ll_model)
            zip_file.writestr("start.sh", env_content.encode("utf-8"))
            zip_file.writestr("src/main/resources/application-obaas.yml", yaml_content.encode("utf-8"))
        zip_buffer.seek(0)
    return zip_buffer


#####################################################
# MAIN
#####################################################
def main():
    """Streamlit GUI"""
    remove_footer()
    st.header("Client Settings", divider="red")
    get_models(model_type="ll", force=True)
    get_models(model_type="embed", force=True)
    get_databases(force=True)
    get_oci(force=True)
    get_prompts(force=True)
    state_dict = copy.deepcopy(state)
    upload_settings = st.toggle(
        "Upload",
        key="selected_upload_settings",
        value=False,
        help="Save or Upload Client Settings.",
    )
    if not upload_settings:
        st.json(state, expanded=False)
        col_left, col_centre, _ = st.columns([3, 4, 3])
        # Oder matters (selected_sensitive_settings must be defined)
        col_centre.checkbox(
            "Include Sensitive Settings",
            key="selected_sensitive_settings",
            help="Include API Keys and Passwords in Download",
        )
        col_left.download_button(
            label="Download Settings",
            data=save_settings(),
            file_name="optimizer_settings.json",
        )
    else:
        uploaded_file = st.file_uploader("Upload the Settings file", type="json")
        if uploaded_file is not None:
            file_content = uploaded_file.read()

            # Convert the JSON content to a dictionary
            try:
                uploaded_settings_dict = json.loads(file_content)
                differences = compare_with_uploaded_json(state_dict, uploaded_settings_dict)

                # Show differences
                if differences:
                    if st.button("Apply New Settings"):
                        # Update the Server; must be done first to avoid unnecessary API calls
                        update_server(uploaded_settings_dict)
                        # Update session state; this is primarily for user_settings
                        update_session_state_recursive(state, uploaded_settings_dict)
                        st.success("Configuration has been updated with the uploaded settings.", icon="✅")
                        time.sleep(3)
                        st.rerun()
                    st.subheader("Differences found:")
                    st.json(differences)
                else:
                    st.write("No differences found. The current configuration matches the saved settings.")
            except json.JSONDecodeError:
                st.error("Error: The uploaded file is not a valid.")
        else:
            st.info("Please upload a Settings file.")

    st.header("SpringAI Settings", divider="red")
    ll_model = state.user_settings["ll_model"]["model"]
    embed_model = state.user_settings["vector_search"]["model"]
    spring_ai_conf = spring_ai_conf_check(ll_model, embed_model)

    if spring_ai_conf == "hybrid":
        st.markdown(f"""
            The current configuration combination of embedding and language models
            is currently **not supported** for SpringAI.
            - Language Model:  **{ll_model}**
            - Embedding Model: **{embed_model}**
        """)
    else:
        st.download_button(
            label="Download SpringAI",
            data=spring_ai_zip(spring_ai_conf, ll_model),  # Generate zip on the fly
            file_name="spring_ai.zip",  # Zip file name
            mime="application/zip",  # Mime type for zip file
            disabled=spring_ai_conf == "hybrid",
        )


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    main()
