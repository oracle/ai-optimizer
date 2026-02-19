"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for OCI profile registry operations.
"""
# spell-checker: disable
# pylint: disable=too-few-public-methods

from unittest.mock import patch

import pytest

from server.app.api.v1.schemas.databases import PersistedSettings
from server.app.api.v1.schemas.oci_profiles import OCIConfigEntry
from server.app.oci import (
    clear_oci_registry,
    get_all_oci_profiles,
    get_oci_profile,
    load_oci_profiles,
    register_oci_profile,
    remove_oci_profile,
)
from server.app.oci.config import OCIProfileSettings


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure a clean registry for each test."""
    clear_oci_registry()
    yield
    clear_oci_registry()


class TestRegisterOCIProfile:
    """register_oci_profile stores and updates profiles."""

    def test_register_new_profile(self):
        """New profile is stored and marked usable."""
        settings = OCIProfileSettings(auth_profile="TEST", region="us-ashburn-1")
        state = register_oci_profile(settings)
        assert state.auth_profile == "TEST"
        assert state.settings.region == "us-ashburn-1"
        assert state.usable is True

    def test_register_updates_existing(self):
        """Re-registering the same name updates settings in place."""
        settings1 = OCIProfileSettings(auth_profile="TEST", region="us-ashburn-1")
        state1 = register_oci_profile(settings1)

        settings2 = OCIProfileSettings(auth_profile="TEST", region="us-phoenix-1")
        state2 = register_oci_profile(settings2)

        assert state1 is state2
        assert state2.settings.region == "us-phoenix-1"


class TestGetOCIProfile:
    """get_oci_profile returns the profile or None."""

    def test_get_existing(self):
        """Returns state for a registered profile."""
        register_oci_profile(OCIProfileSettings(auth_profile="X"))
        assert get_oci_profile("X") is not None

    def test_get_missing(self):
        """Returns None for an unknown profile."""
        assert get_oci_profile("NOPE") is None


class TestGetAllOCIProfiles:
    """get_all_oci_profiles returns all registered profiles."""

    def test_empty_registry(self):
        """Empty list when nothing is registered."""
        assert not get_all_oci_profiles()

    def test_returns_all(self):
        """All registered profiles are included."""
        register_oci_profile(OCIProfileSettings(auth_profile="A"))
        register_oci_profile(OCIProfileSettings(auth_profile="B"))
        profiles = get_all_oci_profiles()
        names = [p.auth_profile for p in profiles]
        assert "A" in names
        assert "B" in names


class TestRemoveOCIProfile:
    """remove_oci_profile removes a profile and returns True/False."""

    def test_remove_existing(self):
        """Returns True and removes the profile."""
        register_oci_profile(OCIProfileSettings(auth_profile="DEL"))
        assert remove_oci_profile("DEL") is True
        assert get_oci_profile("DEL") is None

    def test_remove_missing(self):
        """Returns False for an unknown profile."""
        assert remove_oci_profile("NOPE") is False


class TestClearOCIRegistry:
    """clear_oci_registry removes all profiles."""

    def test_clear(self):
        """Registry is empty after clear."""
        register_oci_profile(OCIProfileSettings(auth_profile="A"))
        register_oci_profile(OCIProfileSettings(auth_profile="B"))
        clear_oci_registry()
        assert not get_all_oci_profiles()


class TestLoadOCIProfiles:
    """load_oci_profiles merges config-file and DB entries."""

    @pytest.mark.anyio
    async def test_db_overrides_config_file(self):
        """Persisted DB values override config-file values for the same profile."""
        config_profile = OCIProfileSettings(
            auth_profile="SHARED",
            region="us-ashburn-1",
            genai_compartment_id="config-compartment",
        )
        db_entry = OCIConfigEntry(
            auth_profile="SHARED",
            region="us-phoenix-1",
            genai_compartment_id="db-compartment",
        )
        persisted = PersistedSettings(oci_configs=[db_entry])

        with patch(
            "server.app.oci.parse_oci_config_file",
            return_value=[config_profile],
        ):
            await load_oci_profiles(persisted)

        state = get_oci_profile("SHARED")
        assert state is not None
        assert state.settings.region == "us-phoenix-1"
        assert state.settings.genai_compartment_id == "db-compartment"
