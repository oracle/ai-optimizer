"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/embed.py
Tests for document embedding and vector store endpoints.
"""
# pylint: disable=protected-access redefined-outer-name
# Pytest fixtures use parameter injection where fixture names match parameters

from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import json

import pytest
from fastapi import HTTPException, UploadFile
from pydantic import HttpUrl

from common.schema import DatabaseVectorStorage, VectorStoreRefreshRequest
from server.api.v1 import embed
from server.api.utils.databases import DbException
from unit.server.api.conftest import create_mock_aiohttp_session


@pytest.fixture
def split_embed_mocks():
    """Fixture providing bundled mocks for split_embed tests."""
    with (
        patch("server.api.v1.embed.utils_oci.get") as mock_oci_get,
        patch("server.api.v1.embed.utils_embed.get_temp_directory") as mock_get_temp,
        patch("server.api.v1.embed.utils_embed.load_and_split_documents") as mock_load_split,
        patch("server.api.v1.embed.utils_models.get_client_embed") as mock_get_embed,
        patch("server.api.v1.embed.functions.get_vs_table") as mock_get_vs_table,
        patch("server.api.v1.embed.utils_embed.populate_vs") as mock_populate,
        patch("server.api.v1.embed.utils_databases.get_client_database") as mock_get_db,
        patch("shutil.rmtree") as mock_rmtree,
    ):
        yield {
            "oci_get": mock_oci_get,
            "get_temp": mock_get_temp,
            "load_split": mock_load_split,
            "get_embed": mock_get_embed,
            "get_vs_table": mock_get_vs_table,
            "populate": mock_populate,
            "get_db": mock_get_db,
            "rmtree": mock_rmtree,
        }


@pytest.fixture
def refresh_vector_store_mocks():
    """Fixture providing bundled mocks for refresh_vector_store tests."""
    with (
        patch("server.api.v1.embed.utils_oci.get") as mock_oci_get,
        patch("server.api.v1.embed.utils_databases.get_client_database") as mock_get_db,
        patch("server.api.v1.embed.utils_embed.get_vector_store_by_alias") as mock_get_vs,
        patch("server.api.v1.embed.utils_oci.get_bucket_objects_with_metadata") as mock_get_objects,
        patch("server.api.v1.embed.utils_embed.get_processed_objects_metadata") as mock_get_processed,
        patch("server.api.v1.embed.utils_oci.detect_changed_objects") as mock_detect_changed,
        patch("server.api.v1.embed.utils_embed.get_total_chunks_count") as mock_get_chunks,
        patch("server.api.v1.embed.utils_models.get_client_embed") as mock_get_embed,
        patch("server.api.v1.embed.utils_embed.refresh_vector_store_from_bucket") as mock_refresh,
    ):
        yield {
            "oci_get": mock_oci_get,
            "get_db": mock_get_db,
            "get_vs": mock_get_vs,
            "get_objects": mock_get_objects,
            "get_processed": mock_get_processed,
            "detect_changed": mock_detect_changed,
            "get_chunks": mock_get_chunks,
            "get_embed": mock_get_embed,
            "refresh": mock_refresh,
        }


class TestExtractProviderErrorMessage:
    """Tests for the _extract_provider_error_message helper function."""

    def test_exception_with_message(self):
        """Test extraction of exception with message"""
        error = Exception("Something went wrong")
        result = embed._extract_provider_error_message(error)
        assert result == "Something went wrong"

    def test_exception_without_message(self):
        """Test extraction of exception without message"""
        error = ValueError()
        result = embed._extract_provider_error_message(error)
        assert result == "Error: ValueError"

    def test_openai_quota_exceeded(self):
        """Test extraction of OpenAI quota exceeded error message"""
        error_msg = (
            "Error code: 429 - {'error': {'message': 'You exceeded your current quota, "
            "please check your plan and billing details.', 'type': 'insufficient_quota'}}"
        )
        error = Exception(error_msg)
        result = embed._extract_provider_error_message(error)
        assert result == error_msg

    def test_openai_rate_limit(self):
        """Test extraction of OpenAI rate limit error message"""
        error_msg = "Rate limit exceeded. Please try again later."
        error = Exception(error_msg)
        result = embed._extract_provider_error_message(error)
        assert result == error_msg

    def test_complex_error_message(self):
        """Test extraction of complex multi-line error message"""
        error_msg = "Connection failed\nTimeout: 30s\nHost: api.example.com"
        error = Exception(error_msg)
        result = embed._extract_provider_error_message(error)
        assert result == error_msg

    @pytest.mark.parametrize(
        "error_message",
        [
            "OpenAI API key is invalid",
            "Cohere API error occurred",
            "OCI service error",
            "Database connection failed",
            "Rate limit exceeded for model xyz",
        ],
    )
    def test_various_error_messages(self, error_message):
        """Test that various error messages are passed through correctly"""
        error = Exception(error_message)
        result = embed._extract_provider_error_message(error)
        assert result == error_message


class TestEmbedDropVs:
    """Tests for the embed_drop_vs endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_databases.get_client_database")
    @patch("server.api.v1.embed.utils_databases.connect")
    @patch("server.api.v1.embed.utils_databases.drop_vs")
    async def test_embed_drop_vs_success(self, mock_drop, mock_connect, mock_get_db, make_database):
        """embed_drop_vs should drop vector store and return success."""
        mock_db = make_database()
        mock_get_db.return_value = mock_db
        mock_connect.return_value = MagicMock()
        mock_drop.return_value = None

        result = await embed.embed_drop_vs(vs="VS_TEST", client="test_client")

        assert result.status_code == 200
        mock_drop.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_databases.get_client_database")
    @patch("server.api.v1.embed.utils_databases.connect")
    @patch("server.api.v1.embed.utils_databases.drop_vs")
    async def test_embed_drop_vs_raises_400_on_db_exception(self, mock_drop, mock_connect, mock_get_db, make_database):
        """embed_drop_vs should raise 400 on DbException."""
        mock_db = make_database()
        mock_get_db.return_value = mock_db
        mock_connect.return_value = MagicMock()
        mock_drop.side_effect = DbException(status_code=400, detail="Table not found")

        with pytest.raises(HTTPException) as exc_info:
            await embed.embed_drop_vs(vs="VS_NONEXISTENT", client="test_client")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_databases.get_client_database")
    @patch("server.api.v1.embed.utils_databases.connect")
    @patch("server.api.v1.embed.utils_databases.drop_vs")
    async def test_embed_drop_vs_response_contains_vs_name(self, mock_drop, mock_connect, mock_get_db, make_database):
        """embed_drop_vs response should contain vector store name."""
        mock_db = make_database()
        mock_get_db.return_value = mock_db
        mock_connect.return_value = MagicMock()
        mock_drop.return_value = None

        result = await embed.embed_drop_vs(vs="VS_MY_STORE", client="test_client")

        body = json.loads(result.body)
        assert "VS_MY_STORE" in body["message"]


