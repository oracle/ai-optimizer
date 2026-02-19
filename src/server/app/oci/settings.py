"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Conversion helpers between OCI internal state and persistence models.
"""
# spell-checker: ignore genai

from server.app.api.v1.schemas.oci_profiles import OCIConfigEntry
from server.app.oci.config import OCIAuthConfig, OCIProfileSettings, OCIProfileState


def oci_config_to_entry(state: OCIProfileState) -> OCIConfigEntry:
    """Convert internal OCIProfileState to a JSON-serializable entry."""

    s = state.settings
    a = s.auth
    return OCIConfigEntry(
        auth_profile=s.auth_profile,
        user=a.user,
        authentication=a.authentication,
        security_token_file=a.security_token_file,
        fingerprint=a.fingerprint,
        tenancy=a.tenancy,
        region=s.region,
        key=a.key,
        pass_phrase=a.pass_phrase,
        genai_compartment_id=s.genai_compartment_id,
        genai_region=s.genai_region,
        log_requests=s.log_requests,
        additional_user_agent=s.additional_user_agent,
    )


def entry_to_oci_settings(entry: OCIConfigEntry) -> OCIProfileSettings:
    """Convert a persisted JSON entry back to internal OCIProfileSettings."""

    return OCIProfileSettings(
        auth_profile=entry.auth_profile,
        auth=OCIAuthConfig(
            user=entry.user,
            authentication=entry.authentication,
            security_token_file=entry.security_token_file,
            fingerprint=entry.fingerprint,
            tenancy=entry.tenancy,
            key=entry.key,
            pass_phrase=entry.pass_phrase,
        ),
        region=entry.region,
        genai_compartment_id=entry.genai_compartment_id,
        genai_region=entry.genai_region,
        log_requests=entry.log_requests,
        additional_user_agent=entry.additional_user_agent,
    )
