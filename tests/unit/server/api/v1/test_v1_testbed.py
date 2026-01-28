"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/testbed.py
Tests for Q&A testbed and evaluation endpoints.
"""
# pylint: disable=protected-access,too-few-public-methods,too-many-arguments
# pylint: disable=too-many-positional-arguments,too-many-locals

from unittest.mock import patch, MagicMock, AsyncMock
from io import BytesIO
import pytest
from fastapi import HTTPException, UploadFile
import litellm

from server.api.v1 import testbed
from common.schema import QASets, QASetData, Evaluation, EvaluationReport


class TestTestbedTestsets:
    """Tests for the testbed_testsets endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.get_testsets")
    async def test_testbed_testsets_returns_list(
        self, mock_get_testsets, mock_get_db, mock_db_connection
    ):
        """testbed_testsets should return list of testsets."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db

        mock_testsets = [
            QASets(tid="TS001", name="Test Set 1", created="2024-01-01"),
            QASets(tid="TS002", name="Test Set 2", created="2024-01-02"),
        ]
        mock_get_testsets.return_value = mock_testsets

        result = await testbed.testbed_testsets(client="test_client")

        assert result == mock_testsets
        mock_get_testsets.assert_called_once_with(db_conn=mock_db_connection)

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.get_testsets")
    async def test_testbed_testsets_empty_list(
        self, mock_get_testsets, mock_get_db, mock_db_connection
    ):
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
    async def test_testbed_evaluations_returns_list(
        self, mock_get_evals, mock_get_db, mock_db_connection
    ):
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
    async def test_testbed_evaluations_uppercases_tid(
        self, mock_get_evals, mock_get_db, mock_db_connection
    ):
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
    async def test_testbed_evaluation_returns_report(
        self, mock_process_report, mock_get_db, mock_db_connection
    ):
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
    async def test_testbed_testset_qa_returns_data(
        self, mock_get_qa, mock_get_db, mock_db_connection
    ):
        """testbed_testset_qa should return Q&A data."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db

        mock_qa = QASetData(qa_data=[{"question": "Q1", "answer": "A1"}])
        mock_get_qa.return_value = mock_qa

        result = await testbed.testbed_testset_qa(tid="ts001", client="test_client")

        assert result == mock_qa
        mock_get_qa.assert_called_once_with(db_conn=mock_db_connection, tid="TS001")


