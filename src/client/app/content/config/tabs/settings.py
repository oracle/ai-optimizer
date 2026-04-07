"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: ignore pname ollama vllm obaas mvnw

import copy
import io
import json
import logging
import shutil
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
import streamlit as st
import yaml
from streamlit import session_state as state

from client.app.core import helpers
from client.app.core.api import api_post, get_server_settings

LOGGER = logging.getLogger("client.content.config.tabs.settings")


#############################################################################
# Functions
#############################################################################
def _fetch_settings() -> dict:
    """Return settings filtered by the 'Include Sensitive Settings' checkbox.

    Calls the server with ``include_sensitive`` matching the checkbox state so
    that sensitive fields are omitted when the user has not opted in.  Falls
    back to ``state.settings`` if the API call fails.
    """
    include = state.get("runtime_sensitive_settings", False)
    result = get_server_settings(client=state.optimizer_client, include_sensitive=include)
    return result if result is not None else state.settings


def _get_settings_data() -> str:
    """Return settings JSON for download, respecting the sensitivity checkbox."""
    return json.dumps(_fetch_settings(), indent=2)


def _compare_prompt_configs(current_prompts: list, uploaded_prompts: list) -> dict:
    """Compare prompt_configs lists by prompt name."""
    current_by_name = {p["name"]: p for p in current_prompts if "name" in p}
    uploaded_by_name = {p["name"]: p for p in uploaded_prompts if "name" in p}
    result = {}
    for name in sorted(set(current_by_name) | set(uploaded_by_name)):
        if name in current_by_name and name in uploaded_by_name:
            if current_by_name[name] != uploaded_by_name[name]:
                result[name] = {
                    "status": "Text differs",
                    "current": current_by_name[name],
                    "uploaded": uploaded_by_name[name],
                }
        elif name not in current_by_name:
            result[name] = {"status": "Missing in Current", "uploaded": uploaded_by_name[name]}
        else:
            result[name] = {"status": "Missing in Uploaded", "current": current_by_name[name]}
    return result


# Config lists matched by unique key rather than position.
# Each value is a function that extracts the unique key from an item.
_KEYED_CONFIGS = {
    "model_configs": lambda item: (item["id"], item["provider"]),
    "database_configs": lambda item: item["alias"],
    "oci_configs": lambda item: item["auth_profile"],
}

_PROMPT_DIFF_FORMATTERS = {
    "Text differs": lambda info: (
        "Value Mismatch",
        {"current": info["current"], "uploaded": info["uploaded"]},
    ),
    "Missing in Current": lambda info: ("Missing in Current", info["uploaded"]),
    "Missing in Uploaded": lambda info: ("Missing in Uploaded", info["current"]),
}


def _compare_keyed_configs(current_items: list, uploaded_items: list, path: str, differences: dict, key_fn) -> None:
    """Compare config lists by matching on a unique key."""
    current_by_key = {key_fn(item): item for item in current_items}
    uploaded_by_key = {key_fn(item): item for item in uploaded_items}
    for key in sorted(set(current_by_key) | set(uploaded_by_key), key=str):
        label = key if isinstance(key, str) else ".".join(str(k) for k in key)
        item_path = f"{path}.{label}"
        if key in current_by_key and key in uploaded_by_key:
            _compute_diff(current_by_key[key], uploaded_by_key[key], item_path, differences)
        elif key in current_by_key:
            differences["Missing in Uploaded"][item_path] = current_by_key[key]
        else:
            differences["Missing in Current"][item_path] = uploaded_by_key[key]


def _compare_dicts(current: dict, uploaded: dict, path: str, differences: dict) -> None:
    """Compare two dicts recursively, populating differences."""
    all_keys = sorted(set(current) | set(uploaded))
    for key in all_keys:
        full_path = f"{path}.{key}" if path else key
        if full_path == "client_settings.client" or full_path.endswith((".created", ".usable")):
            continue

        current_value = current.get(key)
        uploaded_value = uploaded.get(key)

        if key not in current or key not in uploaded:
            if key not in uploaded and current_value not in (None, ""):
                differences["Missing in Uploaded"][full_path] = current_value
            if key not in current:
                differences["Missing in Current"][full_path] = uploaded_value
            continue

        if key == "prompt_configs" and isinstance(current_value, list) and isinstance(uploaded_value, list):
            for pname, info in _compare_prompt_configs(current_value, uploaded_value).items():
                bucket, payload = _PROMPT_DIFF_FORMATTERS[info["status"]](info)
                prompt_path = f"{full_path}.{pname}"
                differences[bucket][prompt_path] = payload
            continue

        if key in _KEYED_CONFIGS and isinstance(current_value, list) and isinstance(uploaded_value, list):
            _compare_keyed_configs(current_value, uploaded_value, full_path, differences, _KEYED_CONFIGS[key])
            continue

        _compute_diff(current_value, uploaded_value, full_path, differences)