class TestEmbedGetFiles:
    """Tests for the embed_get_files endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_databases.get_client_database")
    @patch("server.api.v1.embed.utils_embed.get_vector_store_files")
    async def test_embed_get_files_success(self, mock_get_files, mock_get_db, make_database):
        """embed_get_files should return file list."""
        mock_db = make_database()
        mock_get_db.return_value = mock_db
        mock_get_files.return_value = [
            {"filename": "file1.pdf", "chunks": 10},
            {"filename": "file2.txt", "chunks": 5},
        ]

        result = await embed.embed_get_files(vs="VS_TEST", client="test_client")

        assert result.status_code == 200
        mock_get_files.assert_called_once_with(mock_db, "VS_TEST")

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_databases.get_client_database")
    @patch("server.api.v1.embed.utils_embed.get_vector_store_files")
    async def test_embed_get_files_raises_400_on_exception(self, mock_get_files, mock_get_db, make_database):
        """embed_get_files should raise 400 on exception."""
        mock_db = make_database()
        mock_get_db.return_value = mock_db
        mock_get_files.side_effect = Exception("Query failed")

        with pytest.raises(HTTPException) as exc_info:
            await embed.embed_get_files(vs="VS_TEST", client="test_client")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_databases.get_client_database")
    @patch("server.api.v1.embed.utils_embed.get_vector_store_files")
    async def test_embed_get_files_empty_list(self, mock_get_files, mock_get_db, make_database):
        """embed_get_files should return empty list for empty vector store."""
        mock_db = make_database()
        mock_get_db.return_value = mock_db
        mock_get_files.return_value = []

        result = await embed.embed_get_files(vs="VS_EMPTY", client="test_client")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body == []


class TestCommentVs:
    """Tests for the comment_vs endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_databases.get_client_database")
    @patch("server.api.v1.embed.utils_embed.update_vs_comment")
    async def test_comment_vs_success(self, mock_update_comment, mock_get_db, make_database, make_vector_store):
        """comment_vs should update vector store comment and return success."""
        mock_db = make_database()
        mock_get_db.return_value = mock_db
        mock_update_comment.return_value = None

        request = make_vector_store(vector_store="VS_TEST")

        result = await embed.comment_vs(request=request, client="test_client")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "comment updated" in body["message"]
        mock_update_comment.assert_called_once_with(vector_store=request, db_details=mock_db)

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_databases.get_client_database")
    @patch("server.api.v1.embed.utils_embed.update_vs_comment")
    async def test_comment_vs_calls_get_client_database(
        self, mock_update_comment, mock_get_db, make_database, make_vector_store
    ):
        """comment_vs should call get_client_database with correct client."""
        mock_db = make_database()
        mock_get_db.return_value = mock_db
        mock_update_comment.return_value = None

        request = make_vector_store()

        await embed.comment_vs(request=request, client="my_client")

        mock_get_db.assert_called_once_with("my_client")


