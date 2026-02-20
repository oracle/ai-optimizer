"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI profile registry and startup lifecycle.
"""
# spell-checker: ignore genai

import logging

from .config import parse_oci_config_file
from .settings import entry_to_oci_settings

LOGGER = logging.getLogger(__name__)

async def load_oci_profiles(persisted=None) -> None:
    """Startup entry point: load OCI profiles from config file and DB."""

    # 1. Parse OCI config file
    profiles = parse_oci_config_file()
    for settings in profiles:
        register_oci_profile(settings)

    if profiles:
        LOGGER.info("Loaded %d OCI profile(s) from config file", len(profiles))

    # 2. Load persisted OCI configs from DB (if provided)
    if persisted is not None:
        for entry in persisted.oci_configs:
            oci_settings = entry_to_oci_settings(entry)
            register_oci_profile(oci_settings)