class TestTestbedDeleteTestset:
    """Tests for the testbed_delete_testset endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.delete_qa")
    async def test_testbed_delete_testset_success(
        self, mock_delete_qa, mock_get_db, mock_db_connection
    ):
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
        mock_testset_qa.return_value = QASetData(qa_data=[{"question": "Q1"}])

        mock_file = UploadFile(file=BytesIO(b'{"question": "Q1"}'), filename="test.jsonl")

        result = await testbed.testbed_upsert_testsets(
            files=[mock_file], name="Test Set", tid=None, client="test_client"
        )

        assert isinstance(result, QASetData)
        mock_db_connection.commit.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.jsonl_to_json_content")
    async def test_testbed_upsert_testsets_handles_exception(
        self, mock_jsonl, mock_get_db, mock_db_connection
    ):
        """testbed_upsert_testsets should raise 500 on exception."""
        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db
        mock_jsonl.side_effect = Exception("Parse error")

        mock_file = UploadFile(file=BytesIO(b"invalid"), filename="test.jsonl")

        with pytest.raises(HTTPException) as exc_info:
            await testbed.testbed_upsert_testsets(
                files=[mock_file], name="Test", tid=None, client="test_client"
            )

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
        ex = litellm.APIConnectionError(
            message="Connection failed", llm_provider="openai", model="gpt-4"
        )

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


class TestProcessFileForTestset:
    """Tests for the _process_file_for_testset helper function."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_models.get_litellm_config")
    @patch("server.api.v1.testbed.utils_testbed.load_and_split")
    @patch("server.api.v1.testbed.utils_testbed.build_knowledge_base")
    async def test_process_file_writes_and_processes(
        self, mock_build_kb, mock_load_split, mock_get_config, tmp_path
    ):
        """_process_file_for_testset should write file and build knowledge base."""
        mock_get_config.return_value = {"model": "test", "max_chunk_size": 512}
        mock_load_split.return_value = ["node1", "node2"]
        mock_testset = MagicMock()

        # Make save create an actual file (function reads it after save)
        def save_side_effect(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"question": "generated"}\n')

        mock_testset.save = save_side_effect
        mock_build_kb.return_value = mock_testset

        mock_file = MagicMock()
        mock_file.read = AsyncMock(return_value=b"file content")
        mock_file.filename = "test.pdf"

        full_testsets = tmp_path / "all_testsets.jsonl"
        full_testsets.touch()

        await testbed._process_file_for_testset(
            file=mock_file,
            temp_directory=tmp_path,
            full_testsets=full_testsets,
            name="TestSet",
            questions=5,
            ll_model="gpt-4",
            embed_model="text-embedding-3",
            oci_config=MagicMock(),
        )

        mock_load_split.assert_called_once()
        mock_build_kb.assert_called_once()
        # Verify file was created (save was called)
        assert (tmp_path / "TestSet.jsonl").exists()

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_models.get_litellm_config")
    @patch("server.api.v1.testbed.utils_testbed.load_and_split")
    @patch("server.api.v1.testbed.utils_testbed.build_knowledge_base")
    async def test_process_file_appends_to_full_testsets(
        self, mock_build_kb, mock_load_split, mock_get_config, tmp_path
    ):
        """_process_file_for_testset should append to full_testsets file."""
        mock_get_config.return_value = {"model": "test", "max_chunk_size": 512}
        mock_load_split.return_value = ["node1"]
        mock_testset = MagicMock()

        def save_side_effect(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"question": "Q1"}\n')

        mock_testset.save = save_side_effect
        mock_build_kb.return_value = mock_testset

        mock_file = MagicMock()
        mock_file.read = AsyncMock(return_value=b"content")
        mock_file.filename = "test.pdf"

        full_testsets = tmp_path / "all_testsets.jsonl"
        full_testsets.write_text('{"question": "existing"}\n')

        await testbed._process_file_for_testset(
            file=mock_file,
            temp_directory=tmp_path,
            full_testsets=full_testsets,
            name="TestSet",
            questions=2,
            ll_model="gpt-4",
            embed_model="embed",
            oci_config=MagicMock(),
        )

        content = full_testsets.read_text()
        assert '{"question": "existing"}' in content
        assert '{"question": "Q1"}' in content

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_models.get_litellm_config")
    @patch("server.api.v1.testbed.utils_testbed.load_and_split")
    @patch("server.api.v1.testbed.utils_testbed.build_knowledge_base")
    async def test_process_file_passes_max_chunk_size_to_load_and_split(
        self, mock_build_kb, mock_load_split, mock_get_config, tmp_path
    ):
        """_process_file_for_testset should pass max_chunk_size to load_and_split."""
        # First call for ll_model, second for embed_model
        mock_get_config.side_effect = [
            {"llm_model": "gpt-4"},
            {"model": "text-embedding-3", "max_chunk_size": 8192},
        ]
        mock_load_split.return_value = ["node1"]
        mock_testset = MagicMock()

        def save_side_effect(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"question": "Q1"}\n')

        mock_testset.save = save_side_effect
        mock_build_kb.return_value = mock_testset

        mock_file = MagicMock()
        mock_file.read = AsyncMock(return_value=b"content")
        mock_file.filename = "test.pdf"

        full_testsets = tmp_path / "all_testsets.jsonl"
        full_testsets.touch()

        await testbed._process_file_for_testset(
            file=mock_file,
            temp_directory=tmp_path,
            full_testsets=full_testsets,
            name="TestSet",
            questions=2,
            ll_model="openai/gpt-4",
            embed_model="openai/text-embedding-3",
            oci_config=MagicMock(),
        )

        # Verify load_and_split was called with max_chunk_size from embed model config
        mock_load_split.assert_called_once()
        call_args = mock_load_split.call_args
        # Second positional argument should be max_chunk_size (8192)
        assert call_args[0][1] == 8192


