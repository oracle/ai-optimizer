"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/embed.py
Tests for document embedding and vector store utility functions.

Uses hybrid approach:
- Real Oracle database for vector store query tests
- Mocks for file processing logic (document loaders, splitting, etc.)
"""

# pylint: disable=too-few-public-methods

import json
import os
from unittest.mock import patch, MagicMock
import pytest

from langchain_core.documents import Document as LangchainDocument

from server.api.utils import embed as utils_embed


class TestUpdateVsComment:
    """Tests for the update_vs_comment function."""

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.functions.get_vs_table")
    @patch("server.api.utils.embed.utils_databases.execute_sql")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_update_vs_comment_success(
        self, mock_disconnect, mock_execute_sql, mock_get_vs_table, mock_connect, make_database, make_vector_store
    ):
        """update_vs_comment should execute comment SQL."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_get_vs_table.return_value = ("VS_TEST", '{"alias": "test"}')

        db_details = make_database()
        vector_store = make_vector_store(vector_store="VS_TEST")

        utils_embed.update_vs_comment(vector_store=vector_store, db_details=db_details)

        mock_connect.assert_called_once_with(db_details)
        mock_execute_sql.assert_called_once()
        mock_disconnect.assert_called_once_with(mock_conn)

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.functions.get_vs_table")
    @patch("server.api.utils.embed.utils_databases.execute_sql")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_update_vs_comment_builds_correct_sql(
        self, _mock_disconnect, mock_execute_sql, mock_get_vs_table, mock_connect, make_database, make_vector_store
    ):
        """update_vs_comment should build correct COMMENT ON TABLE SQL."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_get_vs_table.return_value = ("VS_MY_STORE", '{"alias": "my_alias", "model": "embed-3"}')

        db_details = make_database()
        vector_store = make_vector_store(vector_store="VS_MY_STORE")

        utils_embed.update_vs_comment(vector_store=vector_store, db_details=db_details)

        call_args = mock_execute_sql.call_args[0]
        sql = call_args[1]
        assert "COMMENT ON TABLE VS_MY_STORE IS" in sql
        assert "GENAI:" in sql

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.functions.get_vs_table")
    @patch("server.api.utils.embed.utils_databases.execute_sql")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_update_vs_comment_disconnects_on_success(
        self, mock_disconnect, _mock_execute_sql, mock_get_vs_table, mock_connect, make_database, make_vector_store
    ):
        """update_vs_comment should disconnect from database after execution."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_get_vs_table.return_value = ("VS_TEST", "{}")

        db_details = make_database()
        vector_store = make_vector_store()

        utils_embed.update_vs_comment(vector_store=vector_store, db_details=db_details)

        mock_disconnect.assert_called_once_with(mock_conn)

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.functions.get_vs_table")
    @patch("server.api.utils.embed.utils_databases.execute_sql")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_update_vs_comment_calls_get_vs_table_with_correct_params(
        self, _mock_disconnect, _mock_execute_sql, mock_get_vs_table, mock_connect, make_database, make_vector_store
    ):
        """update_vs_comment should call get_vs_table excluding database and vector_store."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_get_vs_table.return_value = ("VS_TEST", "{}")

        db_details = make_database()
        vector_store = make_vector_store(
            vector_store="VS_TEST",
            model="embed-model",
            chunk_size=500,
            chunk_overlap=100,
        )

        utils_embed.update_vs_comment(vector_store=vector_store, db_details=db_details)

        mock_get_vs_table.assert_called_once()
        call_kwargs = mock_get_vs_table.call_args.kwargs
        # Should NOT include database or vector_store
        assert "database" not in call_kwargs
        assert "vector_store" not in call_kwargs
        # Should include other fields
        assert "model" in call_kwargs or "chunk_size" in call_kwargs


class TestGetTempDirectory:
    """Tests for the get_temp_directory function."""

    @patch("server.api.utils.embed.Path")
    def test_get_temp_directory_uses_app_tmp(self, mock_path):
        """Should use /app/tmp if it exists."""
        mock_app_path = MagicMock()
        mock_app_path.exists.return_value = True
        mock_app_path.is_dir.return_value = True
        mock_path.return_value = mock_app_path
        mock_path.side_effect = lambda x: mock_app_path if x == "/app/tmp" else MagicMock()

        result = utils_embed.get_temp_directory("test_client", "embed")

        assert result is not None

    @patch("server.api.utils.embed.Path")
    def test_get_temp_directory_uses_tmp_fallback(self, mock_path):
        """Should use /tmp if /app/tmp doesn't exist."""
        mock_app_path = MagicMock()
        mock_app_path.exists.return_value = False
        mock_path.return_value = mock_app_path

        result = utils_embed.get_temp_directory("test_client", "embed")

        assert result is not None


