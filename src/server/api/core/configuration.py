"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from server.api.core import bootstrap

import common.schema as schema


def get_server_config() -> schema.Configuration:
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


def load_server_config(config_data: dict) -> None:
    """Load server configuration from dict, updating only present keys in bootstrap."""
    config = schema.Configuration(**config_data)

    if "database_configs" in config_data:
        bootstrap.DATABASE_OBJECTS = config.database_configs or []

    if "model_configs" in config_data:
        bootstrap.MODEL_OBJECTS = config.model_configs or []

    if "oci_configs" in config_data:
        bootstrap.OCI_OBJECTS = config.oci_configs or []

    if "prompt_configs" in config_data:
        bootstrap.PROMPT_OBJECTS = config.prompt_configs or []
