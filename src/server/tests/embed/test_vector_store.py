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
    get_processed_objects_metadata,
    get_vector_store_files,
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
# get_processed_objects_metadata (server-side aggregation)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_processed_objects_metadata_new_format():
    """New-format query returns one row per filename; size is cast to int."""
    rows = [
        ("a.pdf", "etag-a", "2026-01-01T00:00:00", "100"),
        ("b.pdf", "etag-b", "2026-01-02T00:00:00", "200"),
    ]
    with patch(
        "server.app.embed.vector_store.execute_sql",
        new_callable=AsyncMock,
        return_value=rows,
    ) as mock_exec:
        result = await get_processed_objects_metadata(MagicMock(), "VS_TBL")

    assert result == {
        "a.pdf": {"etag": "etag-a", "time_modified": "2026-01-01T00:00:00", "size": 100},
        "b.pdf": {"etag": "etag-b", "time_modified": "2026-01-02T00:00:00", "size": 200},
    }
    sql_arg = mock_exec.await_args_list[0].args[1]
    assert "GROUP BY" in sql_arg
    assert "$.filename" in sql_arg


@pytest.mark.unit
async def test_get_processed_objects_metadata_legacy_fallback():
    """Empty new-format result triggers the legacy 'source' fallback query."""
    legacy_rows = [("oci://bucket/folder/legacy.pdf",)]

    async def _exec(_conn, sql, *_a, **_kw):
        return [] if "$.filename" in sql else legacy_rows

    with patch("server.app.embed.vector_store.execute_sql", side_effect=_exec) as mock_exec:
        result = await get_processed_objects_metadata(MagicMock(), "VS_TBL")

    assert result == {"legacy.pdf": {"etag": None, "time_modified": None, "size": None}}
    assert mock_exec.await_count == 2


@pytest.mark.unit
async def test_get_processed_objects_metadata_empty():
    """Both queries empty → empty dict."""
    with patch("server.app.embed.vector_store.execute_sql", new_callable=AsyncMock, return_value=[]):
        result = await get_processed_objects_metadata(MagicMock(), "VS_TBL")
    assert result == {}