class TestDocToJson:
    """Tests for the doc_to_json function."""

    def test_doc_to_json_creates_file(self, tmp_path):
        """Should create JSON file from documents."""
        docs = [LangchainDocument(page_content="Test content", metadata={"source": "test.pdf"})]

        result = utils_embed.doc_to_json(docs, "test.pdf", str(tmp_path))

        assert os.path.exists(result)
        assert result.endswith(".json")


class TestProcessMetadata:
    """Tests for the process_metadata function."""

    def test_process_metadata_adds_metadata(self):
        """Should add metadata to chunk."""
        chunk = LangchainDocument(page_content="Test content", metadata={"source": "/path/to/test.pdf", "page": 1})

        result = utils_embed.process_metadata(1, chunk)

        assert len(result) == 1
        assert result[0].metadata["id"] == "test_1"
        assert result[0].metadata["filename"] == "test.pdf"

    def test_process_metadata_includes_file_metadata(self):
        """Should include file metadata if provided."""
        chunk = LangchainDocument(page_content="Test content", metadata={"source": "/path/to/doc.pdf"})
        file_metadata = {"doc.pdf": {"size": 1000, "time_modified": "2024-01-01", "etag": "abc123"}}

        result = utils_embed.process_metadata(1, chunk, file_metadata)

        assert result[0].metadata["size"] == 1000
        assert result[0].metadata["etag"] == "abc123"


class TestSplitDocument:
    """Tests for the split_document function."""

    def test_split_document_pdf(self):
        """Should split PDF documents."""
        docs = [LangchainDocument(page_content="A" * 2000, metadata={"source": "test.pdf"})]

        result = utils_embed.split_document("default", 500, 50, docs, "pdf")

        assert len(result) > 0

    def test_split_document_unsupported_extension(self):
        """Should raise ValueError for unsupported extension."""
        docs = [LangchainDocument(page_content="Test", metadata={})]

        with pytest.raises(ValueError) as exc_info:
            utils_embed.split_document("default", 500, 50, docs, "xyz")

        assert "Unsupported file type" in str(exc_info.value)


class TestGetDocumentLoader:  # pylint: disable=protected-access
    """Tests for the _get_document_loader function."""

    def test_get_document_loader_pdf(self, tmp_path):
        """Should return PyPDFLoader for PDF files."""
        test_file = tmp_path / "test.pdf"
        test_file.touch()

        _, split = utils_embed._get_document_loader(str(test_file), "pdf")

        assert split is True

    def test_get_document_loader_html(self, tmp_path):
        """Should return TextLoader for HTML files."""
        test_file = tmp_path / "test.html"
        test_file.touch()

        _, split = utils_embed._get_document_loader(str(test_file), "html")

        assert split is True

    def test_get_document_loader_unsupported(self, tmp_path):
        """Should raise ValueError for unsupported extension."""
        test_file = tmp_path / "test.xyz"
        test_file.touch()

        with pytest.raises(ValueError):
            utils_embed._get_document_loader(str(test_file), "xyz")


class TestCaptureFileMetadata:  # pylint: disable=protected-access
    """Tests for the _capture_file_metadata function."""

    def test_capture_file_metadata_new_file(self, tmp_path):
        """Should capture metadata for new files."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        stat = test_file.stat()
        file_metadata = {}

        utils_embed._capture_file_metadata("test.txt", stat, file_metadata)

        assert "test.txt" in file_metadata
        assert "size" in file_metadata["test.txt"]
        assert "time_modified" in file_metadata["test.txt"]

    def test_capture_file_metadata_existing_file(self, tmp_path):
        """Should not overwrite existing metadata."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        stat = test_file.stat()
        file_metadata = {"test.txt": {"size": 9999}}

        utils_embed._capture_file_metadata("test.txt", stat, file_metadata)

        assert file_metadata["test.txt"]["size"] == 9999  # Not overwritten


class TestPrepareDocuments:  # pylint: disable=protected-access
    """Tests for the _prepare_documents function."""

    def test_prepare_documents_removes_duplicates(self):
        """Should remove duplicate documents."""
        docs = [
            LangchainDocument(page_content="Same content", metadata={}),
            LangchainDocument(page_content="Same content", metadata={}),
            LangchainDocument(page_content="Different content", metadata={}),
        ]

        result = utils_embed._prepare_documents(docs)

        assert len(result) == 2