def _compare_lists(current: list, uploaded: list, path: str, differences: dict) -> None:
    """Compare two lists pairwise, populating differences."""
    for i in range(min(len(current), len(uploaded))):
        _compute_diff(current[i], uploaded[i], f"{path}[{i}]", differences)
    for i in range(len(uploaded), len(current)):
        differences["Missing in Uploaded"][f"{path}[{i}]"] = current[i]
    for i in range(len(current), len(uploaded)):
        differences["Missing in Current"][f"{path}[{i}]"] = uploaded[i]


def _compute_diff(current, uploaded, path: str = "", differences: dict | None = None) -> dict:
    """Compare current settings against uploaded settings.

    Returns a categorized dict with 'Value Mismatch', 'Missing in Uploaded',
    and 'Missing in Current' keys.
    """
    is_root = differences is None
    if is_root:
        differences = {"Value Mismatch": {}, "Missing in Uploaded": {}, "Missing in Current": {}}

    if isinstance(current, dict) and isinstance(uploaded, dict):
        _compare_dicts(current, uploaded, path, differences)
    elif isinstance(current, list) and isinstance(uploaded, list):
        _compare_lists(current, uploaded, path, differences)
    elif current != uploaded:
        differences["Value Mismatch"][path] = {"current": current, "uploaded": uploaded}

    return differences


def _apply_uploaded_settings(uploaded_data: dict) -> None:
    """POST uploaded settings to the import endpoint and refresh."""
    try:
        api_post("settings/import", json=uploaded_data, toast="Settings imported.")
        helpers.refresh_settings()
    except httpx.HTTPStatusError as exc:
        st.error(f"Failed to import settings: {helpers.extract_error_detail(exc)}")


def _render_upload_settings_section() -> None:
    uploaded_file = st.file_uploader(
        "Upload Settings JSON",
        type="json",
        key="runtime_settings_upload_file",
    )
    if uploaded_file is not None:
        try:
            uploaded_data = json.loads(uploaded_file.read())
        except (json.JSONDecodeError, UnicodeDecodeError):
            st.error("Invalid JSON file.")
            return

        differences = _compute_diff(current=state.settings, uploaded=uploaded_data)
        differences = {k: v for k, v in differences.items() if v}
        if not differences:
            st.info("Settings match the server.")
        else:
            st.subheader("Differences found:")
            st.json(differences, expanded=True)
            if st.button(
                "Apply Settings",
                icon="📤",
                key="runtime_apply_settings",
                help="Import settings from the uploaded JSON file",
            ):
                _apply_uploaded_settings(uploaded_data)
                time.sleep(2)
                st.rerun()


def _reset_to_factory() -> None:
    """POST to /settings/reset and refresh local state."""
    try:
        api_post("settings/reset", toast="Settings reset to factory defaults.", timeout=30)
        helpers.refresh_settings()
    except httpx.HTTPStatusError as exc:
        st.error(f"Factory reset failed: {helpers.extract_error_detail(exc)}")


def _render_download_settings_section() -> None:
    now = datetime.now()
    filename = f"optimizer_settings_{now.strftime('%Y%m%d_%H%M%S')}.json"
    download_button, reset_button, _ = st.columns([3, 3, 4])
    download_button.download_button(
        label="📥 Download Settings",
        type="primary",
        data=_get_settings_data(),
        file_name=filename,
        mime="application/json",
        key="runtime_download_settings",
    )
    with reset_button:  # noqa: SIM117
        with st.popover("⚠️ Factory Reset"):
            st.warning("Are you sure you want to reset all settings to factory defaults?")
            if st.button("⚠️ Factory Reset", key="runtime_factory_reset", type="primary"):
                _reset_to_factory()
                time.sleep(2)
                st.rerun()


