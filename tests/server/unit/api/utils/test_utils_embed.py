"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error import-outside-toplevel

from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock

from langchain.docstore.document import Document as LangchainDocument

from server.api.utils import embed
from common.schema import Database


class TestEmbedUtils:
    """Test embed utility functions"""

    def setup_method(self):
        """Setup test data"""
        self.sample_document = LangchainDocument(
            page_content="This is a test document content.", metadata={"source": "/path/to/test_file.txt", "page": 1}
        )
        self.sample_split_doc = LangchainDocument(
            page_content="This is a chunk of content.", metadata={"source": "/path/to/test_file.txt", "start_index": 0}
        )

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    @patch("pathlib.Path.mkdir")
    def test_get_temp_directory_app_tmp(self, mock_mkdir, mock_is_dir, mock_exists):
        """Test temp directory creation in /app/tmp"""
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        result = embed.get_temp_directory("test_client", "embed")

        assert result == Path("/app/tmp") / "test_client" / "embed"
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    def test_get_temp_directory_tmp_fallback(self, mock_mkdir, mock_exists):
        """Test temp directory creation fallback to /tmp"""
        mock_exists.return_value = False

        result = embed.get_temp_directory("test_client", "embed")

        assert result == Path("/tmp") / "test_client" / "embed"
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.getsize")
    @patch("json.dumps")
    def test_doc_to_json_default_output(self, mock_json_dumps, mock_getsize, mock_file):
        """Test document to JSON conversion with default output directory"""
        mock_json_dumps.return_value = '{"test": "data"}'
        mock_getsize.return_value = 100

        result = embed.doc_to_json([self.sample_document], "/path/to/test_file.txt", "/tmp")

        mock_file.assert_called_once()
        mock_json_dumps.assert_called_once()
        mock_getsize.assert_called_once()
        assert result.endswith("_test_file.json")

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.getsize")
    @patch("json.dumps")
    def test_doc_to_json_custom_output(self, mock_json_dumps, mock_getsize, mock_file):
        """Test document to JSON conversion with custom output directory"""
        mock_json_dumps.return_value = '{"test": "data"}'
        mock_getsize.return_value = 100

        result = embed.doc_to_json([self.sample_document], "/path/to/test_file.txt", "/custom/output")

        mock_file.assert_called_once()
        mock_json_dumps.assert_called_once()
        mock_getsize.assert_called_once()
        assert result == "/custom/output/_test_file.json"

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(embed, "logger")
        assert embed.logger.name == "api.utils.embed"


