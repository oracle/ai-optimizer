"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/testbed.py
Tests for testbed utility functions.

Uses hybrid approach:
- Real Oracle database for testbed table creation and querying
- Mocks for external dependencies (PDF processing, LLM calls)
"""

# pylint: disable=too-few-public-methods

import json
from unittest.mock import patch, MagicMock

import pytest

from server.api.utils import testbed as utils_testbed


class TestJsonlToJsonContent:
    """Tests for the jsonl_to_json_content function."""

    def test_jsonl_to_json_content_single_json(self):
        """Should parse single JSON object."""
        content = '{"question": "What is AI?", "answer": "Artificial Intelligence"}'

        result = utils_testbed.jsonl_to_json_content(content)

        parsed = json.loads(result)
        assert parsed["question"] == "What is AI?"

    def test_jsonl_to_json_content_jsonl(self):
        """Should parse JSONL (multiple lines)."""
        content = '{"q": "Q1"}\n{"q": "Q2"}'

        result = utils_testbed.jsonl_to_json_content(content)

        parsed = json.loads(result)
        assert len(parsed) == 2

    def test_jsonl_to_json_content_bytes(self):
        """Should handle bytes input."""
        content = b'{"question": "test"}'

        result = utils_testbed.jsonl_to_json_content(content)

        parsed = json.loads(result)
        assert parsed["question"] == "test"

    def test_jsonl_to_json_content_single_jsonl(self):
        """Should handle single line JSONL."""
        content = '{"question": "test"}\n'

        result = utils_testbed.jsonl_to_json_content(content)

        parsed = json.loads(result)
        assert parsed["question"] == "test"

    def test_jsonl_to_json_content_invalid(self):
        """Should raise ValueError for invalid content."""
        content = "not valid json at all"

        with pytest.raises(ValueError) as exc_info:
            utils_testbed.jsonl_to_json_content(content)

        assert "Invalid JSONL content" in str(exc_info.value)


class TestCreateTestsetObjects:
    """Tests for the create_testset_objects function.

    Uses mocks since DDL (CREATE TABLE) causes implicit commits in Oracle,
    which breaks savepoint-based test isolation.
    """

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    def test_create_testset_objects_executes_ddl(self, mock_execute):
        """Should execute SQL to create testset tables."""
        mock_conn = MagicMock()

        utils_testbed.create_testset_objects(mock_conn)

        # Should execute 3 DDL statements (testsets, testset_qa, evaluations)
        assert mock_execute.call_count == 3


class TestGetTestsets:
    """Tests for the get_testsets function.

    Uses mocks since the function may trigger DDL which causes implicit commits.
    """

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    def test_get_testsets_returns_list(self, mock_execute):
        """Should return list of TestSets."""
        mock_conn = MagicMock()
        # Return empty result set
        mock_execute.return_value = []

        result = utils_testbed.get_testsets(mock_conn)

        assert isinstance(result, list)
        assert len(result) == 0

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    def test_get_testsets_creates_tables_on_first_call(self, mock_execute):
        """Should create tables if they don't exist."""
        mock_conn = MagicMock()
        # First call returns None (which causes TypeError during unpacking),
        # then 3 DDL calls for table creation, then final query returns []
        mock_execute.side_effect = [None, None, None, None, []]

        result = utils_testbed.get_testsets(mock_conn)

        assert isinstance(result, list)


class TestGetTestsetQa:
    """Tests for the get_testset_qa function."""

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    def test_get_testset_qa_returns_qa(self, mock_execute):
        """Should return TestSetQA object."""
        mock_execute.return_value = [('{"question": "Q1"}',)]
        mock_conn = MagicMock()

        result = utils_testbed.get_testset_qa(mock_conn, "abc123")

        assert len(result.qa_data) == 1