#############################################################################
# Source Code Downloads
#############################################################################
def _save_settings(settings):
    """Return settings JSON after stamping the client field."""
    data = copy.deepcopy(settings)
    now = datetime.now()
    saved_time = now.strftime("%d-%b-%YT%H%M").upper()

    if "client_settings" in data and "client" in data["client_settings"]:
        data["client_settings"]["client"] = saved_time

    return json.dumps(data, indent=2)


def _spring_ai_obaas(src_dir, file_name, provider, ll_config, embed_config):
    """Get the system prompt for SpringAI export"""
    client_settings = state["settings"]["client_settings"]

    ## FUTURE FEATURE:
    # Determine which system prompt would be active based on tools_enabled
    # tools_enabled = client_settings.get("tools_enabled", [])

    # Select prompt name based on tools configuration
    # if not tools_enabled:
    #     prompt_name = "optimizer_basic-default"
    #     if client_settings["vector_search"]["enabled"]:
    #         prompt_name = "optimizer_vs-no-tools-default"
    # else:
    #     # Tools are enabled, use tools-default prompt
    #     prompt_name = "optimizer_tools-default"
    ## Legacy Feature:
    prompt_name = (
        "optimizer_vs-tools-default"
        if "Vector Search" in client_settings.get("tools_enabled", [])
        else "optimizer_basic-default"
    )

    # Find the prompt in configs
    sys_prompt_obj = next((item for item in state["settings"]["prompt_configs"] if item["name"] == prompt_name), None)

    if sys_prompt_obj:
        sys_prompt = sys_prompt_obj.get("text")
    else:
        LOGGER.warning("Prompt %s not found in configs, using fallback", prompt_name)
        sys_prompt = "You are a helpful assistant."

    LOGGER.info("Prompt used in export (%s):\n%s", prompt_name, sys_prompt)

    db_config = helpers.state_configs_lookup("database_configs", "alias")[
        client_settings.get("database", {}).get("alias")
    ]

    # Resolve vector_store table name from the database config's vector stores
    vs_alias = embed_config.get("alias")
    vector_store_name = next(
        (
            vs.get("vector_store", "")
            for vs in db_config.get("vector_stores", [])
            if (vs_alias and vs.get("alias") == vs_alias) or (not vs_alias and vs.get("vector_store"))
        ),
        "",
    )

    formatted_content = (
        (src_dir / "templates" / file_name)
        .read_text(encoding="utf-8")
        .format(
            provider=provider,
            sys_prompt=yaml.dump(sys_prompt).rstrip("\n...") if file_name.endswith(".yaml") else sys_prompt,
            ll_model=ll_config,
            vector_search={**embed_config, "vector_store": vector_store_name},
            database_config=db_config,
        )
    )

    if file_name.endswith(".yaml"):
        yaml_data = yaml.safe_load(formatted_content)
        other_provider = {"ollama": "openai", "openai": "ollama"}.get(provider)
        if other_provider:
            yaml_data["spring"]["ai"][other_provider] = {"chat": {"options": {"model": "_"}}}

        if (
            provider == "openai"
            and "obaas" in file_name
            and "api.openai.com" in yaml_data["spring"]["ai"]["openai"]["base-url"]
        ):
            yaml_data["spring"]["ai"]["openai"]["base-url"] = "https://api.openai.com"
            LOGGER.info(
                "in _spring_ai_obaas(%s) found openai.base-url and changed with https://api.openai.com",
                file_name,
            )

        formatted_content = yaml.dump(yaml_data)

    return formatted_content


