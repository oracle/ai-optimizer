"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.core.schemas — Pydantic model defaults and validation.
"""
# spell-checker: disable

import pytest

from server.app.core.schemas import (
    ClientSettings,
    ClientSettingsUpdate,
    DatabaseSettings,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# ClientSettings
# ---------------------------------------------------------------------------


class TestClientSettings:
    """Test ClientSettings defaults and copy behavior."""

    def test_deep_copy_independence(self):
        """Deep copy produces independent instances."""
        cs1 = ClientSettings()
        cs2 = cs1.model_copy(deep=True)
        cs2.database.alias = "OTHER"

        assert cs1.database.alias == "CORE"

    def test_oci_default(self):
        """OCI defaults to DEFAULT profile."""
        cs = ClientSettings()
        assert cs.oci.auth_profile == "DEFAULT"

    def test_database_default(self):
        """Database defaults to CORE alias."""
        cs = ClientSettings()
        assert cs.database.alias == "CORE"


# ---------------------------------------------------------------------------
# ClientSettingsUpdate
# ---------------------------------------------------------------------------


class TestClientSettingsUpdate:
    """Test ClientSettingsUpdate partial update schema."""

    def test_partial_update(self):
        """Can set individual fields while leaving others None."""
        u = ClientSettingsUpdate(database=DatabaseSettings(alias="OTHER"))
        assert u.database is not None
        assert u.database.alias == "OTHER"
        assert u.ll_model is None