class TestCollectTestbedAnswers:
    """Tests for the _collect_testbed_answers helper function."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.chat.chat_post")
    async def test_collect_answers_returns_agent_answers(self, mock_chat_post):
        """_collect_testbed_answers should return list of AgentAnswer objects."""
        mock_chat_post.return_value = {
            "choices": [{"message": {"content": "Test response"}}]
        }

        mock_df = MagicMock()
        mock_df.itertuples.return_value = [
            MagicMock(question="Question 1"),
            MagicMock(question="Question 2"),
        ]
        mock_testset = MagicMock()
        mock_testset.to_pandas.return_value = mock_df

        result = await testbed._collect_testbed_answers(mock_testset, "test_client")

        assert len(result) == 2
        assert result[0].message == "Test response"
        assert result[1].message == "Test response"

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.chat.chat_post")
    async def test_collect_answers_calls_chat_for_each_question(self, mock_chat_post):
        """_collect_testbed_answers should call chat endpoint for each question."""
        mock_chat_post.return_value = {
            "choices": [{"message": {"content": "Response"}}]
        }

        mock_df = MagicMock()
        mock_df.itertuples.return_value = [
            MagicMock(question="Q1"),
            MagicMock(question="Q2"),
            MagicMock(question="Q3"),
        ]
        mock_testset = MagicMock()
        mock_testset.to_pandas.return_value = mock_df

        await testbed._collect_testbed_answers(mock_testset, "client123")

        assert mock_chat_post.call_count == 3

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.chat.chat_post")
    async def test_collect_answers_empty_testset(self, mock_chat_post):
        """_collect_testbed_answers should return empty list for empty testset."""
        mock_df = MagicMock()
        mock_df.itertuples.return_value = []
        mock_testset = MagicMock()
        mock_testset.to_pandas.return_value = mock_df

        result = await testbed._collect_testbed_answers(mock_testset, "client")

        assert result == []
        mock_chat_post.assert_not_called()


class TestTestbedEvaluate:
    """Tests for the testbed_evaluate endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.pickle.dumps")
    @patch("server.api.v1.testbed.utils_settings.get_client")
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.get_testset_qa")
    @patch("server.api.v1.testbed.utils_embed.get_temp_directory")
    @patch("server.api.v1.testbed.QATestset.load")
    @patch("server.api.v1.testbed.utils_oci.get")
    @patch("server.api.v1.testbed.utils_models.get_litellm_config")
    @patch("server.api.v1.testbed.set_llm_model")
    @patch("server.api.v1.testbed.get_prompt_with_override")
    @patch("server.api.v1.testbed._collect_testbed_answers")
    @patch("server.api.v1.testbed.evaluate")
    @patch("server.api.v1.testbed.utils_testbed.insert_evaluation")
    @patch("server.api.v1.testbed.utils_testbed.process_report")
    @patch("server.api.v1.testbed.shutil.rmtree")
    async def test_testbed_evaluate_calls_set_llm_model_with_config(
        self,
        _mock_rmtree,
        mock_process_report,
        mock_insert_eval,
        mock_evaluate,
        mock_collect_answers,
        mock_get_prompt,
        mock_set_llm,
        mock_get_litellm,
        mock_oci_get,
        mock_qa_load,
        mock_get_temp_dir,
        mock_get_testset_qa,
        mock_get_db,
        mock_get_settings,
        mock_pickle_dumps,
        mock_db_connection,
        tmp_path,
    ):
        """testbed_evaluate should call set_llm_model with config from get_litellm_config."""
        mock_pickle_dumps.return_value = b"pickled_report"

        mock_settings = MagicMock()
        mock_settings.ll_model = MagicMock()
        mock_settings.vector_search = MagicMock()
        mock_settings.model_dump_json.return_value = "{}"
        mock_get_settings.return_value = mock_settings

        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db

        mock_get_testset_qa.return_value = MagicMock(qa_data=[{"q": "Q1"}])
        mock_get_temp_dir.return_value = tmp_path
        mock_qa_load.return_value = MagicMock()
        mock_oci_get.return_value = MagicMock()

        # Config returned by get_litellm_config with giskard=True includes llm_model
        judge_config = {"llm_model": "openai/gpt-4", "api_key": "test"}
        mock_get_litellm.return_value = judge_config

        mock_prompt_msg = MagicMock()
        mock_prompt_msg.content.text = "Judge prompt"
        mock_get_prompt.return_value = mock_prompt_msg

        mock_collect_answers.return_value = [MagicMock(message="Answer")]

        mock_report = MagicMock()
        mock_report.correctness = 0.85
        mock_evaluate.return_value = mock_report

        mock_insert_eval.return_value = "EID123"
        mock_process_report.return_value = MagicMock()

        await testbed.testbed_evaluate(
            tid="TS001",
            judge="openai/gpt-4",
            client="test_client",
        )

        # Verify set_llm_model is called with the config (not with duplicate llm_model)
        mock_set_llm.assert_called_once_with(**judge_config)

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.pickle.dumps")
    @patch("server.api.v1.testbed.utils_settings.get_client")
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.get_testset_qa")
    @patch("server.api.v1.testbed.utils_embed.get_temp_directory")
    @patch("server.api.v1.testbed.QATestset.load")
    @patch("server.api.v1.testbed.utils_oci.get")
    @patch("server.api.v1.testbed.utils_models.get_litellm_config")
    @patch("server.api.v1.testbed.set_llm_model")
    @patch("server.api.v1.testbed.get_prompt_with_override")
    @patch("server.api.v1.testbed._collect_testbed_answers")
    @patch("server.api.v1.testbed.evaluate")
    @patch("server.api.v1.testbed.utils_testbed.insert_evaluation")
    @patch("server.api.v1.testbed.utils_testbed.process_report")
    @patch("server.api.v1.testbed.shutil.rmtree")
    async def test_testbed_evaluate_success(
        self,
        _mock_rmtree,
        mock_process_report,
        mock_insert_eval,
        mock_evaluate,
        mock_collect_answers,
        mock_get_prompt,
        _mock_set_llm,
        mock_get_litellm,
        mock_oci_get,
        mock_qa_load,
        mock_get_temp_dir,
        mock_get_testset_qa,
        mock_get_db,
        mock_get_settings,
        mock_pickle_dumps,
        mock_db_connection,
        tmp_path,
    ):
        """testbed_evaluate should run evaluation and return report."""
        mock_pickle_dumps.return_value = b"pickled_report"

        mock_settings = MagicMock()
        mock_settings.ll_model = MagicMock()
        mock_settings.vector_search = MagicMock()
        mock_settings.model_dump_json.return_value = "{}"
        mock_get_settings.return_value = mock_settings

        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db

        mock_get_testset_qa.return_value = MagicMock(qa_data=[{"q": "Q1", "a": "A1"}])
        mock_get_temp_dir.return_value = tmp_path

        mock_loaded_testset = MagicMock()
        mock_qa_load.return_value = mock_loaded_testset

        mock_oci_get.return_value = MagicMock()
        mock_get_litellm.return_value = {"api_key": "test"}

        mock_prompt_msg = MagicMock()
        mock_prompt_msg.content.text = "You are a judge."
        mock_get_prompt.return_value = mock_prompt_msg

        mock_collect_answers.return_value = [MagicMock(message="Answer")]

        mock_report = MagicMock()
        mock_report.correctness = 0.85
        mock_evaluate.return_value = mock_report

        mock_insert_eval.return_value = "EID123"

        mock_eval_report = MagicMock()
        mock_process_report.return_value = mock_eval_report

        result = await testbed.testbed_evaluate(
            tid="TS001",
            judge="gpt-4",
            client="test_client",
        )

        assert result == mock_eval_report
        mock_settings.ll_model.chat_history = False
        mock_settings.vector_search.grade = False
        mock_evaluate.assert_called_once()
        mock_insert_eval.assert_called_once()
        mock_db_connection.commit.assert_called()

    @pytest.mark.asyncio
    @patch("server.api.v1.testbed.utils_settings.get_client")
    @patch("server.api.v1.testbed.utils_databases.get_client_database")
    @patch("server.api.v1.testbed.utils_testbed.get_testset_qa")
    @patch("server.api.v1.testbed.utils_embed.get_temp_directory")
    @patch("server.api.v1.testbed.QATestset.load")
    @patch("server.api.v1.testbed.utils_oci.get")
    @patch("server.api.v1.testbed.utils_models.get_litellm_config")
    @patch("server.api.v1.testbed.set_llm_model")
    @patch("server.api.v1.testbed.get_prompt_with_override")
    @patch("server.api.v1.testbed._collect_testbed_answers")
    @patch("server.api.v1.testbed.evaluate")
    async def test_testbed_evaluate_raises_500_on_correctness_key_error(
        self,
        mock_evaluate,
        mock_collect_answers,
        mock_get_prompt,
        _mock_set_llm,
        mock_get_litellm,
        mock_oci_get,
        mock_qa_load,
        mock_get_temp_dir,
        mock_get_testset_qa,
        mock_get_db,
        mock_get_settings,
        mock_db_connection,
        tmp_path,
    ):
        """testbed_evaluate should raise 500 when correctness key is missing."""
        mock_settings = MagicMock()
        mock_settings.ll_model = MagicMock()
        mock_settings.vector_search = MagicMock()
        mock_get_settings.return_value = mock_settings

        mock_db = MagicMock()
        mock_db.connection = mock_db_connection
        mock_get_db.return_value = mock_db

        mock_get_testset_qa.return_value = MagicMock(qa_data=[{"q": "Q1"}])
        mock_get_temp_dir.return_value = tmp_path

        mock_qa_load.return_value = MagicMock()
        mock_oci_get.return_value = MagicMock()
        mock_get_litellm.return_value = {}

        mock_prompt_msg = MagicMock()
        mock_prompt_msg.content.text = "Judge prompt"
        mock_get_prompt.return_value = mock_prompt_msg

        mock_collect_answers.return_value = []
        mock_evaluate.side_effect = KeyError("correctness")

        with pytest.raises(HTTPException) as exc_info:
            await testbed.testbed_evaluate(
                tid="TS001",
                judge="gpt-4",
                client="test_client",
            )

        assert exc_info.value.status_code == 500
        assert "correctness" in str(exc_info.value.detail)
