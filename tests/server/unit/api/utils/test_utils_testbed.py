"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=protected-access import-error import-outside-toplevel

from unittest.mock import patch, MagicMock
import json

import pytest
from oracledb import Connection

from server.api.utils import testbed


class TestTestbedUtils:
    """Test testbed utility functions"""

    @pytest.fixture
    def mock_connection(self):
        """Mock database connection fixture"""
        return MagicMock(spec=Connection)

    @pytest.fixture
    def sample_qa_data(self):
        """Sample QA data fixture"""
        return {
            "question": "What is the capital of France?",
            "answer": "Paris",
            "context": "France is a country in Europe.",
        }

    def test_jsonl_to_json_content_single_json(self):
        """Test converting single JSON object to JSON content"""
        content = '{"key": "value"}'
        result = testbed.jsonl_to_json_content(content)
        expected = json.dumps({"key": "value"})
        assert result == expected

    def test_jsonl_to_json_content_jsonl_multiple_lines(self):
        """Test converting JSONL with multiple lines to JSON content"""
        content = '{"line": 1}\n{"line": 2}\n{"line": 3}'
        result = testbed.jsonl_to_json_content(content)
        expected = json.dumps([{"line": 1}, {"line": 2}, {"line": 3}])
        assert result == expected

    def test_jsonl_to_json_content_jsonl_single_line(self):
        """Test converting JSONL with single line to JSON content"""
        content = '{"single": "line"}'
        result = testbed.jsonl_to_json_content(content)
        expected = json.dumps({"single": "line"})
        assert result == expected

    def test_jsonl_to_json_content_bytes_input(self):
        """Test converting bytes JSONL content to JSON"""
        content = b'{"bytes": "content"}'
        result = testbed.jsonl_to_json_content(content)
        expected = json.dumps({"bytes": "content"})
        assert result == expected

    def test_jsonl_to_json_content_invalid_json(self):
        """Test handling invalid JSON content"""
        content = '{"invalid": json}'
        with pytest.raises(ValueError, match="Invalid JSONL content"):
            testbed.jsonl_to_json_content(content)

    def test_jsonl_to_json_content_empty_content(self):
        """Test handling empty content"""
        content = ""
        with pytest.raises(ValueError, match="Invalid JSONL content"):
            testbed.jsonl_to_json_content(content)

    def test_jsonl_to_json_content_whitespace_content(self):
        """Test handling whitespace-only content"""
        content = "   \n   \n   "
        with pytest.raises(ValueError, match="Invalid JSONL content"):
            testbed.jsonl_to_json_content(content)

    @patch("server.api.utils.databases.execute_sql")
    def test_create_testset_objects(self, mock_execute_sql, mock_connection):
        """Test creating testset database objects"""
        mock_execute_sql.return_value = []

        testbed.create_testset_objects(mock_connection)

        # Should execute 3 SQL statements (testsets, testset_qa, evaluations tables)
        assert mock_execute_sql.call_count == 3

        # Verify table creation statements
        call_args_list = mock_execute_sql.call_args_list
        assert "oai_testsets" in call_args_list[0][0][1]
        assert "oai_testset_qa" in call_args_list[1][0][1]
        assert "oai_evaluations" in call_args_list[2][0][1]

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(testbed, "logger")
        assert testbed.logger.name == "api.utils.testbed"