def _zip_directory(directory: Path) -> io.BytesIO:
    """Zip all files under *directory* into an in-memory buffer."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in directory.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(directory))
    buf.seek(0)
    return buf


def _spring_ai_zip(provider, ll_config, embed_config):
    """Create SpringAI Zip File"""

    files = ["mvnw", "mvnw.cmd", "pom.xml", "README.md"]
    src_dir = Path(__file__).resolve().parents[4] / "source/spring_ai"

    with tempfile.TemporaryDirectory() as temp_dir:
        dst_dir = Path(temp_dir) / "spring_ai"
        LOGGER.info("Starting SpringAI zip processing: %s", dst_dir)

        shutil.copytree(src_dir / "src", dst_dir / "src")
        for item in files:
            shutil.copy(src_dir / item, dst_dir)

        zip_buffer = _zip_directory(dst_dir)

        env_content = _spring_ai_obaas(src_dir, "start.sh", provider, ll_config, embed_config)
        yaml_content = _spring_ai_obaas(src_dir, "obaas.yaml", provider, ll_config, embed_config)
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("start.sh", env_content)
            zf.writestr("src/main/resources/application-obaas.yml", yaml_content)
        zip_buffer.seek(0)
    return zip_buffer


def _langchain_mcp_zip(settings):
    """Create LangChain MCP Zip File"""

    src_dir = Path(__file__).resolve().parents[4] / "source/langchain/rag"

    with tempfile.TemporaryDirectory() as temp_dir:
        dst_dir = Path(temp_dir) / "langchain_mcp"
        LOGGER.info("Starting langchain mcp zip processing: %s", dst_dir)

        shutil.copytree(src_dir, dst_dir)
        (dst_dir / "optimizer_settings.json").write_text(_save_settings(settings), encoding="utf-8")

        return _zip_directory(dst_dir)


def _spring_ai_conf_check(ll_model: dict, embed_model: dict) -> str:
    """Check if configuration is valid for SpringAI package"""
    if not ll_model or not embed_model:
        return "hybrid"

    ll_provider = ll_model.get("provider", "")
    embed_provider = embed_model.get("provider", "")
    LOGGER.info("llm chat: %s - embeddings: %s", ll_provider, embed_provider)
    if all("hosted_vllm" in p for p in (ll_provider, embed_provider)):
        return "hosted_vllm"
    if all("openai" in p for p in (ll_provider, embed_provider)):
        return "openai"
    if all("ollama" in p for p in (ll_provider, embed_provider)):
        return "ollama"

    return "hybrid"


def _get_model_configs() -> tuple[dict, dict, str]:
    """Get model configurations and determine Spring AI config type."""
    client_settings = state["settings"]["client_settings"]
    try:
        model_lookup = helpers.enabled_models_lookup(model_type="ll")
        ll_model = client_settings["ll_model"]
        ll_key = f"{ll_model.get('provider')}/{ll_model.get('id')}"
        ll_config = model_lookup[ll_key] | ll_model
    except KeyError:
        ll_config = {}

    try:
        model_lookup = helpers.enabled_models_lookup(model_type="embed")
        vs = client_settings["vector_search"]
        embed_key = f"{vs.get('provider')}/{vs.get('id')}"
        embed_config = model_lookup[embed_key] | vs
    except KeyError:
        embed_config = {}

    spring_ai_conf = _spring_ai_conf_check(ll_config, embed_config)
    return ll_config, embed_config, spring_ai_conf


def _render_source_code_templates_section() -> None:
    """Render the source code templates section."""
    st.header("Source Code Templates", divider="red")

    ll_config, embed_config, spring_ai_conf = _get_model_configs()
    LOGGER.debug("config found: %s", spring_ai_conf)

    if spring_ai_conf == "hybrid":
        st.markdown(
            f"""
            The current configuration combination of embedding and language models
            is currently **not supported** for Spring AI and LangChain MCP templates.
            - Language Model:  **{ll_config.get("id", "Unset")}**
            - Embedding Model: **{embed_config.get("id", "Unset")}**
        """
        )
    else:
        settings = get_server_settings(client=state.optimizer_client, include_sensitive=True) or state.settings
        col_left, col_centre, _ = st.columns([3, 4, 3])
        with col_left:
            st.download_button(
                label="Download LangchainMCP",
                data=_langchain_mcp_zip(settings),
                file_name="langchain_mcp.zip",
                mime="application/zip",
            )
        with col_centre:
            if spring_ai_conf != "hosted_vllm":
                st.download_button(
                    label="Download SpringAI",
                    data=_spring_ai_zip(spring_ai_conf, ll_config, embed_config),
                    file_name="spring_ai.zip",
                    mime="application/zip",
                )


#####################################################
# MAIN
#####################################################
def display_settings():
    """Streamlit GUI"""
    st.header("Optimizer Settings", divider="red")

    if "runtime_settings_upload_toggle" not in state:
        state.runtime_settings_upload_toggle = False
    col_left, col_right = st.columns([2, 9])
    upload_settings = col_left.toggle(
        "Upload",
        key="runtime_settings_upload_toggle",
        help="Upload Settings.",
        width="content",
    )
    col_right.checkbox(
        "Include Sensitive Settings",
        key="runtime_sensitive_settings",
        help="Include API Keys and Passwords in Download",
        disabled=upload_settings,
    )

    if not upload_settings:
        st.json(_fetch_settings(), expanded=False)
        _render_download_settings_section()
    else:
        _render_upload_settings_section()

    _render_source_code_templates_section()