class TestGetEvaluations:
    """Tests for the get_evaluations function."""

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    def test_get_evaluations_returns_list(self, mock_execute):
        """Should return list of Evaluation objects."""
        mock_eid = MagicMock()
        mock_eid.hex.return_value = "eval123"
        mock_execute.return_value = [(mock_eid, "2024-01-01", 0.85)]
        mock_conn = MagicMock()

        result = utils_testbed.get_evaluations(mock_conn, "tid123")

        assert len(result) == 1
        assert result[0].correctness == 0.85

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    @patch("server.api.utils.testbed.create_testset_objects")
    def test_get_evaluations_creates_tables_on_error(self, mock_create, mock_execute):
        """Should create tables if TypeError occurs."""
        mock_execute.return_value = None
        mock_conn = MagicMock()

        result = utils_testbed.get_evaluations(mock_conn, "tid123")

        mock_create.assert_called_once()
        assert result == []


class TestDeleteQa:
    """Tests for the delete_qa function."""

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    def test_delete_qa_executes_sql(self, mock_execute):
        """Should execute DELETE SQL."""
        mock_conn = MagicMock()

        utils_testbed.delete_qa(mock_conn, "tid123")

        mock_execute.assert_called_once()
        mock_conn.commit.assert_called_once()


class TestUpsertQa:
    """Tests for the upsert_qa function."""

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    def test_upsert_qa_single_qa(self, mock_execute):
        """Should handle single QA object."""
        mock_execute.return_value = "tid123"
        mock_conn = MagicMock()
        json_data = '{"question": "Q1", "answer": "A1"}'

        result = utils_testbed.upsert_qa(mock_conn, "TestSet", "2024-01-01T00:00:00.000", json_data)

        mock_execute.assert_called_once()
        assert result == "tid123"

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    def test_upsert_qa_multiple_qa(self, mock_execute):
        """Should handle multiple QA objects."""
        mock_execute.return_value = "tid123"
        mock_conn = MagicMock()
        json_data = '[{"q": "Q1"}, {"q": "Q2"}]'

        utils_testbed.upsert_qa(mock_conn, "TestSet", "2024-01-01T00:00:00.000", json_data)

        mock_execute.assert_called_once()


class TestInsertEvaluation:
    """Tests for the insert_evaluation function."""

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    def test_insert_evaluation_executes_sql(self, mock_execute):
        """Should execute INSERT SQL."""
        mock_execute.return_value = "eid123"
        mock_conn = MagicMock()

        result = utils_testbed.insert_evaluation(
            mock_conn, "tid123", "2024-01-01T00:00:00.000", 0.85, '{"model": "gpt-4"}', b"report_data"
        )

        mock_execute.assert_called_once()
        assert result == "eid123"


class TestLoadAndSplit:
    """Tests for the load_and_split function."""

    @patch("server.api.utils.testbed.PdfReader")
    @patch("server.api.utils.testbed.SentenceSplitter")
    def test_load_and_split_processes_pdf(self, mock_splitter, mock_reader):
        """Should load PDF and split into nodes."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page content"
        mock_reader.return_value.pages = [mock_page]

        mock_splitter_instance = MagicMock()
        mock_splitter_instance.return_value = ["node1", "node2"]
        mock_splitter.return_value = mock_splitter_instance

        # chunk_size=1024, overlap=10% (102), effective_chunk_size=922
        utils_testbed.load_and_split("/path/to/doc.pdf", chunk_size=1024)

        mock_reader.assert_called_once_with("/path/to/doc.pdf")
        mock_splitter.assert_called_once_with(chunk_size=922, chunk_overlap=102)

    @patch("server.api.utils.testbed.PdfReader")
    @patch("server.api.utils.testbed.SentenceSplitter")
    def test_load_and_split_calculates_overlap_correctly(self, mock_splitter, mock_reader):
        """Should calculate 10% overlap from chunk_size."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page content"
        mock_reader.return_value.pages = [mock_page]

        mock_splitter_instance = MagicMock()
        mock_splitter_instance.return_value = []
        mock_splitter.return_value = mock_splitter_instance

        # chunk_size=500, overlap=10% (50), effective_chunk_size=450
        utils_testbed.load_and_split("/path/to/doc.pdf", chunk_size=500)

        mock_splitter.assert_called_once_with(chunk_size=450, chunk_overlap=50)

    @patch("server.api.utils.testbed.PdfReader")
    @patch("server.api.utils.testbed.SentenceSplitter")
    def test_load_and_split_with_small_chunk_size(self, mock_splitter, mock_reader):
        """Should handle small chunk sizes correctly."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page content"
        mock_reader.return_value.pages = [mock_page]

        mock_splitter_instance = MagicMock()
        mock_splitter_instance.return_value = []
        mock_splitter.return_value = mock_splitter_instance

        # chunk_size=100, overlap=10% (10), effective_chunk_size=90
        utils_testbed.load_and_split("/path/to/doc.pdf", chunk_size=100)

        mock_splitter.assert_called_once_with(chunk_size=90, chunk_overlap=10)

    @patch("server.api.utils.testbed.PdfReader")
    @patch("server.api.utils.testbed.SentenceSplitter")
    def test_load_and_split_uses_default_chunk_size(self, mock_splitter, mock_reader):
        """Should use default chunk_size of 512 when not specified."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page content"
        mock_reader.return_value.pages = [mock_page]

        mock_splitter_instance = MagicMock()
        mock_splitter_instance.return_value = []
        mock_splitter.return_value = mock_splitter_instance

        # Default chunk_size=512, overlap=10% (51), effective_chunk_size=461
        utils_testbed.load_and_split("/path/to/doc.pdf")

        mock_splitter.assert_called_once_with(chunk_size=461, chunk_overlap=51)


