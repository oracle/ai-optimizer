"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from pathlib import Path
from unittest.mock import patch, mock_open

from langchain.docstore.document import Document as LangchainDocument

from server.api.utils import embed


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