class TestGetVectorStoreByAlias:
    """Tests for the get_vector_store_by_alias function."""

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_get_vector_store_by_alias_success(self, _mock_disconnect, mock_connect, make_database):
        """Should return vector store config for matching alias."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("VS_TEST", '{"alias": "test_alias", "model": "embed-3", "chunk_size": 500, "chunk_overlap": 100}')
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = utils_embed.get_vector_store_by_alias(make_database(), "test_alias")

        assert result.vector_store == "VS_TEST"
        assert result.alias == "test_alias"

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_get_vector_store_by_alias_not_found(self, _mock_disconnect, mock_connect, make_database):
        """Should raise ValueError if alias not found."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        with pytest.raises(ValueError) as exc_info:
            utils_embed.get_vector_store_by_alias(make_database(), "nonexistent")

        assert "not found" in str(exc_info.value)


class TestGetTotalChunksCount:
    """Tests for the get_total_chunks_count function."""

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_get_total_chunks_count_success(self, _mock_disconnect, mock_connect, make_database):
        """Should return chunk count."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (150,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = utils_embed.get_total_chunks_count(make_database(), "VS_TEST")

        assert result == 150

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_get_total_chunks_count_error(self, _mock_disconnect, mock_connect, make_database):
        """Should return 0 on error."""
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("Query failed")
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = utils_embed.get_total_chunks_count(make_database(), "VS_TEST")

        assert result == 0


class TestGetProcessedObjectsMetadata:
    """Tests for the get_processed_objects_metadata function."""

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_get_processed_objects_metadata_new_format(self, _mock_disconnect, mock_connect, make_database):
        """Should return metadata in new format."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [({"filename": "doc.pdf", "etag": "abc", "time_modified": "2024-01-01"},)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = utils_embed.get_processed_objects_metadata(make_database(), "VS_TEST")

        assert "doc.pdf" in result
        assert result["doc.pdf"]["etag"] == "abc"

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_get_processed_objects_metadata_old_format(self, _mock_disconnect, mock_connect, make_database):
        """Should handle old format with source field."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [({"source": "/path/to/doc.pdf"},)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = utils_embed.get_processed_objects_metadata(make_database(), "VS_TEST")

        assert "doc.pdf" in result


class TestGetVectorStoreFiles:
    """Tests for the get_vector_store_files function."""

    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed.utils_databases.disconnect")
    def test_get_vector_store_files_success(self, _mock_disconnect, mock_connect, make_database):
        """Should return file list with statistics."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ({"filename": "doc1.pdf", "size": 1000},),
            ({"filename": "doc1.pdf", "size": 1000},),
            ({"filename": "doc2.pdf", "size": 2000},),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = utils_embed.get_vector_store_files(make_database(), "VS_TEST")

        assert result["total_files"] == 2
        assert result["total_chunks"] == 3