class TestStoreSqlFile:
    """Tests for the store_sql_file endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    @patch("server.api.v1.embed.functions.run_sql_query")
    async def test_store_sql_file_success(self, mock_run_sql, mock_get_temp, tmp_path):
        """store_sql_file should execute SQL and return file path."""
        mock_get_temp.return_value = tmp_path
        mock_run_sql.return_value = "result.csv"

        result = await embed.store_sql_file(request=["conn_str", "SELECT * FROM table"], client="test_client")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "result.csv" in body

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    @patch("server.api.v1.embed.functions.run_sql_query")
    async def test_store_sql_file_calls_run_sql_query(self, mock_run_sql, mock_get_temp, tmp_path):
        """store_sql_file should call run_sql_query with correct params."""
        mock_get_temp.return_value = tmp_path
        mock_run_sql.return_value = "output.csv"

        await embed.store_sql_file(request=["db_conn", "SELECT 1"], client="test_client")

        mock_run_sql.assert_called_once_with(db_conn="db_conn", query="SELECT 1", base_path=tmp_path)


class TestStoreWebFile:
    """Tests for the store_web_file endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    @patch("server.api.v1.embed.web_parse.fetch_and_extract_sections")
    @patch("server.api.v1.embed.web_parse.slugify")
    @patch("aiohttp.ClientSession")
    async def test_store_web_file_html_success(
        self, mock_session_class, mock_slugify, mock_fetch_sections, mock_get_temp, tmp_path
    ):
        """store_web_file should fetch HTML and extract sections."""
        mock_get_temp.return_value = tmp_path
        mock_slugify.return_value = "test-page"
        mock_fetch_sections.return_value = [{"title": "Section 1", "content": "Content 1"}]

        mock_response = AsyncMock()
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.read = AsyncMock(return_value=b"<html></html>")
        create_mock_aiohttp_session(mock_session_class, mock_response)

        result = await embed.store_web_file(request=[HttpUrl("https://example.com/page")], client="test_client")

        assert result.status_code == 200

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    @patch("aiohttp.ClientSession")
    async def test_store_web_file_pdf_success(self, mock_session_class, mock_get_temp, tmp_path):
        """store_web_file should download PDF files."""
        mock_get_temp.return_value = tmp_path

        mock_response = AsyncMock()
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.read = AsyncMock(return_value=b"%PDF-1.4")
        create_mock_aiohttp_session(mock_session_class, mock_response)

        result = await embed.store_web_file(request=[HttpUrl("https://example.com/doc.pdf")], client="test_client")

        assert result.status_code == 200


