"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.mcp.tools.schemas utilities.
"""
# spell-checker: disable

from __future__ import annotations

from server.app.core.settings import settings
from server.app.database.schemas import DatabaseConfig
from server.app.mcp.tools import schemas
from server.app.models.schemas import ModelIdentity
from server.app.oci.schemas import OciProfileConfig


def test_get_oci_profile_match() -> None:
    """get_oci_profile returns matching profile."""
    target = OciProfileConfig(auth_profile="PROD", tenancy="ocid1.tenancy.oc1..prod")
    settings.oci_configs = [
        OciProfileConfig(auth_profile="DEFAULT"),
        target,
    ]
    settings.client_settings.oci.auth_profile = "PROD"

    result = schemas.get_oci_profile()

    assert result is target


def test_get_oci_profile_missing() -> None:
    """get_oci_profile returns None when missing."""
    settings.oci_configs = []
    settings.client_settings.oci.auth_profile = "UNKNOWN"

    assert schemas.get_oci_profile() is None


def test_get_database_pool_found() -> None:
    """get_database_pool returns pool when present and usable."""
    pool = object()
    cfg = DatabaseConfig(alias="CORE")
    cfg.pool = pool  # type: ignore[assignment]
    cfg.usable = True
    settings.database_configs = [cfg]
    settings.client_settings.database.alias = "CORE"

    assert schemas.get_database_pool() is pool


def test_get_database_pool_missing() -> None:
    """get_database_pool returns None without pool."""
    settings.database_configs = []
    settings.client_settings.database.alias = "MISSING"

    assert schemas.get_database_pool() is None


def test_generate_vs_metadata_success() -> None:
    """generate_vs_metadata composes expected table/comment."""
    from server.app.embed.vector_store import generate_vs_metadata

    table_name, comment = generate_vs_metadata(
        embedding_model=ModelIdentity(provider="openai", id="text-embed"),
        chunk_size=512,
        chunk_overlap=32,
        distance_strategy="COSINE",
        index_type="HNSW",
        alias="DOCS",
        description="Test docs",
    )

    assert table_name == "DOCS_OPENAI_TEXT_EMBED_512_32_COSINE_HNSW"
    assert comment is not None
    assert '"alias": "DOCS"' in comment
    assert '"description": "Test docs"' in comment
    assert '"distance_strategy": "COSINE"' in comment