class TestRefreshVectorStoreFromBucket:
    """Tests for the refresh_vector_store_from_bucket function."""

    @patch("server.api.utils.embed.get_temp_directory")
    def test_refresh_vector_store_empty_objects(
        self, _mock_get_temp, make_vector_store, make_database, make_oci_config
    ):
        """Should return early if no objects to process."""
        result = utils_embed.refresh_vector_store_from_bucket(
            make_vector_store(),
            "test-bucket",
            [],
            make_database(),
            MagicMock(),
            make_oci_config(),
        )

        assert result["processed_files"] == 0
        assert "No new or modified files" in result["message"]

    @patch("server.api.utils.embed.shutil.rmtree")
    @patch("server.api.utils.embed.populate_vs")
    @patch("server.api.utils.embed.load_and_split_documents")
    @patch("server.api.utils.embed.utils_oci.get_object")
    @patch("server.api.utils.embed.get_temp_directory")
    def test_refresh_vector_store_success(
        self,
        mock_get_temp,
        mock_get_object,
        mock_load_split,
        mock_populate,
        _mock_rmtree,
        make_vector_store,
        make_database,
        make_oci_config,
        tmp_path,
    ):
        """Should process objects and populate vector store."""
        mock_get_temp.return_value = tmp_path
        mock_get_object.return_value = str(tmp_path / "doc.pdf")
        mock_load_split.return_value = (
            [LangchainDocument(page_content="test", metadata={})],
            [],
            {"processed_files": [], "skipped_files": [], "total_chunks": 0},
        )

        bucket_objects = [{"name": "doc.pdf", "size": 1000, "time_modified": "2024-01-01", "etag": "abc"}]

        result = utils_embed.refresh_vector_store_from_bucket(
            make_vector_store(),
            "test-bucket",
            bucket_objects,
            make_database(),
            MagicMock(),
            make_oci_config(),
        )

        assert result["processed_files"] == 1
        mock_populate.assert_called_once()

    @patch("server.api.utils.embed.shutil.rmtree")
    @patch("server.api.utils.embed.utils_oci.get_object")
    @patch("server.api.utils.embed.get_temp_directory")
    def test_refresh_vector_store_download_failure(
        self, mock_get_temp, mock_get_object, _mock_rmtree, make_vector_store, make_database, make_oci_config, tmp_path
    ):
        """Should handle download failures gracefully."""
        mock_get_temp.return_value = tmp_path
        mock_get_object.side_effect = Exception("Download failed")

        bucket_objects = [{"name": "doc.pdf", "size": 1000}]

        result = utils_embed.refresh_vector_store_from_bucket(
            make_vector_store(),
            "test-bucket",
            bucket_objects,
            make_database(),
            MagicMock(),
            make_oci_config(),
        )

        assert result["processed_files"] == 0
        assert "errors" in result


class TestLoadAndSplitDocuments:
    """Tests for the load_and_split_documents function."""

    @patch("server.api.utils.embed._get_document_loader")
    @patch("server.api.utils.embed._process_and_split_document")
    def test_load_and_split_documents_success(self, mock_process, mock_get_loader, tmp_path):
        """Should load and split documents."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")

        mock_loader = MagicMock()
        mock_loader.load.return_value = [LangchainDocument(page_content="Test", metadata={})]
        mock_get_loader.return_value = (mock_loader, True)
        mock_process.return_value = [LangchainDocument(page_content="Test", metadata={"id": "1"})]

        result, _, _ = utils_embed.load_and_split_documents([str(test_file)], "default", 500, 50)

        assert len(result) == 1

    @patch("server.api.utils.embed._get_document_loader")
    @patch("server.api.utils.embed._process_and_split_document")
    @patch("server.api.utils.embed.doc_to_json")
    def test_load_and_split_documents_with_json_output(
        self, mock_doc_to_json, mock_process, mock_get_loader, tmp_path
    ):
        """Should write JSON when output_dir provided."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Test content")

        mock_loader = MagicMock()
        mock_loader.load.return_value = [LangchainDocument(page_content="Test", metadata={})]
        mock_get_loader.return_value = (mock_loader, True)
        mock_process.return_value = [LangchainDocument(page_content="Test", metadata={})]
        mock_doc_to_json.return_value = str(tmp_path / "_test.json")

        _, split_files, _ = utils_embed.load_and_split_documents(
            [str(test_file)], "default", 500, 50, write_json=True, output_dir=str(tmp_path)
        )

        mock_doc_to_json.assert_called_once()
        assert len(split_files) == 1


class TestLoadAndSplitUrl:
    """Tests for the load_and_split_url function."""

    @patch("server.api.utils.embed.WebBaseLoader")
    @patch("server.api.utils.embed.split_document")
    def test_load_and_split_url_success(self, mock_split, mock_loader_class):
        """Should load and split URL content."""
        mock_loader = MagicMock()
        mock_loader.load.return_value = [
            LangchainDocument(page_content="Web content", metadata={"source": "http://example.com"})
        ]
        mock_loader_class.return_value = mock_loader
        mock_split.return_value = [LangchainDocument(page_content="Chunk", metadata={"source": "http://example.com"})]

        result, _ = utils_embed.load_and_split_url("default", "http://example.com", 500, 50)

        assert len(result) == 1

    @patch("server.api.utils.embed.WebBaseLoader")
    @patch("server.api.utils.embed.split_document")
    def test_load_and_split_url_empty_content(self, mock_split, mock_loader_class):
        """Should raise ValueError for empty content."""
        mock_loader = MagicMock()
        mock_loader.load.return_value = [LangchainDocument(page_content="", metadata={})]
        mock_loader_class.return_value = mock_loader
        mock_split.return_value = []

        with pytest.raises(ValueError) as exc_info:
            utils_embed.load_and_split_url("default", "http://example.com", 500, 50)

        assert "no chunk-able data" in str(exc_info.value)


