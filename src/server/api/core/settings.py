"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import os
import copy
import json
from server.api.core import bootstrap

from common.schema import Settings, Configuration, ClientIdType
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


def get_server_config() -> Configuration:
    """Return server configuration"""
    database_objects = bootstrap.DATABASE_OBJECTS
    database_configs = [db for db in database_objects]

    model_objects = bootstrap.MODEL_OBJECTS
    model_configs = [model for model in model_objects]

    oci_objects = bootstrap.OCI_OBJECTS
    oci_configs = [oci for oci in oci_objects]

    prompt_objects = bootstrap.PROMPT_OBJECTS
    prompt_configs = [prompt for prompt in prompt_objects]

    full_config = {
        "database_configs": database_configs,
        "model_configs": model_configs,
        "oci_configs": oci_configs,
        "prompt_configs": prompt_configs,
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

    if "prompt_configs" in config_data:
        bootstrap.PROMPT_OBJECTS = config.prompt_configs or []


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
