"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/testbed.py
Tests for Q&A testbed and evaluation endpoints.
"""
# pylint: disable=protected-access,too-few-public-methods

from unittest.mock import patch, MagicMock
from io import BytesIO
import pytest
from fastapi import HTTPException, UploadFile
import litellm

from server.api.v1 import testbed
from common.schema import TestSets, TestSetQA, Evaluation, EvaluationReport


class TestTestbedTestsets:
    """Tests for the testbed_testsets endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.get_testsets")
    async def test_testbed_testsets_returns_list(self, mock_get_testsets, mock_get_db, mock_db_connection):
        """testbed_testsets should return list of testsets."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db

        mock_testsets = [
            TestSets(tid="TS001", name="Test Set 1", created="2024-01-01"),
            TestSets(tid="TS002", name="Test Set 2", created="2024-01-02"),
        ]
        mock_get_testsets.return_value = mock_testsets

        result = await testbed.testbed_testsets(client="test_client")

        assert result == mock_testsets
        mock_get_testsets.assert_called_once_with(db_conn=mock_db_connection)

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.get_testsets")
    async def test_testbed_testsets_empty_list(self, mock_get_testsets, mock_get_db, mock_db_connection):
        """testbed_testsets should return empty list when no testsets."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db
        mock_get_testsets.return_value = []

        result = await testbed.testbed_testsets(client="test_client")

        assert result == []


class TestTestbedEvaluations:
    """Tests for the testbed_evaluations endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.get_evaluations")
    async def test_testbed_evaluations_returns_list(self, mock_get_evals, mock_get_db, mock_db_connection):
        """testbed_evaluations should return list of evaluations."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db

        mock_evals = [
            Evaluation(eid="EV001", evaluated="2024-01-01", correctness=0.85),
            Evaluation(eid="EV002", evaluated="2024-01-02", correctness=0.90),
        ]
        mock_get_evals.return_value = mock_evals

        result = await testbed.testbed_evaluations(tid="ts001", client="test_client")

        assert result == mock_evals
        mock_get_evals.assert_called_once_with(db_conn=mock_db_connection, tid="TS001")

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.get_evaluations")
    async def test_testbed_evaluations_uppercases_tid(self, mock_get_evals, mock_get_db, mock_db_connection):
        """testbed_evaluations should uppercase the tid."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db
        mock_get_evals.return_value = []

        await testbed.testbed_evaluations(tid="lowercase", client="test_client")

        mock_get_evals.assert_called_once_with(db_conn=mock_db_connection, tid="LOWERCASE")


class TestTestbedEvaluation:
    """Tests for the testbed_evaluation endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.process_report")
    async def test_testbed_evaluation_returns_report(self, mock_process_report, mock_get_db, mock_db_connection):
        """testbed_evaluation should return evaluation report."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db

        mock_report = MagicMock(spec=EvaluationReport)
        mock_process_report.return_value = mock_report

        result = await testbed.testbed_evaluation(eid="ev001", client="test_client")

        assert result == mock_report
        mock_process_report.assert_called_once_with(db_conn=mock_db_connection, eid="EV001")


class TestTestbedTestsetQa:
    """Tests for the testbed_testset_qa endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.get_testset_qa")
    async def test_testbed_testset_qa_returns_data(self, mock_get_qa, mock_get_db, mock_db_connection):
        """testbed_testset_qa should return Q&A data."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db

        mock_qa = TestSetQA(qa_data=[{"question": "Q1", "answer": "A1"}])
        mock_get_qa.return_value = mock_qa

        result = await testbed.testbed_testset_qa(tid="ts001", client="test_client")

        assert result == mock_qa
        mock_get_qa.assert_called_once_with(db_conn=mock_db_connection, tid="TS001")


class TestTestbedDeleteTestset:
    """Tests for the testbed_delete_testset endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.delete_qa")
    async def test_testbed_delete_testset_success(self, mock_delete_qa, mock_get_db, mock_db_connection):
        """testbed_delete_testset should delete and return success."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db
        mock_delete_qa.return_value = None

        result = await testbed.testbed_delete_testset(tid="ts001", client="test_client")

        assert result.status_code == 200
        mock_delete_qa.assert_called_once_with(mock_db_connection, "TS001")


class TestTestbedUpsertTestsets:
    """Tests for the testbed_upsert_testsets endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.jsonl_to_json_content")
    @patch("server.api.v1.testbed.utils_testbed.upsert_qa")
    @patch("server.api.v1.testbed.testbed_testset_qa")
    async def test_testbed_upsert_testsets_success(
        self, mock_testset_qa, mock_upsert, mock_jsonl, mock_get_db, mock_db_connection
    ):
        """testbed_upsert_testsets should upload and return Q&A."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db
        mock_jsonl.return_value = [{"question": "Q1", "answer": "A1"}]
        mock_upsert.return_value = "TS001"
        mock_testset_qa.return_value = TestSetQA(qa_data=[{"question": "Q1"}])

        mock_file = UploadFile(file=BytesIO(b'{"question": "Q1"}'), filename="test.jsonl")

        result = await testbed.testbed_upsert_testsets(
            files=[mock_file], name="Test Set", tid=None, client="test_client"
        )

        assert isinstance(result, TestSetQA)
        mock_db_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.jsonl_to_json_content")
    async def test_testbed_upsert_testsets_handles_exception(self, mock_jsonl, mock_get_db, mock_db_connection):
        """testbed_upsert_testsets should raise 500 on exception."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db
        mock_jsonl.side_effect = Exception("Parse error")

        mock_file = UploadFile(file=BytesIO(b"invalid"), filename="test.jsonl")

        with pytest.raises(HTTPException) as exc_info:
            await testbed.testbed_upsert_testsets(files=[mock_file], name="Test", tid=None, client="test_client")

        assert exc_info.value.status_code == 500


