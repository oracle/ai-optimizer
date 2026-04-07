"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for embed vector store utilities.
"""
# spell-checker: disable

import pytest
from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy

from server.app.embed.document import DoclingDocumentChunk
from server.app.embed.vector_store import _prepare_documents, generate_vs_metadata
from server.app.models.schemas import ModelIdentity
from server.app.oci.bucket import detect_changed_objects

# ---------------------------------------------------------------------------
# generate_vs_metadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_generate_vs_metadata_basic():
    """Generates valid table name and comment JSON."""
    model = ModelIdentity(provider="openai", id="text-embedding-3-small")
    table_name, comment_json = generate_vs_metadata(
        embedding_model=model,
        chunk_size=1000,
        chunk_overlap=100,
        distance_strategy=DistanceStrategy.COSINE,
    )
    assert table_name.startswith("OPENAI_TEXT_EMBEDDING_3_SMALL_1000_100_COSINE_HNSW")
    assert "openai/text-embedding-3-small" in comment_json
    assert '"chunk_size": 1000' in comment_json


@pytest.mark.unit
def test_generate_vs_metadata_with_alias():
    """Alias is prepended to table name."""
    model = ModelIdentity(provider="oci", id="embed-v3")
    table_name, comment_json = generate_vs_metadata(
        embedding_model=model,
        chunk_size=500,
        chunk_overlap=50,
        distance_strategy=DistanceStrategy.DOT_PRODUCT,
        alias="my_store",
    )
    assert table_name.startswith("MY_STORE_")
    assert '"alias": "my_store"' in comment_json


@pytest.mark.unit
def test_generate_vs_metadata_with_description():
    """Description is included in comment JSON."""
    model = ModelIdentity(provider="openai", id="embed")
    _, comment_json = generate_vs_metadata(
        embedding_model=model,
        chunk_size=1000,
        chunk_overlap=0,
        distance_strategy=DistanceStrategy.COSINE,
        description="Test description",
    )
    assert '"description": "Test description"' in comment_json


# ---------------------------------------------------------------------------
# _prepare_documents
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prepare_documents_empty_input():
    """Returns empty list for empty input without crashing."""
    result = _prepare_documents([])
    assert not result


@pytest.mark.unit
def test_prepare_documents_dedup():
    """Duplicate chunks are removed."""
    chunks = [
        DoclingDocumentChunk(page_content="same text", metadata={"id": "1"}),
        DoclingDocumentChunk(page_content="same text", metadata={"id": "2"}),
        DoclingDocumentChunk(page_content="different text", metadata={"id": "3"}),
    ]
    result = _prepare_documents(chunks)
    assert len(result) == 2
    assert result[0].page_content == "same text"
    assert result[1].page_content == "different text"


@pytest.mark.unit
def test_prepare_documents_preserves_order():
    """First occurrence of duplicate is kept."""
    chunks = [
        DoclingDocumentChunk(page_content="A", metadata={"id": "first"}),
        DoclingDocumentChunk(page_content="B", metadata={"id": "second"}),
        DoclingDocumentChunk(page_content="A", metadata={"id": "third"}),
    ]
    result = _prepare_documents(chunks)
    assert len(result) == 2
    assert result[0].metadata["id"] == "first"


# ---------------------------------------------------------------------------
# detect_changed_objects (OCI bucket key flattening)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detect_changed_objects_with_prefix():
    """Bucket objects with folder prefixes match processed_objects keyed by flattened key."""
    current = [
        {"name": "docs/file.pdf", "etag": "abc", "time_modified": "2026-01-01"},
    ]
    processed = {
        "docs_file.pdf": {"etag": "abc", "time_modified": "2026-01-01", "size": 100},
    }
    new, modified = detect_changed_objects(current, processed)
    assert len(new) == 0
    assert len(modified) == 0


@pytest.mark.unit
def test_detect_changed_objects_prefix_modified():
    """Detects modification when bucket path has prefix but etag changed."""
    current = [
        {"name": "folder/report.pdf", "etag": "new_etag", "time_modified": "2026-02-01"},
    ]
    processed = {
        "folder_report.pdf": {"etag": "old_etag", "time_modified": "2026-01-01", "size": 200},
    }
    new, modified = detect_changed_objects(current, processed)
    assert len(new) == 0
    assert len(modified) == 1


@pytest.mark.unit
def test_detect_changed_objects_no_prefix():
    """Still works correctly with flat bucket keys (no prefix)."""
    current = [
        {"name": "file.pdf", "etag": "abc", "time_modified": "2026-01-01"},
        {"name": "new.pdf", "etag": "xyz", "time_modified": "2026-01-01"},
    ]
    processed = {
        "file.pdf": {"etag": "abc", "time_modified": "2026-01-01", "size": 100},
    }
    new, modified = detect_changed_objects(current, processed)
    assert len(new) == 1
    assert new[0]["name"] == "new.pdf"
    assert len(modified) == 0


@pytest.mark.unit
def test_detect_changed_objects_same_basename_different_prefix():
    """Distinct bucket keys with same basename are treated as separate objects."""
    current = [
        {"name": "reports/q1.pdf", "etag": "abc", "time_modified": "2026-01-01"},
        {"name": "policies/q1.pdf", "etag": "xyz", "time_modified": "2026-01-01"},
    ]
    processed = {
        "reports_q1.pdf": {"etag": "abc", "time_modified": "2026-01-01", "size": 100},
    }
    new, modified = detect_changed_objects(current, processed)
    assert len(new) == 1
    assert new[0]["name"] == "policies/q1.pdf"
    assert len(modified) == 0
