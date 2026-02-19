"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI profile registry and startup lifecycle.
"""
# spell-checker: ignore genai

import logging
from typing import Dict, Optional

from .config import OCIProfileSettings, OCIProfileState, parse_oci_config_file
from .settings import entry_to_oci_settings

LOGGER = logging.getLogger(__name__)


_OCI_REGISTRY: Dict[str, OCIProfileState] = {}


def register_oci_profile(settings: OCIProfileSettings) -> OCIProfileState:
    """Store or update the state for an OCI profile.

    If the auth_profile already exists, updates its settings while preserving
    runtime state.  Otherwise creates a new OCIProfileState.
    """
    existing = _OCI_REGISTRY.get(settings.auth_profile)
    if existing is not None:
        existing.settings = settings
        return existing
    state = OCIProfileState(settings=settings)
    _OCI_REGISTRY[state.auth_profile] = state
    return state


def get_oci_profile(auth_profile: str) -> Optional[OCIProfileState]:
    """Return the stored state for ``auth_profile`` if present."""
    return _OCI_REGISTRY.get(auth_profile)


def get_all_oci_profiles() -> list[OCIProfileState]:
    """Return all registered OCI profile states."""
    return list(_OCI_REGISTRY.values())


def remove_oci_profile(auth_profile: str) -> bool:
    """Remove an OCI profile from the registry. Returns True if it existed."""
    return _OCI_REGISTRY.pop(auth_profile, None) is not None


def clear_oci_registry() -> None:
    """Remove all tracked OCI profiles."""
    _OCI_REGISTRY.clear()


async def load_oci_profiles(persisted=None) -> None:
    """Startup entry point: load OCI profiles from config file and DB.

    *persisted* is the ``PersistedSettings`` loaded by the caller (from the
    CORE database).  Accepting it as a parameter avoids a circular import
    between the ``database`` and ``oci`` packages.
    """

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
