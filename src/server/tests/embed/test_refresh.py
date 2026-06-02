"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.embed.refresh.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.app.database.schemas import DatabaseConfig
from server.app.embed.refresh import refresh_vector_store_from_bucket
from server.app.embed.schemas import VectorStoreConfig
from server.app.models.schemas import ModelIdentity
from server.app.oci.schemas import OciProfileConfig
from server.tests.constants import TEST_OPENAI_EMBED_ID

MODULE = "server.app.embed.refresh"

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


def _make_db_config(**overrides) -> DatabaseConfig:
    defaults = {"alias": "TEST", "username": "test", "password": "test", "dsn": "test:1521/pdb"}
    return DatabaseConfig(**{**defaults, **overrides})


def _make_vs_config(**overrides) -> VectorStoreConfig:
    defaults = {
        "embedding_model": ModelIdentity(provider="openai", id=TEST_OPENAI_EMBED_ID),
        "chunk_size": 500,
        "chunk_overlap": 50,
    }
    return VectorStoreConfig(**{**defaults, **overrides})


def _make_profile(**overrides) -> OciProfileConfig:
    defaults = {"auth_profile": "TEST", "namespace": "ns", "region": "us-phoenix-1"}
    return OciProfileConfig(**{**defaults, **overrides})


def _bucket_obj(name, size=1024, etag="e1", time_modified="2025-01-01T00:00:00"):
    return {"name": name, "size": size, "etag": etag, "time_modified": time_modified}


# ---------------------------------------------------------------------------
# refresh_vector_store_from_bucket
# ---------------------------------------------------------------------------