class TestJsonToDoc:  # pylint: disable=protected-access
    """Tests for the _json_to_doc function."""

    def test_json_to_doc_success(self, tmp_path):
        """Should convert JSON file to documents."""
        json_content = [
            {"kwargs": {"page_content": "Content 1", "metadata": {"source": "test.pdf"}}},
            {"kwargs": {"page_content": "Content 2", "metadata": {"source": "test.pdf"}}},
        ]
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(json_content))

        result = utils_embed._json_to_doc(str(json_file))

        assert len(result) == 2
        assert result[0].page_content == "Content 1"


class TestProcessAndSplitDocument:  # pylint: disable=protected-access
    """Tests for the _process_and_split_document function."""

    @patch("server.api.utils.embed.split_document")
    @patch("server.api.utils.embed.process_metadata")
    def test_process_and_split_document_with_split(self, mock_process_meta, mock_split):
        """Should split and process document."""
        mock_split.return_value = [LangchainDocument(page_content="Chunk", metadata={"source": "test.pdf"})]
        mock_process_meta.return_value = [LangchainDocument(page_content="Chunk", metadata={"id": "1"})]

        loaded_doc = [LangchainDocument(page_content="Full content", metadata={})]

        result = utils_embed._process_and_split_document(
            loaded_doc,
            split=True,
            model="default",
            chunk_size=500,
            chunk_overlap=50,
            extension="pdf",
            file_metadata={},
        )

        mock_split.assert_called_once()
        assert len(result) == 1

    def test_process_and_split_document_no_split(self):
        """Should return loaded doc without splitting."""
        loaded_doc = [LangchainDocument(page_content="Content", metadata={})]

        result = utils_embed._process_and_split_document(
            loaded_doc,
            split=False,
            model="default",
            chunk_size=500,
            chunk_overlap=50,
            extension="png",
            file_metadata={},
        )

        assert result == loaded_doc


class TestCreateTempVectorStore:  # pylint: disable=protected-access
    """Tests for the _create_temp_vector_store function."""

    @patch("server.api.utils.embed.utils_databases.drop_vs")
    @patch("server.api.utils.embed.OracleVS")
    def test_create_temp_vector_store_success(self, mock_oracle_vs, mock_drop_vs, make_vector_store):
        """Should create temporary vector store."""
        mock_vs = MagicMock()
        mock_oracle_vs.return_value = mock_vs
        mock_conn = MagicMock()
        mock_embed_client = MagicMock()
        vector_store = make_vector_store(vector_store="VS_TEST")

        _, vs_config_tmp = utils_embed._create_temp_vector_store(mock_conn, vector_store, mock_embed_client)

        assert vs_config_tmp.vector_store == "VS_TEST_TMP"
        mock_drop_vs.assert_called_once()


class TestEmbedDocumentsInBatches:  # pylint: disable=protected-access
    """Tests for the _embed_documents_in_batches function."""

    @patch("server.api.utils.embed.OracleVS.add_documents")
    def test_embed_documents_in_batches_no_rate_limit(self, mock_add_docs):
        """Should embed documents without rate limiting."""
        mock_vs = MagicMock()
        chunks = [LangchainDocument(page_content=f"Chunk {i}", metadata={}) for i in range(10)]

        utils_embed._embed_documents_in_batches(mock_vs, chunks, rate_limit=0)

        mock_add_docs.assert_called_once()

    @patch("server.api.utils.embed.time.sleep")
    @patch("server.api.utils.embed.OracleVS.add_documents")
    def test_embed_documents_in_batches_with_rate_limit(self, mock_add_docs, mock_sleep):
        """Should apply rate limiting between batches."""
        mock_vs = MagicMock()
        # Create 600 chunks to trigger multiple batches (batch_size=500)
        chunks = [LangchainDocument(page_content=f"Chunk {i}", metadata={}) for i in range(600)]

        utils_embed._embed_documents_in_batches(mock_vs, chunks, rate_limit=60)

        assert mock_add_docs.call_count == 2  # 500 + 100
        mock_sleep.assert_called()  # Rate limiting applied