class TestGetVectorStoreFiles:
    """Test get_vector_store_files() function"""

    def setup_method(self):
        """Setup test data"""
        self.sample_db = Database(
            name="TEST_DB",
            user="test_user",
            password="",
            dsn="localhost:1521/FREEPDB1"
        )

    @patch("server.api.utils.databases.connect")
    @patch("server.api.utils.databases.disconnect")
    def test_get_vector_store_files_with_metadata(self, mock_disconnect, mock_connect):
        """Test retrieving file list with complete metadata"""
        # Mock database connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock query results with metadata
        mock_cursor.fetchall.return_value = [
            ({
                "filename": "doc1.pdf",
                "size": 1024000,
                "time_modified": "2025-11-01T10:00:00",
                "etag": "etag-123"
            },),
            ({
                "filename": "doc1.pdf",
                "size": 1024000,
                "time_modified": "2025-11-01T10:00:00",
                "etag": "etag-123"
            },),
            ({
                "filename": "doc2.txt",
                "size": 2048,
                "time_modified": "2025-11-02T10:00:00",
                "etag": "etag-456"
            },),
        ]

        # Execute
        result = embed.get_vector_store_files(self.sample_db, "TEST_VS")

        # Verify
        assert result["vector_store"] == "TEST_VS"
        assert result["total_files"] == 2
        assert result["total_chunks"] == 3
        assert result["orphaned_chunks"] == 0

        # Verify files
        assert len(result["files"]) == 2
        assert result["files"][0]["filename"] == "doc1.pdf"
        assert result["files"][0]["chunk_count"] == 2
        assert result["files"][0]["size"] == 1024000
        assert result["files"][1]["filename"] == "doc2.txt"
        assert result["files"][1]["chunk_count"] == 1

        mock_disconnect.assert_called_once()

    @patch("server.api.utils.databases.connect")
    @patch("server.api.utils.databases.disconnect")
    def test_get_vector_store_files_with_decimal_size(self, mock_disconnect, mock_connect):
        """Test handling of Decimal size from Oracle NUMBER type"""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock query results with Decimal size (from Oracle)
        mock_cursor.fetchall.return_value = [
            ({
                "filename": "doc.pdf",
                "size": Decimal("1024000"),  # Oracle returns Decimal
                "time_modified": "2025-11-01T10:00:00",
                "etag": "etag-123"
            },),
        ]

        # Execute
        result = embed.get_vector_store_files(self.sample_db, "TEST_VS")

        # Verify Decimal was converted to int
        assert result["files"][0]["size"] == 1024000
        assert isinstance(result["files"][0]["size"], int)

    @patch("server.api.utils.databases.connect")
    @patch("server.api.utils.databases.disconnect")
    def test_get_vector_store_files_old_format(self, mock_disconnect, mock_connect):
        """Test retrieving files with old metadata format (source field)"""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock query results with old format (source instead of filename)
        mock_cursor.fetchall.return_value = [
            ({"source": "/path/to/doc1.pdf"},),
            ({"source": "/path/to/doc1.pdf"},),
        ]

        # Execute
        result = embed.get_vector_store_files(self.sample_db, "TEST_VS")

        # Verify fallback to source field worked
        assert result["total_files"] == 1
        assert result["files"][0]["filename"] == "doc1.pdf"
        assert result["files"][0]["chunk_count"] == 2

    @patch("server.api.utils.databases.connect")
    @patch("server.api.utils.databases.disconnect")
    def test_get_vector_store_files_with_orphaned_chunks(self, mock_disconnect, mock_connect):
        """Test detection of orphaned chunks without valid filename"""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock query results with some orphaned chunks
        mock_cursor.fetchall.return_value = [
            ({"filename": "doc1.pdf", "size": 1024},),
            ({"filename": "doc1.pdf", "size": 1024},),
            ({"other_field": "no_filename"},),  # Orphaned chunk
            ({"other_field": "no_source"},),  # Orphaned chunk
        ]

        # Execute
        result = embed.get_vector_store_files(self.sample_db, "TEST_VS")

        # Verify
        assert result["total_files"] == 1
        assert result["total_chunks"] == 2
        assert result["orphaned_chunks"] == 2
        assert result["files"][0]["chunk_count"] == 2

    @patch("server.api.utils.databases.connect")
    @patch("server.api.utils.databases.disconnect")
    def test_get_vector_store_files_empty_store(self, mock_disconnect, mock_connect):
        """Test retrieving from empty vector store"""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock empty results
        mock_cursor.fetchall.return_value = []

        # Execute
        result = embed.get_vector_store_files(self.sample_db, "EMPTY_VS")

        # Verify
        assert result["vector_store"] == "EMPTY_VS"
        assert result["total_files"] == 0
        assert result["total_chunks"] == 0
        assert result["orphaned_chunks"] == 0
        assert len(result["files"]) == 0

    @patch("server.api.utils.databases.connect")
    @patch("server.api.utils.databases.disconnect")
    def test_get_vector_store_files_sorts_by_filename(self, mock_disconnect, mock_connect):
        """Test that files are sorted alphabetically by filename"""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock query results in random order
        mock_cursor.fetchall.return_value = [
            ({"filename": "zebra.pdf"},),
            ({"filename": "apple.txt"},),
            ({"filename": "monkey.md"},),
        ]

        # Execute
        result = embed.get_vector_store_files(self.sample_db, "TEST_VS")

        # Verify sorted order
        filenames = [f["filename"] for f in result["files"]]
        assert filenames == ["apple.txt", "monkey.md", "zebra.pdf"]
