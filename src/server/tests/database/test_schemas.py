"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.database.schemas — Pydantic model defaults and validation.
"""
# spell-checker: disable

import pytest

from server.app.database.schemas import (
    DatabaseConfig,
    DatabaseSensitive,
    DatabaseUpdate,
)
from server.app.embed.schemas import VectorStoreConfig

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# DatabaseSensitive
# ---------------------------------------------------------------------------


class TestDatabaseSensitive:
    """Test DatabaseSensitive defaults."""

    def test_defaults(self):
        """All sensitive fields default to None."""
        s = DatabaseSensitive()
        assert s.password is None
        assert s.wallet_password is None


# ---------------------------------------------------------------------------
# VectorStoreConfig
# ---------------------------------------------------------------------------


class TestVectorStoreConfig:
    """Test VectorStoreConfig defaults."""

    def test_defaults(self):
        """Default values are correct."""
        vs = VectorStoreConfig()
        assert vs.vector_store is None
        assert vs.alias is None
        assert vs.description is None
        assert vs.embedding_model is None
        assert vs.chunk_size == 0
        assert vs.chunk_overlap == 0
        assert vs.distance_strategy is None
        assert vs.index_type is None

    def test_vector_store_readonly_schema(self):
        """vector_store field has readOnly in JSON schema."""
        schema = VectorStoreConfig.model_json_schema()
        vs_prop = schema["properties"]["vector_store"]
        assert vs_prop.get("readOnly") is True


# ---------------------------------------------------------------------------
# DatabaseConfig
# ---------------------------------------------------------------------------


class TestDatabaseConfig:
    """Test DatabaseConfig defaults and serialization."""

    def test_defaults(self):
        """Default values are correct."""
        dc = DatabaseConfig(alias="TEST")
        assert dc.usable is False
        assert dc.pool is None
        assert not dc.vector_stores
        assert dc.tcp_connect_timeout == 30
        assert dc.username is None
        assert dc.dsn is None

    def test_pool_excluded_from_serialization(self):
        """pool field is excluded from model_dump."""
        dc = DatabaseConfig(alias="TEST")
        dumped = dc.model_dump()
        assert "pool" not in dumped

    def test_inherits_sensitive_fields(self):
        """DatabaseConfig inherits password and wallet_password from DatabaseSensitive."""
        dc = DatabaseConfig(alias="TEST", password="secret", wallet_password="wallet_secret")
        assert dc.password == "secret"
        assert dc.wallet_password == "wallet_secret"


# ---------------------------------------------------------------------------
# DatabaseUpdate
# ---------------------------------------------------------------------------


class TestDatabaseUpdate:
    """Test DatabaseUpdate schema."""

    def test_all_optional(self):
        """All fields default to None."""
        u = DatabaseUpdate()
        assert u.username is None
        assert u.dsn is None
        assert u.wallet_location is None
        assert u.config_dir is None
        assert u.tcp_connect_timeout is None
        assert u.password is None