class TestMergeAndIndexVectorStore:  # pylint: disable=protected-access
    """Tests for the _merge_and_index_vector_store function."""

    @patch("server.api.utils.embed.LangchainVS.create_index")
    @patch("server.api.utils.embed.utils_databases.drop_vs")
    @patch("server.api.utils.embed.utils_databases.execute_sql")
    @patch("server.api.utils.embed.LangchainVS.drop_index_if_exists")
    @patch("server.api.utils.embed.OracleVS")
    def test_merge_and_index_vector_store_hnsw(
        self, _mock_oracle_vs, mock_drop_idx, mock_execute, mock_drop_vs, mock_create_idx, make_vector_store
    ):
        """Should merge temp store and create HNSW index."""
        mock_conn = MagicMock()
        vector_store = make_vector_store(vector_store="VS_TEST", index_type="HNSW")
        vector_store_tmp = make_vector_store(vector_store="VS_TEST_TMP")

        utils_embed._merge_and_index_vector_store(mock_conn, vector_store, vector_store_tmp, MagicMock())

        mock_drop_idx.assert_called_once()  # HNSW drops existing index
        mock_execute.assert_called_once()  # Merge SQL
        mock_drop_vs.assert_called_once()  # Drop temp table
        mock_create_idx.assert_called_once()  # Create index


class TestPopulateVs:
    """Tests for the populate_vs function."""

    @patch("server.api.utils.embed.update_vs_comment")
    @patch("server.api.utils.embed._merge_and_index_vector_store")
    @patch("server.api.utils.embed._embed_documents_in_batches")
    @patch("server.api.utils.embed._create_temp_vector_store")
    @patch("server.api.utils.embed.utils_databases.connect")
    @patch("server.api.utils.embed._prepare_documents")
    def test_populate_vs_success(
        self,
        mock_prepare,
        mock_connect,
        mock_create_temp,
        mock_embed,
        mock_merge,
        mock_comment,
        make_vector_store,
        make_database,
    ):
        """Should populate vector store with documents."""
        mock_prepare.return_value = [LangchainDocument(page_content="Test", metadata={})]
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_create_temp.return_value = (MagicMock(), make_vector_store(vector_store="VS_TMP"))

        docs = [LangchainDocument(page_content="Test", metadata={})]

        utils_embed.populate_vs(make_vector_store(), make_database(), MagicMock(), input_data=docs)

        mock_prepare.assert_called_once()
        mock_create_temp.assert_called_once()
        mock_embed.assert_called_once()
        mock_merge.assert_called_once()
        mock_comment.assert_called_once()


class TestSplitDocumentExtensions:
    """Tests for split_document with various extensions."""

    def test_split_document_html(self):
        """Should split HTML documents using HTMLHeaderTextSplitter."""
        docs = [LangchainDocument(page_content="<h1>Title</h1><p>Content here</p>", metadata={"source": "test.html"})]

        result = utils_embed.split_document("default", 500, 50, docs, "html")

        assert len(result) >= 1

    def test_split_document_md(self):
        """Should split Markdown documents."""
        docs = [LangchainDocument(page_content="# Header\n\nContent " * 100, metadata={"source": "test.md"})]

        result = utils_embed.split_document("default", 500, 50, docs, "md")

        assert len(result) >= 1

    def test_split_document_txt(self):
        """Should split text documents."""
        docs = [LangchainDocument(page_content="Text content " * 200, metadata={"source": "test.txt"})]

        result = utils_embed.split_document("default", 500, 50, docs, "txt")

        assert len(result) >= 1

    def test_split_document_csv(self):
        """Should split CSV documents."""
        docs = [LangchainDocument(page_content="col1,col2\nval1,val2\n" * 100, metadata={"source": "test.csv"})]

        result = utils_embed.split_document("default", 500, 50, docs, "csv")

        assert len(result) >= 1


class TestGetDocumentLoaderExtensions:  # pylint: disable=protected-access
    """Tests for _get_document_loader with various extensions."""

    def test_get_document_loader_md(self, tmp_path):
        """Should return TextLoader for Markdown files."""
        test_file = tmp_path / "test.md"
        test_file.touch()

        _, split = utils_embed._get_document_loader(str(test_file), "md")

        assert split is True

    def test_get_document_loader_csv(self, tmp_path):
        """Should return CSVLoader for CSV files."""
        test_file = tmp_path / "test.csv"
        test_file.write_text("col1,col2\nval1,val2")

        _, split = utils_embed._get_document_loader(str(test_file), "csv")

        assert split is True

    def test_get_document_loader_txt(self, tmp_path):
        """Should return TextLoader for text files."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        _, split = utils_embed._get_document_loader(str(test_file), "txt")

        assert split is True