@pytest.mark.unit
async def test_get_processed_objects_metadata_swallows_errors():
    """SQL errors are logged and yield an empty dict (preserves prior behavior)."""
    with patch(
        "server.app.embed.vector_store.execute_sql",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        result = await get_processed_objects_metadata(MagicMock(), "VS_TBL")
    assert result == {}


@pytest.mark.unit
async def test_get_processed_objects_metadata_propagates_overflow():
    """Result-set overflow must propagate so refresh fails loudly instead of
    silently treating every object as new and skipping stale-chunk cleanup."""
    from server.app.database.sql import ResultSetTooLargeError

    with (
        patch(
            "server.app.embed.vector_store.execute_sql",
            new_callable=AsyncMock,
            side_effect=ResultSetTooLargeError("too big"),
        ),
        pytest.raises(ResultSetTooLargeError),
    ):
        await get_processed_objects_metadata(MagicMock(), "VS_TBL")


# ---------------------------------------------------------------------------
# get_vector_store_files (server-side aggregation)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_vector_store_files_empty():
    """Empty store yields zero counts."""
    with patch("server.app.embed.vector_store.execute_sql", new_callable=AsyncMock, return_value=[]):
        result = await get_vector_store_files(MagicMock(), "VS_TBL")

    assert result == {
        "vector_store": "VS_TBL",
        "total_files": 0,
        "total_chunks": 0,
        "orphaned_chunks": 0,
        "files": [],
    }


@pytest.mark.unit
async def test_get_vector_store_files_aggregates_new_format():
    """One row per filename with chunk_count from server-side COUNT(*)."""
    # (filename_raw, source_raw, chunk_count, etag, time_modified, size_str)
    rows = [
        ("a.pdf", None, 5, "etag-a", "2026-01-01", "100"),
        ("b.pdf", None, 3, "etag-b", "2026-01-02", "200"),
    ]
    with patch(
        "server.app.embed.vector_store.execute_sql",
        new_callable=AsyncMock,
        return_value=rows,
    ):
        result = await get_vector_store_files(MagicMock(), "VS_TBL")

    assert result["total_files"] == 2
    assert result["total_chunks"] == 8
    assert result["orphaned_chunks"] == 0
    files = {f["filename"]: f for f in result["files"]}
    assert files["a.pdf"]["chunk_count"] == 5
    assert files["a.pdf"]["size"] == 100
    assert files["b.pdf"]["chunk_count"] == 3


@pytest.mark.unit
async def test_get_vector_store_files_legacy_source_basenamed():
    """Legacy rows with only `source` use os.path.basename for the filename."""
    rows = [
        (None, "oci://bucket/folder/legacy.pdf", 4, None, None, None),
    ]
    with patch(
        "server.app.embed.vector_store.execute_sql",
        new_callable=AsyncMock,
        return_value=rows,
    ):
        result = await get_vector_store_files(MagicMock(), "VS_TBL")

    assert result["total_files"] == 1
    assert result["files"][0]["filename"] == "legacy.pdf"
    assert result["files"][0]["chunk_count"] == 4
    assert result["files"][0]["size"] is None


@pytest.mark.unit
async def test_get_vector_store_files_orphans_counted():
    """Rows with neither filename nor source contribute to orphaned_chunks only."""
    rows = [
        ("a.pdf", None, 2, None, None, None),
        (None, None, 7, None, None, None),  # orphan group
    ]
    with patch(
        "server.app.embed.vector_store.execute_sql",
        new_callable=AsyncMock,
        return_value=rows,
    ):
        result = await get_vector_store_files(MagicMock(), "VS_TBL")

    assert result["total_files"] == 1
    assert result["total_chunks"] == 2
    assert result["orphaned_chunks"] == 7


# ---------------------------------------------------------------------------
# update_vs_comment input handling
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
async def test_update_vs_comment_rejects_invalid_table_identifiers():
    """``X IS 'x'--`` table name is rejected before any SQL runs."""
    cfg = make_test_vs_config(vector_store="X IS 'x'--")

    with (
        patch("server.app.embed.vector_store.execute_sql", new_callable=AsyncMock) as mock_exec,
        pytest.raises(ValueError, match="Invalid vector store table name"),
    ):
        await update_vs_comment(MagicMock(), cfg, '{"alias": "x"}')

    mock_exec.assert_not_called()


@pytest.mark.unit
async def test_update_vs_comment_doubles_single_quotes_in_description():
    """Single quotes in the description are doubled into the SQL literal.

    Description values reach the SQL string literal unescaped from the
    JSON layer, so the comment-update path must double every ``'`` so the
    value stays inside the surrounding ``'GENAI: ...'`` literal.
    """
    payload = "x' || (SELECT col FROM tbl WHERE name='X') || 'x"
    comment_json = _generate_comment(description=payload)
    # Sanity: json.dumps does not escape single quotes — value survives intact.
    assert "'X'" in comment_json

    sql = await _capture_comment_sql(make_test_vs_config(vector_store=_VS_INJECT_TABLE), comment_json)
    body = _assert_well_formed_literal(sql)
    assert "name=''X''" in body
    assert "x''" in body


@pytest.mark.unit
async def test_update_vs_comment_normal_payload_passes_through():
    """Ordinary alias/description still produces a syntactically valid statement."""
    comment_json = _generate_comment(alias="docs", description="Project documentation")

    sql = await _capture_comment_sql(make_test_vs_config(vector_store=_VS_INJECT_TABLE), comment_json)
    _assert_well_formed_literal(sql)
    assert '"alias": "docs"' in sql
    assert '"description": "Project documentation"' in sql
