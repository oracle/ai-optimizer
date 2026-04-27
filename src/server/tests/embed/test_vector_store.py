"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for embed vector store utilities.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy

from server.app.database.sql import validate_vs_table_name
from server.app.embed.document import DoclingDocumentChunk
from server.app.embed.vector_store import (
    _prepare_documents,
    generate_vs_metadata,
    update_vs_comment,
)
from server.app.models.schemas import ModelIdentity
from server.app.oci.bucket import detect_changed_objects
from server.tests.conftest import make_test_vs_config

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


@pytest.mark.unit
@pytest.mark.parametrize(
    "alias,model_id",
    [
        ("café", "embed"),                # Latin accented (preserved as Unicode word char)
        ("докс", "embed"),                # Cyrillic
        ("тест", "embed"),                # different Cyrillic — must NOT collide with above
        ("文档", "embed"),                # CJK
        ("docs", "embed-é"),              # accent in model id
        ("alias with space", "embed"),    # whitespace collapses to _
        ("a-b.c/d", "embed"),             # punctuation collapses to _
    ],
)
def test_generate_vs_metadata_output_passes_validator(alias, model_id):
    """Generator output round-trips through ``validate_vs_table_name`` for any
    free-text alias / model id.

    The generator preserves Unicode word characters via ``re.sub(r"\\W", ...)``
    and the validator accepts the same grammar (``\\w+``); aligning the two
    avoids both (a) collisions from ASCII collapse and (b) ValueErrors on
    legacy auto-generated stores.
    """
    model = ModelIdentity(provider="openai", id=model_id)
    table_name, _ = generate_vs_metadata(
        embedding_model=model,
        chunk_size=1000,
        chunk_overlap=0,
        distance_strategy=DistanceStrategy.COSINE,
        alias=alias,
    )
    assert validate_vs_table_name(table_name) == table_name


@pytest.mark.unit
def test_generate_vs_metadata_distinct_non_ascii_aliases_dont_collide():
    """Distinct non-ASCII aliases of the same length must produce distinct
    table names — guards against ASCII-collapse collisions where every
    non-ASCII letter would map to ``_``.
    """
    model = ModelIdentity(provider="openai", id="embed")
    common = {
        "embedding_model": model,
        "chunk_size": 1000,
        "chunk_overlap": 0,
        "distance_strategy": DistanceStrategy.COSINE,
    }
    name_a, _ = generate_vs_metadata(alias="дока", **common)
    name_b, _ = generate_vs_metadata(alias="тест", **common)
    assert name_a != name_b


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


# ---------------------------------------------------------------------------
# update_vs_comment — SQL-injection regression
# ---------------------------------------------------------------------------


_VS_INJECT_TABLE = "VS_INJECT_TEST"
_COMMENT_PREFIX = f'COMMENT ON TABLE "{_VS_INJECT_TABLE}" IS \'GENAI: '


def _generate_comment(description: str | None = None, alias: str | None = None) -> str:
    """Build a comment_json the way the endpoint does."""
    _, comment_json = generate_vs_metadata(
        embedding_model=ModelIdentity(provider="openai", id="text-embedding-3-small"),
        chunk_size=1000,
        chunk_overlap=100,
        distance_strategy=DistanceStrategy.COSINE,
        index_type="HNSW",
        alias=alias,
        description=description,
    )
    return comment_json


async def _capture_comment_sql(cfg, comment_json: str) -> str:
    """Run update_vs_comment with execute_sql mocked; return the rendered SQL."""
    mock_exec = AsyncMock()
    with patch("server.app.embed.vector_store.execute_sql", new=mock_exec):
        await update_vs_comment(MagicMock(), cfg, comment_json)
    assert mock_exec.await_count == 1
    assert mock_exec.await_args is not None
    return mock_exec.await_args.args[1]


def _assert_well_formed_literal(sql: str) -> str:
    """Assert sql wraps a balanced 'GENAI: …' literal; return the literal body."""
    assert sql.startswith(_COMMENT_PREFIX)
    assert sql.endswith("'")
    body = sql[len(_COMMENT_PREFIX):-1]
    # Every ``'`` inside the body must be doubled (Oracle string-literal escape),
    # so the count is always even.
    assert body.count("'") % 2 == 0
    return body


@pytest.mark.unit
async def test_update_vs_comment_rejects_identifier_injection():
    """``X IS 'x'--`` table name is rejected before any SQL runs."""
    cfg = make_test_vs_config(vector_store="X IS 'x'--")

    with (
        patch("server.app.embed.vector_store.execute_sql", new_callable=AsyncMock) as mock_exec,
        pytest.raises(ValueError, match="Invalid vector store table name"),
    ):
        await update_vs_comment(MagicMock(), cfg, '{"alias": "x"}')

    mock_exec.assert_not_called()


@pytest.mark.unit
async def test_update_vs_comment_escapes_string_literal_injection():
    """Single quotes in a malicious description are doubled into the literal.

    If unescaped, the payload's leading ``x'`` would close the outer
    ``'GENAI: ...'`` string. Asserting the SELECT subquery appears with
    surrounding quotes doubled proves it stays inside the literal.
    """
    payload = "x' || (SELECT password FROM dba_users WHERE username='SYS') || 'x"
    comment_json = _generate_comment(description=payload)
    # Sanity: json.dumps does not escape single quotes — payload survives intact.
    assert "'SYS'" in comment_json

    sql = await _capture_comment_sql(make_test_vs_config(vector_store=_VS_INJECT_TABLE), comment_json)
    body = _assert_well_formed_literal(sql)
    assert "username=''SYS''" in body
    assert "x''" in body


@pytest.mark.unit
async def test_update_vs_comment_normal_payload_passes_through():
    """Ordinary alias/description still produces a syntactically valid statement."""
    comment_json = _generate_comment(alias="docs", description="Project documentation")

    sql = await _capture_comment_sql(make_test_vs_config(vector_store=_VS_INJECT_TABLE), comment_json)
    _assert_well_formed_literal(sql)
    assert '"alias": "docs"' in sql
    assert '"description": "Project documentation"' in sql
