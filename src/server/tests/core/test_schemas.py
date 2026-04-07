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
    LLModelSettings,
    OciSettings,
    VectorSearchSettings,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# LLModelSettings
# ---------------------------------------------------------------------------


class TestLLModelSettings:
    """Test LLModelSettings defaults."""

    def test_defaults(self):
        """Default values are correct."""
        m = LLModelSettings()
        assert m.chat_history is True
        assert m.provider is None
        assert m.id is None
        assert m.max_tokens == 4096
        assert m.temperature == 0.50
        assert m.top_p == 1.00
        assert m.frequency_penalty == 0.00
        assert m.presence_penalty == 0.00
        assert m.max_input_tokens is None


# ---------------------------------------------------------------------------
# VectorSearchSettings
# ---------------------------------------------------------------------------


class TestVectorSearchSettings:
    """Test VectorSearchSettings defaults."""

    def test_defaults(self):
        """Default values are correct."""
        v = VectorSearchSettings()
        assert v.search_type == "Similarity"
        assert v.top_k == 8
        assert v.score_threshold == 0.65
        assert v.fetch_k == 20
        assert v.lambda_mult == 0.5
        assert v.discovery is True
        assert v.rephrase is True
        assert v.grade is True
        assert v.alias is None
        assert v.chunk_size is None


# ---------------------------------------------------------------------------
# ClientSettings
# ---------------------------------------------------------------------------


class TestClientSettings:
    """Test ClientSettings defaults and copy behavior."""

    def test_defaults(self):
        """Default values are correct."""
        cs = ClientSettings()
        assert cs.client == "CONFIGURED"
        assert isinstance(cs.ll_model, LLModelSettings)
        assert isinstance(cs.oci, OciSettings)
        assert isinstance(cs.database, DatabaseSettings)
        assert not cs.tools_enabled

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

    def test_all_none_by_default(self):
        """All fields are None by default."""
        u = ClientSettingsUpdate()
        assert u.ll_model is None
        assert u.oci is None
        assert u.database is None
        assert u.tools_enabled is None
        assert u.vector_search is None
        assert u.testbed is None

    def test_partial_update(self):
        """Can set individual fields while leaving others None."""
        u = ClientSettingsUpdate(database=DatabaseSettings(alias="OTHER"))
        assert u.database is not None
        assert u.database.alias == "OTHER"
        assert u.ll_model is None