class TestStoreLocalFile:
    """Tests for the store_local_file endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    async def test_store_local_file_success(self, mock_get_temp, tmp_path):
        """store_local_file should save uploaded files."""
        mock_get_temp.return_value = tmp_path

        mock_file = UploadFile(file=BytesIO(b"Test content"), filename="test.txt")

        result = await embed.store_local_file(files=[mock_file], client="test_client")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "test.txt" in body

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    async def test_store_local_file_creates_metadata(self, mock_get_temp, tmp_path):
        """store_local_file should create metadata file."""
        mock_get_temp.return_value = tmp_path

        mock_file = UploadFile(file=BytesIO(b"Test content"), filename="test.txt")

        await embed.store_local_file(files=[mock_file], client="test_client")

        metadata_file = tmp_path / ".file_metadata.json"
        assert metadata_file.exists()

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    async def test_store_local_file_multiple_files(self, mock_get_temp, tmp_path):
        """store_local_file should handle multiple files."""
        mock_get_temp.return_value = tmp_path

        files = [
            UploadFile(file=BytesIO(b"Content 1"), filename="file1.txt"),
            UploadFile(file=BytesIO(b"Content 2"), filename="file2.txt"),
        ]

        result = await embed.store_local_file(files=files, client="test_client")

        body = json.loads(result.body)
        assert len(body) == 2

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    async def test_store_local_file_metadata_excludes_metadata_file(self, mock_get_temp, tmp_path):
        """store_local_file should not include metadata file in response."""
        mock_get_temp.return_value = tmp_path

        mock_file = UploadFile(file=BytesIO(b"Content"), filename="test.txt")

        result = await embed.store_local_file(files=[mock_file], client="test_client")

        body = json.loads(result.body)
        assert ".file_metadata.json" not in body


class TestSplitEmbed:
    """Tests for the split_embed endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_oci.get")
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    async def test_split_embed_raises_404_when_no_files(self, mock_get_temp, mock_oci_get, tmp_path, make_oci_config):
        """split_embed should raise 404 when no files found."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_temp.return_value = tmp_path  # Empty directory

        request = DatabaseVectorStorage(model="text-embedding-3", chunk_size=1000, chunk_overlap=200)

        with pytest.raises(HTTPException) as exc_info:
            await embed.split_embed(request=request, rate_limit=0, client="test_client")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_oci.get")
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    async def test_split_embed_raises_404_when_folder_not_found(self, mock_get_temp, mock_oci_get, make_oci_config):
        """split_embed should raise 404 when folder not found."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_temp.return_value = Path("/nonexistent/path")

        request = DatabaseVectorStorage(model="text-embedding-3", chunk_size=1000, chunk_overlap=200)

        with pytest.raises(HTTPException) as exc_info:
            await embed.split_embed(request=request, rate_limit=0, client="test_client")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_split_embed_success(self, split_embed_mocks, tmp_path, make_oci_config, make_database):
        """split_embed should process files and populate vector store."""
        mocks = split_embed_mocks
        mocks["oci_get"].return_value = make_oci_config()
        mocks["get_temp"].return_value = tmp_path
        mocks["load_split"].return_value = (["doc1", "doc2"], None)
        mocks["get_embed"].return_value = MagicMock()
        mocks["get_vs_table"].return_value = ("VS_TEST", "test_alias")
        mocks["populate"].return_value = None
        mocks["get_db"].return_value = make_database()

        # Create a test file
        (tmp_path / "test.txt").write_text("Test content")

        request = DatabaseVectorStorage(model="text-embedding-3", chunk_size=1000, chunk_overlap=200)

        result = await embed.split_embed(request=request, rate_limit=0, client="test_client")

        assert result.status_code == 200
        mocks["populate"].assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_oci.get")
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    @patch("server.api.v1.embed.utils_embed.load_and_split_documents")
    @patch("shutil.rmtree")
    async def test_split_embed_raises_500_on_value_error(
        self, _mock_rmtree, mock_load_split, mock_get_temp, mock_oci_get, tmp_path, make_oci_config
    ):
        """split_embed should raise 500 on ValueError during processing."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_temp.return_value = tmp_path
        mock_load_split.side_effect = ValueError("Invalid document format")

        # Create a test file
        (tmp_path / "test.txt").write_text("Test content")

        request = DatabaseVectorStorage(model="text-embedding-3", chunk_size=1000, chunk_overlap=200)

        with pytest.raises(HTTPException) as exc_info:
            await embed.split_embed(request=request, rate_limit=0, client="test_client")

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_oci.get")
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    @patch("server.api.v1.embed.utils_embed.load_and_split_documents")
    @patch("shutil.rmtree")
    async def test_split_embed_raises_500_on_runtime_error(
        self, _mock_rmtree, mock_load_split, mock_get_temp, mock_oci_get, tmp_path, make_oci_config
    ):
        """split_embed should raise 500 on RuntimeError during processing."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_temp.return_value = tmp_path
        mock_load_split.side_effect = RuntimeError("Processing failed")

        # Create a test file
        (tmp_path / "test.txt").write_text("Test content")

        request = DatabaseVectorStorage(model="text-embedding-3", chunk_size=1000, chunk_overlap=200)

        with pytest.raises(HTTPException) as exc_info:
            await embed.split_embed(request=request, rate_limit=0, client="test_client")

        assert exc_info.value.status_code == 500
        assert "Processing failed" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_oci.get")
    @patch("server.api.v1.embed.utils_embed.get_temp_directory")
    @patch("server.api.v1.embed.utils_embed.load_and_split_documents")
    @patch("shutil.rmtree")
    async def test_split_embed_raises_500_on_generic_exception(
        self, _mock_rmtree, mock_load_split, mock_get_temp, mock_oci_get, tmp_path, make_oci_config
    ):
        """split_embed should raise 500 on generic Exception during processing."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_temp.return_value = tmp_path
        mock_load_split.side_effect = Exception("Unexpected error occurred")

        # Create a test file
        (tmp_path / "test.txt").write_text("Test content")

        request = DatabaseVectorStorage(model="text-embedding-3", chunk_size=1000, chunk_overlap=200)

        with pytest.raises(HTTPException) as exc_info:
            await embed.split_embed(request=request, rate_limit=0, client="test_client")

        assert exc_info.value.status_code == 500
        assert "Unexpected error occurred" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_split_embed_loads_file_metadata(self, split_embed_mocks, tmp_path, make_oci_config, make_database):
        """split_embed should load file metadata when available."""
        mocks = split_embed_mocks
        mocks["oci_get"].return_value = make_oci_config()
        mocks["get_temp"].return_value = tmp_path
        mocks["load_split"].return_value = (["doc1"], None)
        mocks["get_embed"].return_value = MagicMock()
        mocks["get_vs_table"].return_value = ("VS_TEST", "test_alias")
        mocks["populate"].return_value = None
        mocks["get_db"].return_value = make_database()

        # Create a test file and metadata
        (tmp_path / "test.txt").write_text("Test content")
        metadata = {"test.txt": {"size": 12, "time_modified": "2024-01-01T00:00:00Z"}}
        (tmp_path / ".file_metadata.json").write_text(json.dumps(metadata))

        request = DatabaseVectorStorage(model="text-embedding-3", chunk_size=1000, chunk_overlap=200)

        result = await embed.split_embed(request=request, rate_limit=0, client="test_client")

        assert result.status_code == 200
        # Verify load_and_split_documents was called with file_metadata
        call_kwargs = mocks["load_split"].call_args.kwargs
        assert call_kwargs.get("file_metadata") == metadata

    @pytest.mark.asyncio
    async def test_split_embed_handles_corrupt_metadata(
        self, split_embed_mocks, tmp_path, make_oci_config, make_database
    ):
        """split_embed should handle corrupt metadata file gracefully."""
        mocks = split_embed_mocks
        mocks["oci_get"].return_value = make_oci_config()
        mocks["get_temp"].return_value = tmp_path
        mocks["load_split"].return_value = (["doc1"], None)
        mocks["get_embed"].return_value = MagicMock()
        mocks["get_vs_table"].return_value = ("VS_TEST", "test_alias")
        mocks["populate"].return_value = None
        mocks["get_db"].return_value = make_database()

        # Create a test file and corrupt metadata
        (tmp_path / "test.txt").write_text("Test content")
        (tmp_path / ".file_metadata.json").write_text("{ invalid json }")

        request = DatabaseVectorStorage(model="text-embedding-3", chunk_size=1000, chunk_overlap=200)

        result = await embed.split_embed(request=request, rate_limit=0, client="test_client")

        # Should still succeed, falling back to None for metadata
        assert result.status_code == 200
        call_kwargs = mocks["load_split"].call_args.kwargs
        assert call_kwargs.get("file_metadata") is None


class TestRefreshVectorStore:
    """Tests for the refresh_vector_store endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_oci.get")
    @patch("server.api.v1.embed.utils_databases.get_client_database")
    @patch("server.api.v1.embed.utils_embed.get_vector_store_by_alias")
    @patch("server.api.v1.embed.utils_oci.get_bucket_objects_with_metadata")
    async def test_refresh_vector_store_no_files(
        self,
        mock_get_objects,
        mock_get_vs,
        mock_get_db,
        mock_oci_get,
        make_oci_config,
        make_database,
        make_vector_store,
    ):
        """refresh_vector_store should return success when no files."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_db.return_value = make_database()
        mock_get_vs.return_value = make_vector_store()
        mock_get_objects.return_value = []

        request = VectorStoreRefreshRequest(vector_store_alias="test_alias", bucket_name="test-bucket")

        result = await embed.refresh_vector_store(request=request, client="test_client")

        assert result.status_code == 200

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_oci.get")
    async def test_refresh_vector_store_raises_400_on_value_error(self, mock_oci_get):
        """refresh_vector_store should raise 400 on ValueError."""
        mock_oci_get.side_effect = ValueError("Invalid config")

        request = VectorStoreRefreshRequest(vector_store_alias="test_alias", bucket_name="test-bucket")

        with pytest.raises(HTTPException) as exc_info:
            await embed.refresh_vector_store(request=request, client="test_client")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("server.api.v1.embed.utils_oci.get")
    @patch("server.api.v1.embed.utils_databases.get_client_database")
    @patch("server.api.v1.embed.utils_embed.get_vector_store_by_alias")
    async def test_refresh_vector_store_raises_500_on_db_exception(
        self, mock_get_vs, mock_get_db, mock_oci_get, make_oci_config, make_database
    ):
        """refresh_vector_store should raise 500 on DbException."""
        mock_oci_get.return_value = make_oci_config()
        mock_get_db.return_value = make_database()
        mock_get_vs.side_effect = DbException(status_code=500, detail="Database error")

        request = VectorStoreRefreshRequest(vector_store_alias="test_alias", bucket_name="test-bucket")

        with pytest.raises(HTTPException) as exc_info:
            await embed.refresh_vector_store(request=request, client="test_client")

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_refresh_vector_store_no_changes(
        self,
        refresh_vector_store_mocks,
        make_oci_config,
        make_database,
        make_vector_store,
    ):
        """refresh_vector_store should return success when no changes detected."""
        mocks = refresh_vector_store_mocks
        mocks["oci_get"].return_value = make_oci_config()
        mocks["get_db"].return_value = make_database()
        mocks["get_vs"].return_value = make_vector_store()
        mocks["get_objects"].return_value = [{"name": "file.pdf", "etag": "abc123"}]
        mocks["get_processed"].return_value = {"file.pdf": {"etag": "abc123"}}
        mocks["detect_changed"].return_value = ([], [])  # No new, no modified
        mocks["get_chunks"].return_value = 100

        request = VectorStoreRefreshRequest(vector_store_alias="test_alias", bucket_name="test-bucket")

        result = await embed.refresh_vector_store(request=request, client="test_client")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["message"] == "No new or modified files to process"
        assert body["total_chunks_in_store"] == 100

    @pytest.mark.asyncio
    async def test_refresh_vector_store_with_changes(
        self,
        refresh_vector_store_mocks,
        make_oci_config,
        make_database,
        make_vector_store,
    ):
        """refresh_vector_store should process changed files."""
        mocks = refresh_vector_store_mocks
        mocks["oci_get"].return_value = make_oci_config()
        mocks["get_db"].return_value = make_database()
        mocks["get_vs"].return_value = make_vector_store(model="text-embedding-3-small")
        mocks["get_objects"].return_value = [
            {"name": "new_file.pdf", "etag": "new123"},
            {"name": "modified.pdf", "etag": "mod456"},
        ]
        mocks["get_processed"].return_value = {"modified.pdf": {"etag": "old_etag"}}
        mocks["detect_changed"].return_value = (
            [{"name": "new_file.pdf", "etag": "new123"}],  # new
            [{"name": "modified.pdf", "etag": "mod456"}],  # modified
        )
        mocks["get_embed"].return_value = MagicMock()
        mocks["refresh"].return_value = {"message": "Processed 2 files", "processed_files": 2, "total_chunks": 50}
        mocks["get_chunks"].return_value = 150

        request = VectorStoreRefreshRequest(vector_store_alias="test_alias", bucket_name="test-bucket")

        result = await embed.refresh_vector_store(request=request, client="test_client")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "completed"
        assert body["new_files"] == 1
        assert body["updated_files"] == 1
        assert body["total_chunks_in_store"] == 150
        mocks["refresh"].assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_vector_store_raises_500_on_generic_exception(
        self,
        refresh_vector_store_mocks,
        make_oci_config,
        make_database,
        make_vector_store,
    ):
        """refresh_vector_store should raise 500 on generic Exception."""
        mocks = refresh_vector_store_mocks
        mocks["oci_get"].return_value = make_oci_config()
        mocks["get_db"].return_value = make_database()
        mocks["get_vs"].return_value = make_vector_store()
        mocks["get_objects"].return_value = [{"name": "file.pdf", "etag": "abc123"}]
        mocks["get_processed"].return_value = {}
        mocks["detect_changed"].return_value = ([{"name": "file.pdf"}], [])
        mocks["get_embed"].side_effect = RuntimeError("Embedding service unavailable")

        request = VectorStoreRefreshRequest(vector_store_alias="test_alias", bucket_name="test-bucket")

        with pytest.raises(HTTPException) as exc_info:
            await embed.refresh_vector_store(request=request, client="test_client")

        assert exc_info.value.status_code == 500
        assert "Embedding service unavailable" in exc_info.value.detail


class TestRouterConfiguration:
    """Tests for router configuration."""

    def test_auth_router_exists(self):
        """The auth router should be defined."""
        assert hasattr(embed, "auth")

    def test_auth_router_has_routes(self):
        """The auth router should have registered routes."""
        routes = [route.path for route in embed.auth.routes]

        assert "/{vs}" in routes
        assert "/{vs}/files" in routes
        assert "/comment" in routes
        assert "/sql/store" in routes
        assert "/web/store" in routes
        assert "/local/store" in routes
        assert "/" in routes
        assert "/refresh" in routes


class TestLoggerConfiguration:
    """Tests for logger configuration."""

    def test_logger_exists(self):
        """Logger should be configured."""
        assert hasattr(embed, "logger")

    def test_logger_name(self):
        """Logger should have correct name."""
        assert embed.logger.name == "api.v1.embed"