class TestRefreshVectorStoreFromBucket:
    """Test the bucket-to-vector-store refresh pipeline."""

    async def test_empty_bucket_objects_returns_early(self):
        """No bucket objects results in a no-op return."""
        result = await refresh_vector_store_from_bucket(
            vector_store_config=_make_vs_config(),
            bucket_name="test-bucket",
            bucket_objects=[],
            db_config=_make_db_config(),
            embed_client=MagicMock(),
            oci_profile=_make_profile(),
        )
        assert result["processed_files"] == 0
        assert "No new or modified" in result["message"]

    async def test_all_downloads_fail_returns_error(self):
        """When all downloads fail, error dict is returned."""
        with (
            patch(f"{MODULE}.download_object", side_effect=RuntimeError("download failed")),
            patch(f"{MODULE}.tempfile.mkdtemp", return_value="/tmp/refresh_test"),
            patch(f"{MODULE}.Path") as mock_path,
            patch(f"{MODULE}.shutil.rmtree"),
        ):
            mock_path.return_value.exists.return_value = True

            result = await refresh_vector_store_from_bucket(
                vector_store_config=_make_vs_config(),
                bucket_name="test-bucket",
                bucket_objects=[_bucket_obj("fail.pdf")],
                db_config=_make_db_config(),
                embed_client=MagicMock(),
                oci_profile=_make_profile(),
            )

        assert result["processed_files"] == 0
        assert "errors" in result

    async def test_successful_new_files_processing(self):
        """Successful processing returns correct counts."""
        mock_docos = [MagicMock(), MagicMock(), MagicMock()]

        with (
            patch(f"{MODULE}.download_object", side_effect=["/tmp/r/a.pdf", "/tmp/r/b.pdf"]),
            patch(f"{MODULE}.load_and_split_documents", return_value=(mock_docos, [], {})),
            patch(f"{MODULE}.populate_vs", new_callable=AsyncMock),
            patch(f"{MODULE}.tempfile.mkdtemp", return_value="/tmp/refresh_test"),
            patch(f"{MODULE}.Path") as mock_path,
            patch(f"{MODULE}.shutil.rmtree"),
        ):
            mock_path.return_value.exists.return_value = True

            result = await refresh_vector_store_from_bucket(
                vector_store_config=_make_vs_config(),
                bucket_name="test-bucket",
                bucket_objects=[_bucket_obj("a.pdf"), _bucket_obj("b.pdf")],
                db_config=_make_db_config(),
                embed_client=MagicMock(),
                oci_profile=_make_profile(),
            )

        assert result["processed_files"] == 2
        assert result["new_files"] == 2
        assert result["updated_files"] == 0
        assert result["total_chunks"] == 3

    async def test_mixed_new_and_modified_files(self):
        """Modified objects are counted separately from new objects."""
        obj_a = _bucket_obj("a.pdf")
        obj_b = _bucket_obj("b.pdf")
        obj_c = _bucket_obj("c.pdf")
        mock_docos = [MagicMock()]

        with (
            patch(f"{MODULE}.download_object", side_effect=["/tmp/r/a.pdf", "/tmp/r/b.pdf", "/tmp/r/c.pdf"]),
            patch(f"{MODULE}.load_and_split_documents", return_value=(mock_docos, [], {})),
            patch(f"{MODULE}.populate_vs", new_callable=AsyncMock),
            patch(f"{MODULE}.tempfile.mkdtemp", return_value="/tmp/refresh_test"),
            patch(f"{MODULE}.Path") as mock_path,
            patch(f"{MODULE}.shutil.rmtree"),
        ):
            mock_path.return_value.exists.return_value = True

            result = await refresh_vector_store_from_bucket(
                vector_store_config=_make_vs_config(),
                bucket_name="test-bucket",
                bucket_objects=[obj_a, obj_b, obj_c],
                db_config=_make_db_config(),
                embed_client=MagicMock(),
                oci_profile=_make_profile(),
                modified_objects=[obj_a],
            )

        assert result["processed_files"] == 3
        assert result["updated_files"] == 1
        assert result["new_files"] == 2

    async def test_partial_download_failure(self):
        """When some downloads fail, only successful files are processed."""
        mock_docos = [MagicMock()]

        with (
            patch(
                f"{MODULE}.download_object",
                side_effect=["/tmp/r/a.pdf", RuntimeError("fail"), "/tmp/r/c.pdf"],
            ),
            patch(f"{MODULE}.load_and_split_documents", return_value=(mock_docos, [], {})),
            patch(f"{MODULE}.populate_vs", new_callable=AsyncMock),
            patch(f"{MODULE}.tempfile.mkdtemp", return_value="/tmp/refresh_test"),
            patch(f"{MODULE}.Path") as mock_path,
            patch(f"{MODULE}.shutil.rmtree"),
        ):
            mock_path.return_value.exists.return_value = True

            result = await refresh_vector_store_from_bucket(
                vector_store_config=_make_vs_config(),
                bucket_name="test-bucket",
                bucket_objects=[_bucket_obj("a.pdf"), _bucket_obj("b.pdf"), _bucket_obj("c.pdf")],
                db_config=_make_db_config(),
                embed_client=MagicMock(),
                oci_profile=_make_profile(),
            )

        assert result["processed_files"] == 2

    async def test_modified_filenames_only_include_successful_downloads(self):
        """modified_filenames passed to populate_vs excludes failed downloads."""
        obj_a = _bucket_obj("a.pdf")
        obj_b = _bucket_obj("b.pdf")
        mock_docos = [MagicMock()]

        with (
            patch(f"{MODULE}.download_object", side_effect=["/tmp/r/a.pdf", RuntimeError("fail")]),
            patch(f"{MODULE}.load_and_split_documents", return_value=(mock_docos, [], {})),
            patch(f"{MODULE}.populate_vs", new_callable=AsyncMock) as mock_populate,
            patch(f"{MODULE}.tempfile.mkdtemp", return_value="/tmp/refresh_test"),
            patch(f"{MODULE}.Path") as mock_path,
            patch(f"{MODULE}.shutil.rmtree"),
        ):
            mock_path.return_value.exists.return_value = True

            await refresh_vector_store_from_bucket(
                vector_store_config=_make_vs_config(),
                bucket_name="test-bucket",
                bucket_objects=[obj_a, obj_b],
                db_config=_make_db_config(),
                embed_client=MagicMock(),
                oci_profile=_make_profile(),
                modified_objects=[obj_a, obj_b],
            )

        call_kwargs = mock_populate.call_args.kwargs
        # Only a.pdf was downloaded successfully
        assert call_kwargs["modified_filenames"] == ["a.pdf"]

    async def test_populate_vs_called_with_correct_args(self):
        """populate_vs receives the correct arguments."""
        db_config = _make_db_config()
        vs_config = _make_vs_config()
        embed_client = MagicMock()
        mock_docos = [MagicMock()]

        with (
            patch(f"{MODULE}.download_object", return_value="/tmp/r/doc.pdf"),
            patch(f"{MODULE}.load_and_split_documents", return_value=(mock_docos, [], {})),
            patch(f"{MODULE}.populate_vs", new_callable=AsyncMock) as mock_populate,
            patch(f"{MODULE}.tempfile.mkdtemp", return_value="/tmp/refresh_test"),
            patch(f"{MODULE}.Path") as mock_path,
            patch(f"{MODULE}.shutil.rmtree"),
        ):
            mock_path.return_value.exists.return_value = True

            await refresh_vector_store_from_bucket(
                vector_store_config=vs_config,
                bucket_name="test-bucket",
                bucket_objects=[_bucket_obj("doc.pdf")],
                db_config=db_config,
                embed_client=embed_client,
                oci_profile=_make_profile(),
                rate_limit=5,
            )

        mock_populate.assert_called_once()
        call_kwargs = mock_populate.call_args.kwargs
        assert call_kwargs["db_config"] is db_config
        assert call_kwargs["vector_store"] is vs_config
        assert call_kwargs["embed_client"] is embed_client
        assert call_kwargs["input_data"] is mock_docos
        assert call_kwargs["rate_limit"] == 5

    async def test_modified_objects_none_sets_modified_filenames_none(self):
        """When modified_objects is None, modified_filenames is None."""
        mock_docos = [MagicMock()]

        with (
            patch(f"{MODULE}.download_object", return_value="/tmp/r/doc.pdf"),
            patch(f"{MODULE}.load_and_split_documents", return_value=(mock_docos, [], {})),
            patch(f"{MODULE}.populate_vs", new_callable=AsyncMock) as mock_populate,
            patch(f"{MODULE}.tempfile.mkdtemp", return_value="/tmp/refresh_test"),
            patch(f"{MODULE}.Path") as mock_path,
            patch(f"{MODULE}.shutil.rmtree"),
        ):
            mock_path.return_value.exists.return_value = True

            await refresh_vector_store_from_bucket(
                vector_store_config=_make_vs_config(),
                bucket_name="test-bucket",
                bucket_objects=[_bucket_obj("doc.pdf")],
                db_config=_make_db_config(),
                embed_client=MagicMock(),
                oci_profile=_make_profile(),
                modified_objects=None,
            )

        call_kwargs = mock_populate.call_args.kwargs
        assert call_kwargs["modified_filenames"] is None

    async def test_file_metadata_built_from_bucket_objects(self):
        """file_metadata dict is correctly built and passed to load_and_split_documents."""
        with (
            patch(f"{MODULE}.download_object", return_value="/tmp/r/doc.pdf"),
            patch(f"{MODULE}.load_and_split_documents", return_value=([], [], {})) as mock_load,
            patch(f"{MODULE}.populate_vs", new_callable=AsyncMock),
            patch(f"{MODULE}.tempfile.mkdtemp", return_value="/tmp/refresh_test"),
            patch(f"{MODULE}.Path") as mock_path,
            patch(f"{MODULE}.shutil.rmtree"),
        ):
            mock_path.return_value.exists.return_value = True

            await refresh_vector_store_from_bucket(
                vector_store_config=_make_vs_config(),
                bucket_name="my-bucket",
                bucket_objects=[_bucket_obj("folder/doc.pdf", size=2048, etag="e1", time_modified="t1")],
                db_config=_make_db_config(),
                embed_client=MagicMock(),
                oci_profile=_make_profile(),
            )

        call_kwargs = mock_load.call_args.kwargs
        metadata = call_kwargs["file_metadata"]
        assert "folder_doc.pdf" in metadata
        assert metadata["folder_doc.pdf"]["size"] == 2048
        assert metadata["folder_doc.pdf"]["etag"] == "e1"
        assert metadata["folder_doc.pdf"]["bucket_name"] == "my-bucket"