class TestBuildKnowledgeBase:
    """Tests for the build_knowledge_base function."""

    @patch("server.api.utils.testbed.set_llm_model")
    @patch("server.api.utils.testbed.set_embedding_model")
    @patch("server.api.utils.testbed.KnowledgeBase")
    @patch("server.api.utils.testbed.generate_testset")
    def test_build_knowledge_base_success(
        self, mock_generate, mock_kb, mock_set_embed, mock_set_llm
    ):
        """Should create knowledge base and generate testset."""
        mock_testset = MagicMock()
        mock_generate.return_value = mock_testset

        mock_text_node = MagicMock()
        mock_text_node.text = "Sample text"
        text_nodes = [mock_text_node]

        ll_model_config = {"llm_model": "openai/gpt-4", "api_key": "test"}
        embed_model_config = {"model": "openai/text-embedding-3-small", "api_key": "test"}

        result = utils_testbed.build_knowledge_base(
            text_nodes,
            questions=5,
            ll_model_config=ll_model_config,
            embed_model_config=embed_model_config,
        )

        mock_set_llm.assert_called_once_with(**ll_model_config)
        mock_set_embed.assert_called_once_with(**embed_model_config)
        mock_kb.assert_called_once()
        mock_generate.assert_called_once()
        assert result == mock_testset


class TestProcessReport:
    """Tests for the process_report function."""

    @patch("server.api.utils.testbed.utils_databases.execute_sql")
    @patch("server.api.utils.testbed.pickle.loads")
    def test_process_report_success(self, mock_pickle, mock_execute, make_settings):
        """Should process evaluation report."""
        mock_eid = MagicMock()
        mock_eid.hex.return_value = "eid123"

        mock_report = MagicMock()
        mock_report.to_pandas.return_value = MagicMock(to_dict=MagicMock(return_value={}))
        mock_report.correctness_by_topic.return_value = MagicMock(to_dict=MagicMock(return_value={}))
        mock_report.failures = MagicMock(to_dict=MagicMock(return_value={}))
        mock_pickle.return_value = mock_report

        # Settings needs to be a valid Settings object (or dict with required fields)
        settings_data = make_settings().model_dump()
        mock_execute.return_value = [
            {
                "EID": mock_eid,
                "EVALUATED": "2024-01-01",
                "CORRECTNESS": 0.85,
                "SETTINGS": settings_data,
                "RAG_REPORT": b"data",
            }
        ]
        mock_conn = MagicMock()

        result = utils_testbed.process_report(mock_conn, "eid123")

        assert result.eid == "eid123"
        assert result.correctness == 0.85
