"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Conversion helpers between OCI internal state and persistence models.
"""
# spell-checker: ignore genai

from .schema import OciProfileConfig


def oci_config_to_entry(state: OCIProfileState) -> OCIConfigEntry:
    """Convert internal OCIProfileState to a JSON-serializable entry."""

    return OCIConfigEntry(**state.settings.model_dump())


def entry_to_oci_settings(entry: OCIConfigEntry) -> OCIProfileSettings:
    """Convert a persisted JSON entry back to internal OCIProfileSettings."""

    return OCIProfileSettings(**entry.model_dump())
