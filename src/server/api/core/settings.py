"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore fastmcp

import os
import copy
import json
from fastmcp import FastMCP

from server.bootstrap import bootstrap
from server.mcp.prompts import cache
from server.mcp.prompts import defaults
import server.api.utils.mcp as utils_mcp

from common.schema import Settings, Configuration, ClientIdType, MCPPrompt
from common import logging_config

logger = logging_config.logging.getLogger("api.core.settings")


def create_client_settings(client: ClientIdType) -> Settings:
    """Create a new client"""
    logger.debug("Creating client (if non-existent): %s", client)
    settings_objects = bootstrap.SETTINGS_OBJECTS
    if any(settings.client == client for settings in settings_objects):
        raise ValueError(f"client {client} already exists")

    default_settings = next((settings for settings in settings_objects if settings.client == "default"), None)
    # Copy the default settings
    client_settings = Settings(**default_settings.model_dump())
    client_settings.client = client
    settings_objects.append(client_settings)

    return client_settings


def get_client_settings(client: ClientIdType) -> Settings:
    """Return client settings"""
    settings_objects = bootstrap.SETTINGS_OBJECTS
    client_settings = next((settings for settings in settings_objects if settings.client == client), None)
    if not client_settings:
        raise ValueError(f"client {client} not found")

    return client_settings


async def get_mcp_prompts_with_overrides(mcp_engine: FastMCP) -> list[MCPPrompt]:
    """Get all MCP prompts with their defaults and overrides"""
    prompts_info = []
    prompts = await utils_mcp.list_prompts(mcp_engine)

    for prompt_obj in prompts:
        # Only include optimizer prompts
        if not prompt_obj.name.startswith("optimizer_"):
            continue

        # Get default text from code
        default_func_name = prompt_obj.name.replace("-", "_")
        default_func = getattr(defaults, default_func_name, None)

        if default_func:
            try:
                default_message = default_func()
                default_text = default_message.content.text
            except Exception as ex:
                logger.warning("Failed to get default text for %s: %s", prompt_obj.name, ex)
                default_text = ""
        else:
            logger.warning("No default function found for prompt: %s", prompt_obj.name)
            default_text = ""

        # Get override from cache
        override_text = cache.get_override(prompt_obj.name)

        # Extract tags from meta (FastMCP stores tags in meta._fastmcp.tags)
        tags = []
        if prompt_obj.meta and "_fastmcp" in prompt_obj.meta:
            tags = prompt_obj.meta["_fastmcp"].get("tags", [])

        prompts_info.append(
            MCPPrompt(
                name=prompt_obj.name,
                title=prompt_obj.title or prompt_obj.name,
                description=prompt_obj.description or "",
                tags=tags,
                default_text=default_text,
                override_text=override_text,
            )
        )

    return prompts_info


async def get_server_config(mcp_engine: FastMCP) -> dict:
    """Return server configuration"""
    database_objects = bootstrap.DATABASE_OBJECTS
    database_configs = list(database_objects)

    model_objects = bootstrap.MODEL_OBJECTS
    model_configs = list(model_objects)

    oci_objects = bootstrap.OCI_OBJECTS
    oci_configs = list(oci_objects)

    # Get MCP prompts with overrides
    prompt_configs = await get_mcp_prompts_with_overrides(mcp_engine)

    # Extract just the overrides for compact storage
    prompt_overrides = {p.name: p.override_text for p in prompt_configs if p.override_text is not None}

    full_config = {
        "database_configs": database_configs,
        "model_configs": model_configs,
        "oci_configs": oci_configs,
        "prompt_overrides": prompt_overrides,  # Compact overrides only for export/import
    }
    return full_config


def update_client_settings(payload: Settings, client: ClientIdType) -> Settings:
    """Update a single client settings"""
    settings_objects = bootstrap.SETTINGS_OBJECTS

    client_settings = get_client_settings(client)
    settings_objects.remove(client_settings)

    payload.client = client
    settings_objects.append(payload)

    return get_client_settings(client)


def update_server_config(config_data: dict) -> None:
    """Update server configuration"""
    config = Configuration(**config_data)

    if "database_configs" in config_data:
        bootstrap.DATABASE_OBJECTS = config.database_configs or []

    if "model_configs" in config_data:
        bootstrap.MODEL_OBJECTS = config.model_configs or []

    if "oci_configs" in config_data:
        bootstrap.OCI_OBJECTS = config.oci_configs or []

    # Load MCP prompt overrides into cache
    if "prompt_overrides" in config_data:
        overrides = config_data["prompt_overrides"]
        if overrides:
            logger.info("Loading %d prompt overrides into cache", len(overrides))
            for name, text in overrides.items():
                if text:  # Only set non-null overrides
                    cache.set_override(name, text)
                    logger.debug("Set override for prompt: %s", name)


def load_config_from_json_data(config_data: dict, client: ClientIdType = None) -> None:
    """Shared logic for loading settings from JSON data."""

    # Load server config parts into state
    update_server_config(config_data)

    # Load extracted client_settings from config
    client_settings_data = config_data.get("client_settings")
    if not client_settings_data:
        raise KeyError("Missing client_settings in config file")

    client_settings = Settings(**client_settings_data)

    # Determine clients to update
    if client:
        logger.debug("Updating client settings: %s", client)
        update_client_settings(client_settings, client)
    else:
        server_settings = copy.deepcopy(client_settings)
        update_client_settings(server_settings, "server")
        default_settings = copy.deepcopy(client_settings)
        update_client_settings(default_settings, "default")


def read_config_from_json_file() -> Configuration:
    """Load configuration file if it exists"""
    config = os.getenv("CONFIG_FILE")

    if not os.path.isfile(config) or not os.access(config, os.R_OK):
        logger.warning("Config file %s does not exist or is not readable.", config)

    if not config.endswith(".json"):
        logger.warning("Config file %s must be a .json file", config)

    with open(config, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    full_configuration = Configuration(**config_data)

    return full_configuration
