"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Document replacement in the split-and-embed pipeline and Oracle vector stores.
"""
# spell-checker: disable

import contextlib
import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import oracledb
import pytest
from langchain_core.embeddings import Embeddings
from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy

from server.app.database.config import create_pool, create_sync_connection
from server.app.embed.schemas import DoclingDocumentChunk, VectorStoreConfig
from server.app.embed.vector_store import _merge_and_index_vector_store, _populate_vs_sync, _prepare_documents
from server.app.models.schemas import ModelIdentity
from server.tests.conftest import make_core_db_config


class LocalEmbeddings(Embeddings):
    """Deterministic vectors without a model service for database tests."""

    def embed_query(self, text: str) -> list[float]:
        return [float(value) / 255 for value in hashlib.sha256(text.encode()).digest()[:8]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def _chunks(filename: str, texts: list[str], revision: str = "old") -> list[DoclingDocumentChunk]:
    return [
        DoclingDocumentChunk(
            text,
            {"id": f"{filename}_{idx}", "filename": filename, "source": filename, "revision": revision},
        )
        for idx, text in enumerate(texts, start=1)
    ]


@pytest.mark.unit
def test_prepare_documents_keeps_shared_text_in_different_files():
    chunks = _chunks("a.md", ["Shared paragraph", "Shared paragraph"]) + _chunks("b.md", ["Shared paragraph"])
    assert [chunk.metadata["filename"] for chunk in _prepare_documents(chunks)] == ["a.md", "b.md"]


@pytest.mark.unit
@pytest.mark.parametrize("split_by_filename", [False, True])
async def test_pipeline_replaces_only_filenames_with_chunks(tmp_path, split_by_filename):
    from server.app.api.v1.endpoints import embed as endpoint
    from server.tests.api.conftest import _create_mock_pool

    db_config = make_core_db_config()
    db_config.pool = _create_mock_pool(AsyncMock())
    request = VectorStoreConfig(
        embedding_model=ModelIdentity(provider="openai", id="test-embed"),
        distance_strategy=DistanceStrategy.COSINE,
        chunk_size=1000,
        split_by_filename=split_by_filename,
    )
    chunks = _chunks("a.md", ["new a", "new tail"]) + _chunks("b.md", ["new b"])
    results = {
        "processed_files": [{"filename": "a.md", "chunks": 2}, {"filename": "b.md", "chunks": 1}],
        "skipped_files": [{"filename": "skipped.md", "reason": "Cannot parse"}],
        "total_chunks": 3,
    }
    handle = MagicMock(set_progress=AsyncMock())
    with (
        patch.object(endpoint, "get_oci_profile", return_value=MagicMock()),
        patch.object(endpoint, "get_client_embed", return_value=LocalEmbeddings()),
        patch.object(endpoint, "load_and_split_documents", return_value=(chunks, [], results)),
        patch.object(endpoint, "populate_vs", new_callable=AsyncMock) as populate,
        patch.object(endpoint, "update_vs_comment", new_callable=AsyncMock),
        patch.object(endpoint, "discover_vector_stores", new_callable=AsyncMock, return_value=[]),
        patch.object(endpoint, "get_database_settings", return_value=None),
    ):
        result = await endpoint._run_split_embed_pipeline(handle, request, 0, "server", tmp_path, [], None, db_config)

    filenames = [call.kwargs["modified_filenames"] for call in populate.await_args_list]
    assert filenames == ([["a.md"], ["b.md"]] if split_by_filename else [["a.md", "b.md"]])
    assert result.skipped_files[0].filename == "skipped.md"


@pytest.mark.unit
def test_replacement_rolls_back_without_committing_deleted_rows():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = RuntimeError("Insertion failed")
    store = VectorStoreConfig(vector_store="REPLACEMENT_TEST", index_type="HNSW")
    temporary = store.model_copy(update={"vector_store": "REPLACEMENT_TEST_TMP"})
    with (
        patch("server.app.embed.vector_store.OracleVS"),
        patch("server.app.embed.vector_store.drop_index_if_exists"),
        patch("server.app.embed.vector_store._normalize_metadata_oson"),
        pytest.raises(RuntimeError, match="Insertion failed"),
    ):
        _merge_and_index_vector_store(connection, store, temporary, LocalEmbeddings(), ["a.md"])

    cursor.executemany.assert_called_once()
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()


@pytest.fixture
def replacement_store(oracle_db_container):
    """Use isolated tables in the real Oracle integration database."""
    del oracle_db_container
    config = make_core_db_config()
    store = VectorStoreConfig(
        vector_store=f"PYTEST_REPLACE_{uuid.uuid4().hex[:12].upper()}",
        distance_strategy=DistanceStrategy.COSINE,
        index_type="HNSW",
    )
    connection = create_sync_connection(config)
    try:
        yield config, store, connection
    finally:
        for table in (store.vector_store, f"{store.vector_store}_TMP"):
            with contextlib.suppress(oracledb.DatabaseError), connection.cursor() as cursor:
                cursor.execute(f'DROP TABLE "{table}" PURGE')
        connection.close()


def _stored_rows(connection, store):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT id, text, metadata, embedding FROM "{store.vector_store}" ORDER BY id')
        return [(row[0], row[1].read(), row[2], list(row[3])) for row in cursor.fetchall()]


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.parametrize("old_count,new_count", [(1, 1), (2, 3), (3, 1)])
def test_reupload_replaces_content_metadata_and_embeddings(replacement_store, old_count, new_count):
    config, store, connection = replacement_store
    embeddings = LocalEmbeddings()
    previous = _chunks("replacement.md", [f"ALPHA_OLD_ONLY {idx}" for idx in range(old_count)])
    unrelated = _chunks("unrelated.md", ["Unrelated document"])
    _populate_vs_sync(config, store, embeddings, previous + unrelated)
    unrelated_before = [row for row in _stored_rows(connection, store) if row[2]["filename"] == "unrelated.md"]

    current = _chunks("replacement.md", [f"BETA_NEW_ONLY {idx}" for idx in range(new_count)], "new")
    _populate_vs_sync(config, store, embeddings, current, modified_filenames=["replacement.md"])
    stored = _stored_rows(connection, store)
    replaced = [row for row in stored if row[2]["filename"] == "replacement.md"]
    assert len(replaced) == new_count
    assert {row[1] for row in replaced} == {chunk.page_content for chunk in current}
    assert all(row[2]["revision"] == "new" for row in replaced)
    assert all(row[3] == pytest.approx(embeddings.embed_query(row[1])) for row in replaced)
    assert [row for row in stored if row[2]["filename"] == "unrelated.md"] == unrelated_before

    _populate_vs_sync(config, store, embeddings, current, modified_filenames=["replacement.md"])
    assert _stored_rows(connection, store) == stored


@pytest.mark.integration
@pytest.mark.db
def test_unstaged_files_and_shared_content_preserve_document_identity(replacement_store):
    config, store, connection = replacement_store
    embeddings = LocalEmbeddings()
    previous = _chunks("skipped.md", ["Previous usable text"])
    _populate_vs_sync(config, store, embeddings, previous)
    previous_rows = _stored_rows(connection, store)

    current = _chunks("a.md", ["Shared paragraph"]) + _chunks("b.md", ["Shared paragraph"])
    _populate_vs_sync(config, store, embeddings, current, modified_filenames=["a.md", "b.md", "skipped.md"])
    rows = _stored_rows(connection, store)
    assert {row[2]["filename"] for row in rows} == {"a.md", "b.md", "skipped.md"}
    assert [row for row in rows if row[2]["filename"] == "skipped.md"] == previous_rows

    _populate_vs_sync(config, store, embeddings, [], modified_filenames=["skipped.md"])
    assert _stored_rows(connection, store) == rows


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.parametrize("failure", ["embedding", "merge"])
def test_failed_replacement_preserves_previous_document(replacement_store, failure):
    config, store, connection = replacement_store
    embeddings = LocalEmbeddings()
    previous = _chunks("replacement.md", ["Previous usable text", "Old tail"])
    _populate_vs_sync(config, store, embeddings, previous)
    previous_rows = _stored_rows(connection, store)

    if failure == "merge":
        # Reject inserts into the target while allowing embedding into staging.
        with connection.cursor() as cursor:
            cursor.execute(
                f'CREATE TRIGGER "{store.vector_store}_FAIL" BEFORE INSERT ON "{store.vector_store}" '
                "BEGIN RAISE_APPLICATION_ERROR(-20001, 'Test insertion failure'); END;"
            )
        failure_context = contextlib.nullcontext()
    else:
        failure_context = patch.object(
            embeddings, "embed_documents", side_effect=RuntimeError("Test embedding failure")
        )

    with failure_context, pytest.raises((RuntimeError, oracledb.DatabaseError)):
        _populate_vs_sync(
            config,
            store,
            embeddings,
            _chunks("replacement.md", ["Updated content"], "new"),
            modified_filenames=["replacement.md"],
        )
    assert _stored_rows(connection, store) == previous_rows


@pytest.mark.integration
@pytest.mark.db
async def test_local_markdown_pipeline_replaces_same_filename(replacement_store, tmp_path):
    """Parse two actual Markdown uploads and merge through the API job body."""
    from server.app.api.v1.endpoints import embed as endpoint

    config, store, connection = replacement_store
    pool = await create_pool(config)
    config.pool = pool
    request = VectorStoreConfig(
        embedding_model=ModelIdentity(provider="openai", id="test-embed"),
        distance_strategy=DistanceStrategy.COSINE,
        chunk_size=2048,
        chunk_overlap=410,
        index_type="HNSW",
    )
    try:
        with (
            patch.object(endpoint, "get_oci_profile", return_value=MagicMock()),
            patch.object(endpoint, "get_client_embed", return_value=LocalEmbeddings()),
            patch.object(endpoint, "generate_vs_metadata", return_value=(store.vector_store, "{}")),
            patch.object(endpoint, "get_database_settings", return_value=None),
        ):
            for marker in ("ALPHA_OLD_ONLY", "BETA_NEW_ONLY"):
                work_dir = tmp_path / marker
                work_dir.mkdir()
                document = work_dir / "replacement-repro.md"
                document.write_text(f"# Upload replacement reproduction\n\nThe current procedure marker is {marker}.\n")
                result = await endpoint._run_split_embed_pipeline(
                    MagicMock(set_progress=AsyncMock()), request, 0, "server", work_dir, [document], None, config
                )
                assert result.total_chunks == 1
                assert not result.skipped_files
                rows = _stored_rows(connection, store)
                assert len(rows) == 1
                # Docling's Markdown export escapes underscores in plain text.
                stored_text = rows[0][1].replace("\\_", "_")
                assert marker in stored_text
                assert rows[0][2]["filename"] == document.name
                assert rows[0][2]["source"] == str(document)
                if marker == "BETA_NEW_ONLY":
                    assert "ALPHA_OLD_ONLY" not in stored_text
    finally:
        await pool.close()
