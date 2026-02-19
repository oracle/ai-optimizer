"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for OCI settings conversion functions.
"""

from server.app.api.v1.schemas.oci_profiles import OCIConfigEntry
from server.app.oci.config import OCIAuthConfig, OCIProfileSettings, OCIProfileState
from server.app.oci.settings import entry_to_oci_settings, oci_config_to_entry


class TestOCIConfigToEntry:
    """oci_config_to_entry converts state to persistence entry."""

    def test_full_conversion(self):
        """All fields are mapped from state to entry."""
        settings = OCIProfileSettings(
            auth_profile="TEST",
            auth=OCIAuthConfig(
                user="ocid1.user.oc1..test",
                authentication="api_key",
                fingerprint="aa:bb:cc",
                tenancy="ocid1.tenancy.oc1..test",
                key="pem-contents",
                pass_phrase="secret",
            ),
            region="us-ashburn-1",
            genai_compartment_id="ocid1.compartment.oc1..test",
            genai_region="us-chicago-1",
            log_requests=True,
            additional_user_agent="test-agent",
        )
        state = OCIProfileState(settings=settings)

        entry = oci_config_to_entry(state)

        assert entry.auth_profile == "TEST"
        assert entry.user == "ocid1.user.oc1..test"
        assert entry.authentication == "api_key"
        assert entry.fingerprint == "aa:bb:cc"
        assert entry.tenancy == "ocid1.tenancy.oc1..test"
        assert entry.region == "us-ashburn-1"
        assert entry.key == "pem-contents"
        assert entry.pass_phrase == "secret"
        assert entry.genai_compartment_id == "ocid1.compartment.oc1..test"
        assert entry.genai_region == "us-chicago-1"
        assert entry.log_requests is True
        assert entry.additional_user_agent == "test-agent"

    def test_minimal_conversion(self):
        """Optional fields default to None."""
        settings = OCIProfileSettings(auth_profile="MINIMAL")
        state = OCIProfileState(settings=settings)
        entry = oci_config_to_entry(state)
        assert entry.auth_profile == "MINIMAL"
        assert entry.user is None
        assert entry.key is None


class TestEntryToOCISettings:
    """entry_to_oci_settings converts persistence entry to internal settings."""

    def test_round_trip(self):
        """All fields are mapped from entry to settings."""
        entry = OCIConfigEntry(
            auth_profile="RT",
            user="ocid1.user.oc1..rt",
            authentication="security_token",
            security_token_file="/path/token",
            fingerprint="dd:ee:ff",
            tenancy="ocid1.tenancy.oc1..rt",
            region="us-phoenix-1",
            key="key-data",
            pass_phrase="phrase",
            genai_compartment_id="ocid1.compartment.oc1..rt",
            genai_region="us-chicago-1",
            log_requests=True,
            additional_user_agent="agent",
        )

        settings = entry_to_oci_settings(entry)

        assert settings.auth_profile == "RT"
        assert settings.auth.user == "ocid1.user.oc1..rt"
        assert settings.auth.authentication == "security_token"
        assert settings.auth.security_token_file == "/path/token"
        assert settings.auth.fingerprint == "dd:ee:ff"
        assert settings.auth.tenancy == "ocid1.tenancy.oc1..rt"
        assert settings.region == "us-phoenix-1"
        assert settings.auth.key == "key-data"
        assert settings.auth.pass_phrase == "phrase"
        assert settings.genai_compartment_id == "ocid1.compartment.oc1..rt"
        assert settings.genai_region == "us-chicago-1"
        assert settings.log_requests is True
        assert settings.additional_user_agent == "agent"

    def test_defaults(self):
        """Minimal entry preserves default values."""
        entry = OCIConfigEntry(auth_profile="DEF")
        settings = entry_to_oci_settings(entry)
        assert settings.auth.authentication == "api_key"
        assert settings.log_requests is False
        assert settings.additional_user_agent == ""
