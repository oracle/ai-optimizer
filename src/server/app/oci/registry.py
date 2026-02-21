"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI profile registry and startup lifecycle.
"""
# spell-checker: ignore genai

import logging

from server.app.core.settings import settings
from .config import parse_oci_config_file, _check_useable
from .schemas import OciProfileConfig

LOGGER = logging.getLogger(__name__)


def register_oci_profile(profile: OciProfileConfig) -> None:
    """Append *profile* to settings.oci_profile_configs (deduplicate by auth_profile, last-write wins)."""
    key = profile.auth_profile.casefold()
    settings.oci_profile_configs = [
        p for p in settings.oci_profile_configs if p.auth_profile.casefold() != key
    ] + [profile]


async def load_oci_profiles() -> None:
    """Startup entry point: load OCI profiles from the config file."""

    profiles = parse_oci_config_file()
    for prof in profiles:
        _check_useable(prof)
        register_oci_profile(prof)

    if profiles:
        LOGGER.info('Loaded %d OCI profile(s) from config file', len(profiles))