class TestHandleTestsetError:
    """Tests for the _handle_testset_error helper function."""

    def test_handle_testset_error_key_error_columns(self, tmp_path):
        """_handle_testset_error should raise 400 for column KeyError."""
        ex = KeyError("None of ['col1'] are in the columns")

        with pytest.raises(HTTPException) as exc_info:
            testbed._handle_testset_error(ex, tmp_path, "test-model")

        assert exc_info.value.status_code == 400
        assert "test-model" in str(exc_info.value.detail)

    def test_handle_testset_error_value_error(self, tmp_path):
        """_handle_testset_error should raise 400 for ValueError."""
        ex = ValueError("Invalid value")

        with pytest.raises(HTTPException) as exc_info:
            testbed._handle_testset_error(ex, tmp_path, "test-model")

        assert exc_info.value.status_code == 400

    def test_handle_testset_error_api_connection_error(self, tmp_path):
        """_handle_testset_error should raise 424 for API connection error."""
        ex = litellm.APIConnectionError(message="Connection failed", llm_provider="openai", model="gpt-4")

        with pytest.raises(HTTPException) as exc_info:
            testbed._handle_testset_error(ex, tmp_path, "test-model")

        assert exc_info.value.status_code == 424

    def test_handle_testset_error_unknown_exception(self, tmp_path):
        """_handle_testset_error should raise 500 for unknown exceptions."""
        ex = RuntimeError("Unknown error")

        with pytest.raises(HTTPException) as exc_info:
            testbed._handle_testset_error(ex, tmp_path, "test-model")

        assert exc_info.value.status_code == 500

    def test_handle_testset_error_other_key_error(self, tmp_path):
        """_handle_testset_error should re-raise other KeyErrors."""
        ex = KeyError("some_other_key")

        with pytest.raises(KeyError):
            testbed._handle_testset_error(ex, tmp_path, "test-model")


class TestTestbedGenerateQa:
    """Tests for the testbed_generate_qa endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_oci.get")
    async def test_testbed_generate_qa_raises_400_on_value_error(self, mock_oci_get):
        """testbed_generate_qa should raise 400 on ValueError."""
        mock_oci_get.side_effect = ValueError("Invalid OCI config")

        mock_file = UploadFile(file=BytesIO(b"content"), filename="test.txt")

        with pytest.raises(HTTPException) as exc_info:
            await testbed.testbed_generate_qa(
                files=[mock_file],
                name="Test",
                ll_model="gpt-4",
                embed_model="text-embedding-3",
                questions=2,
                client="test_client",
            )

        assert exc_info.value.status_code == 400


class TestRouterConfiguration:
    """Tests for router configuration."""

    def test_auth_router_exists(self):
        """The auth router should be defined."""
        assert hasattr(testbed, "auth")

    def test_auth_router_has_routes(self):
        """The auth router should have registered routes."""
        routes = [route.path for route in testbed.auth.routes]

        assert "/testsets" in routes
        assert "/evaluations" in routes
        assert "/evaluation" in routes
        assert "/testset_qa" in routes
        assert "/testset_delete/{tid}" in routes
        assert "/testset_load" in routes
        assert "/testset_generate" in routes
        assert "/evaluate" in routes


class TestLoggerConfiguration:
    """Tests for logger configuration."""

    def test_logger_exists(self):
        """Logger should be configured."""
        assert hasattr(testbed, "logger")

    def test_logger_name(self):
        """Logger should have correct name."""
        assert testbed.logger.name == "endpoints.v1.testbed"
