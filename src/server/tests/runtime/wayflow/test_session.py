"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the FlowSession base class (shared by NL2SQL and VecSearch).
"""
# spell-checker: disable

import logging
from unittest.mock import AsyncMock, MagicMock

from server.app.api.v1.schemas.chat import TokenUsage, VsMetadata
from server.app.runtime.common import SessionMetadata
from server.app.runtime.wayflow.session import FlowSession
from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ as SAMPLE_CLIENT_SETTINGS
from server.tests.conftest import mock_flow as _mock_flow


def _failing_flow(error: Exception = RuntimeError("tool failed")) -> MagicMock:
    """Create a mock flow whose execute_async raises an exception."""
    flow = _mock_flow()
    flow.start_conversation.return_value.execute_async = AsyncMock(side_effect=error)
    return flow


class TestFlowSessionInit:
    """Unit tests for FlowSession initialization."""

    def test_model_derived_from_client_settings(self):
        """Verify model string is derived as provider/id from client_settings."""
        session = FlowSession(MagicMock(), SAMPLE_CLIENT_SETTINGS)
        assert session._model == "ollama/qwen3:8b"

    def test_history_starts_empty(self):
        """Verify history starts as empty string."""
        session = FlowSession(MagicMock(), SAMPLE_CLIENT_SETTINGS)
        assert session._history == ""


class TestFlowSessionExecute:
    """Unit tests for FlowSession execute and history accumulation."""

    async def test_execute_returns_answer(self):
        """Verify execute returns the flow's answer."""
        flow = _mock_flow("The answer is 42.")
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        result = await session.execute("What is X?", thread_id="t-123")
        assert result == "The answer is 42."

    async def test_execute_passes_base_inputs(self):
        """Verify execute passes query, thread_id, model, and chat_history."""
        flow = _mock_flow()
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        await session.execute("What is X?", thread_id="t-123")

        flow.start_conversation.assert_called_once_with(
            inputs={
                "query": "What is X?",
                "thread_id": "t-123",
                "model": "ollama/qwen3:8b",
                "chat_history": "",
            },
        )

    async def test_history_accumulates_across_calls(self):
        """Verify chat_history grows with each Q&A turn when use_history is True."""
        flow = _mock_flow("First answer")
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)

        await session.execute("First question", thread_id="t-1")
        first_inputs = flow.start_conversation.call_args[1]["inputs"]
        assert first_inputs["chat_history"] == ""

        second_status = MagicMock()
        second_status.output_values = {"answer": "Second answer"}
        flow.start_conversation.return_value.execute_async = AsyncMock(return_value=second_status)
        await session.execute("Follow-up", thread_id="t-1")
        second_inputs = flow.start_conversation.call_args[1]["inputs"]
        assert "First question" in second_inputs["chat_history"]
        assert "First answer" in second_inputs["chat_history"]

    async def test_execute_falls_back_when_answer_is_none(self):
        """When output_values has answer=None, fall back to last message."""
        from wayflowcore.executors.executionstatus import FinishedStatus

        flow = _mock_flow()
        status = MagicMock(spec=FinishedStatus)
        status.output_values = {"answer": None}
        conv = flow.start_conversation.return_value
        conv.execute_async = AsyncMock(return_value=status)
        conv.get_last_message.return_value = MagicMock(content="fallback text")

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        result = await session.execute("test", thread_id="t1")
        assert result == "fallback text"

    async def test_no_history_sent_when_disabled(self):
        """Verify chat_history input is empty when chat_history=False per-call."""
        flow = _mock_flow()
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)

        await session.execute("first question", thread_id="t-1", chat_history=False)
        await session.execute("second question", thread_id="t-1", chat_history=False)

        second_inputs = flow.start_conversation.call_args[1]["inputs"]
        assert second_inputs["chat_history"] == ""
        # Internal history still accumulates for when chat_history is re-enabled
        assert "first question" in session._history


class TestFlowSessionMetadata:
    """Tests for metadata extraction from FlowSession."""

    async def test_normalizes_vs_metadata_list_to_dict(self):
        """A raw list of documents is normalized to dict with 'documents' key."""
        from wayflowcore.executors.executionstatus import FinishedStatus

        flow = _mock_flow()
        status = FinishedStatus(
            output_values={
                "answer": "answer",
                "grade_relevant": "yes",
                "vs_metadata": '[{"page_content": "text"}]',
            }
        )
        conv = flow.start_conversation.return_value
        conv.execute_async = AsyncMock(return_value=status)

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        await session.execute("test", "t1")
        assert session.last_metadata.vs_metadata is not None
        assert session.last_metadata.vs_metadata.model_dump(exclude_none=True) == {
            "documents": [{"page_content": "text"}]
        }

    async def test_clears_documents_when_irrelevant(self):
        """Verify vs_metadata is preserved with empty documents when grade_relevant='no'."""
        import json

        from wayflowcore.executors.executionstatus import FinishedStatus

        flow = _mock_flow()
        full_response = json.dumps(
            {
                "documents": [{"page_content": "text"}],
                "searched_tables": ["TABLE_A"],
                "context_input": "What is X?",
            }
        )
        status = FinishedStatus(
            output_values={
                "answer": "answer",
                "grade_relevant": '{"relevant": "no", "formatted_documents": ""}',
                "vs_metadata": full_response,
            }
        )
        conv = flow.start_conversation.return_value
        conv.execute_async = AsyncMock(return_value=status)

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        await session.execute("test", "t1")
        assert session.last_metadata.vs_metadata is not None
        dumped = session.last_metadata.vs_metadata.model_dump(exclude_none=True)
        assert dumped["documents"] == []
        assert dumped["searched_tables"] == ["TABLE_A"]
        assert dumped["context_input"] == "What is X?"


class TestFlowSessionVsMetadataMerge:
    """Tests for parsing full VectorSearchResponse from vs_metadata."""

    async def test_parses_full_vector_search_response(self):
        """Verify searched_tables and context_input are parsed from full VectorSearchResponse JSON."""
        import json

        from wayflowcore.executors.executionstatus import FinishedStatus

        flow = _mock_flow()
        full_response = json.dumps(
            {
                "documents": [{"page_content": "text"}],
                "searched_tables": ["TABLE_A", "TABLE_B"],
                "context_input": "What is X?",
                "num_documents": 1,
                "status": "success",
            }
        )
        status = FinishedStatus(
            output_values={
                "answer": "answer",
                "grade_relevant": "yes",
                "vs_metadata": full_response,
            }
        )
        conv = flow.start_conversation.return_value
        conv.execute_async = AsyncMock(return_value=status)

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        await session.execute("test", "t1")
        assert session.last_metadata.vs_metadata is not None
        dumped = session.last_metadata.vs_metadata.model_dump(exclude_none=True)
        assert dumped["documents"] == [{"page_content": "text"}]
        assert dumped["searched_tables"] == ["TABLE_A", "TABLE_B"]
        assert dumped["context_input"] == "What is X?"


class TestFlowSessionContentBlockUnwrap:
    """Tests for parsing LangChain content-block wrapped vs_metadata."""

    async def test_parses_content_block_wrapped_response(self):
        """Verify content blocks are unwrapped to extract full VectorSearchResponse."""
        import json

        from wayflowcore.executors.executionstatus import FinishedStatus

        flow = _mock_flow()
        inner_json = json.dumps(
            {
                "documents": [{"page_content": "text"}],
                "searched_tables": ["TABLE_A"],
                "context_input": "What is X?",
                "num_documents": 1,
                "status": "success",
            }
        )
        content_blocks = json.dumps([{"type": "text", "text": inner_json, "id": "lc_test"}])
        status = FinishedStatus(
            output_values={
                "answer": "answer",
                "grade_relevant": "yes",
                "vs_metadata": content_blocks,
            }
        )
        conv = flow.start_conversation.return_value
        conv.execute_async = AsyncMock(return_value=status)

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        await session.execute("test", "t1")
        assert session.last_metadata.vs_metadata is not None
        dumped = session.last_metadata.vs_metadata.model_dump(exclude_none=True)
        assert dumped["documents"] == [{"page_content": "text"}]
        assert dumped["searched_tables"] == ["TABLE_A"]
        assert dumped["context_input"] == "What is X?"


class TestExtractTokenUsage:
    """Tests for FlowSession._extract_token_usage ordering."""

    def test_prefers_last_step_with_token_usage(self):
        """Verify _extract_token_usage returns the last step's usage, not the first."""
        flow = _mock_flow()

        early_llm = MagicMock()
        early_usage = MagicMock()
        early_usage.input_tokens = 50
        early_usage.output_tokens = 20
        early_llm.last_token_usage = early_usage

        late_llm = MagicMock()
        late_usage = MagicMock()
        late_usage.input_tokens = 100
        late_usage.output_tokens = 40
        late_llm.last_token_usage = late_usage

        early_step = MagicMock()
        early_step.llm = early_llm
        late_step = MagicMock()
        late_step.llm = late_llm

        flow.steps = {"generate_sql": early_step, "format_answer": late_step}

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        result = session._extract_token_usage()

        assert result is late_usage

    def test_skips_steps_without_usage(self):
        """Verify steps with no last_token_usage are skipped."""
        flow = _mock_flow()

        llm_with = MagicMock()
        usage = MagicMock()
        usage.input_tokens = 10
        llm_with.last_token_usage = usage

        llm_without = MagicMock()
        llm_without.last_token_usage = None

        step_with = MagicMock()
        step_with.llm = llm_with
        step_without = MagicMock()
        step_without.llm = llm_without

        # The step without usage is last in insertion order
        flow.steps = {"early": step_with, "late": step_without}

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        result = session._extract_token_usage()

        assert result is usage

    def test_returns_none_when_no_steps(self):
        """Verify returns None when flow has no steps attribute."""
        flow = _mock_flow()
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        assert session._extract_token_usage() is None

    def test_clear_resets_all_step_llm_usage(self):
        """Verify _clear_token_usage resets last_token_usage on every step LLM."""
        flow = _mock_flow()

        llm_a = MagicMock()
        llm_a.last_token_usage = MagicMock()
        llm_b = MagicMock()
        llm_b.last_token_usage = MagicMock()

        step_a = MagicMock()
        step_a.llm = llm_a
        step_b = MagicMock()
        step_b.llm = llm_b

        flow.steps = {"branch_a": step_a, "branch_b": step_b}

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        session._clear_token_usage()

        assert llm_a.last_token_usage is None
        assert llm_b.last_token_usage is None

    def test_stale_branch_not_returned_after_clear(self):
        """Verify a branch that didn't run this turn can't leak stale token_usage.

        Simulates: turn N ran branch_a (setting its usage), turn N+1 runs
        branch_b only.  After _clear_token_usage + branch_b execution,
        _extract_token_usage must return branch_b's usage, not branch_a's stale value.
        """
        flow = _mock_flow()

        stale_llm = MagicMock()
        stale_llm.last_token_usage = None  # cleared by _clear_token_usage
        fresh_llm = MagicMock()
        fresh_usage = MagicMock()
        fresh_usage.input_tokens = 80
        fresh_usage.output_tokens = 30
        fresh_llm.last_token_usage = fresh_usage

        stale_step = MagicMock()
        stale_step.llm = stale_llm
        fresh_step = MagicMock()
        fresh_step.llm = fresh_llm

        # stale_step is last in insertion order (worst case for reverse iteration)
        flow.steps = {"branch_b": fresh_step, "branch_a": stale_step}

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        result = session._extract_token_usage()

        assert result is fresh_usage

    def test_extract_finds_usage_in_subflow(self):
        """LLM with last_token_usage inside a FlowExecutionStep subflow is found."""
        from wayflowcore.steps import FlowExecutionStep

        flow = _mock_flow()

        # Top-level step has no usage
        top_step = MagicMock()
        top_step.llm = MagicMock()
        top_step.llm.last_token_usage = None

        # Subflow step has usage
        sub_llm = MagicMock()
        sub_usage = MagicMock()
        sub_usage.input_tokens = 200
        sub_usage.output_tokens = 80
        sub_llm.last_token_usage = sub_usage
        sub_step = MagicMock()
        sub_step.llm = sub_llm

        subflow = MagicMock()
        subflow.steps = {"format_answer": sub_step}

        flow_exec_step = MagicMock(spec=FlowExecutionStep)
        flow_exec_step.flow = subflow

        flow.steps = {"classifier": top_step, "vecsearch_subflow": flow_exec_step}

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        result = session._extract_token_usage()

        assert result is sub_usage

    def test_extract_prefers_top_level_over_subflow(self):
        """Top-level synthesize step is preferred over nested format_answer in 'both' branch."""
        from wayflowcore.steps import ParallelFlowExecutionStep

        flow = _mock_flow()

        # Nested format_answer inside parallel subflow has usage
        sub_llm = MagicMock()
        sub_usage = MagicMock()
        sub_usage.input_tokens = 50
        sub_usage.output_tokens = 20
        sub_llm.last_token_usage = sub_usage
        sub_step = MagicMock()
        sub_step.llm = sub_llm

        subflow = MagicMock()
        subflow.steps = {"format_answer": sub_step}

        parallel_step = MagicMock(spec=ParallelFlowExecutionStep)
        parallel_step.flows = [subflow]

        # Top-level synthesize step also has usage (ran after parallel)
        synth_llm = MagicMock()
        synth_usage = MagicMock()
        synth_usage.input_tokens = 200
        synth_usage.output_tokens = 80
        synth_llm.last_token_usage = synth_usage
        synth_step = MagicMock()
        synth_step.llm = synth_llm

        flow.steps = {
            "both_subflows": parallel_step,
            "synthesize": synth_step,
        }

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        result = session._extract_token_usage()

        assert result is synth_usage

    def test_clear_resets_subflow_llm_usage(self):
        """_clear_token_usage resets LLMs inside nested subflows."""
        from wayflowcore.steps import FlowExecutionStep

        flow = _mock_flow()

        top_llm = MagicMock()
        top_llm.last_token_usage = MagicMock()
        top_step = MagicMock()
        top_step.llm = top_llm

        sub_llm = MagicMock()
        sub_llm.last_token_usage = MagicMock()
        sub_step = MagicMock()
        sub_step.llm = sub_llm

        subflow = MagicMock()
        subflow.steps = {"format_answer": sub_step}

        flow_exec_step = MagicMock(spec=FlowExecutionStep)
        flow_exec_step.flow = subflow

        flow.steps = {"classifier": top_step, "vecsearch_subflow": flow_exec_step}

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        session._clear_token_usage()

        assert top_llm.last_token_usage is None
        assert sub_llm.last_token_usage is None

    async def test_total_tokens_uses_provider_value(self):
        """total_tokens should come from TokenUsage.total_tokens, not input+output."""
        flow = _mock_flow()

        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.total_tokens = 200  # provider reports higher (e.g. cached tokens)

        llm = MagicMock()
        llm.last_token_usage = None
        step = MagicMock()
        step.llm = llm
        flow.steps = {"answer": step}

        # Set usage as side effect so it appears after _clear_token_usage runs
        async def _set_usage():
            llm.last_token_usage = usage
            status = MagicMock()
            status.output_values = {"answer": "ok"}
            return status

        flow.start_conversation.return_value.execute_async = AsyncMock(side_effect=_set_usage)

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        await session.execute("q", thread_id="t1")

        assert session.last_metadata.token_usage is not None
        assert session.last_metadata.token_usage.model_dump() == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 200,
        }

    async def test_total_tokens_falls_back_to_sum(self):
        """When total_tokens is 0 (provider omitted it), fall back to input+output."""
        flow = _mock_flow()

        usage = MagicMock()
        usage.input_tokens = 100
        usage.output_tokens = 50
        usage.total_tokens = 0

        llm = MagicMock()
        llm.last_token_usage = None
        step = MagicMock()
        step.llm = llm
        flow.steps = {"answer": step}

        async def _set_usage():
            llm.last_token_usage = usage
            status = MagicMock()
            status.output_values = {"answer": "ok"}
            return status

        flow.start_conversation.return_value.execute_async = AsyncMock(side_effect=_set_usage)

        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)
        await session.execute("q", thread_id="t1")

        assert session.last_metadata.token_usage is not None
        assert session.last_metadata.token_usage.model_dump() == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }


class TestFlowSessionErrorHandling:
    """Tests for error handling in FlowSession.execute()."""

    async def test_execute_returns_error_on_failure(self):
        """A failing flow returns an error message instead of crashing."""
        session = FlowSession(_failing_flow(), SAMPLE_CLIENT_SETTINGS)
        result = await session.execute("boom", "t1")
        assert result == "An error occurred while processing your request."

    async def test_execute_clears_metadata_on_failure(self):
        """A failed turn must not retain metadata from the previous success."""
        flow = _mock_flow("good answer")
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)

        # First call succeeds and populates metadata
        await session.execute("first", "t1")
        session.last_metadata.vs_metadata = VsMetadata(documents=[{"page_content": "doc1"}])
        session.last_metadata.token_usage = TokenUsage(total_tokens=100)
        assert session.last_metadata != SessionMetadata()

        # Second call fails
        flow.start_conversation.return_value.execute_async = AsyncMock(side_effect=RuntimeError("MCP down"))
        await session.execute("bad", "t1")
        assert session.last_metadata == SessionMetadata()

    async def test_execute_does_not_corrupt_history_on_failure(self):
        """A failed turn must not be appended to chat_history."""
        flow = _mock_flow("good answer")
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)

        # First call succeeds
        await session.execute("first", "t1")
        assert "first" in session._history
        assert "good answer" in session._history

        # Second call fails
        flow.start_conversation.return_value.execute_async = AsyncMock(side_effect=RuntimeError("MCP down"))
        result = await session.execute("bad", "t1")
        assert result == "An error occurred while processing your request."
        assert "bad" not in session._history

    async def test_execute_recovers_after_failure(self):
        """A successful turn after a failed one works normally."""
        flow = _mock_flow("recovered")
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)

        # Fail first
        flow.start_conversation.return_value.execute_async = AsyncMock(side_effect=RuntimeError("transient"))
        await session.execute("fail", "t1")

        # Succeed next
        ok_status = MagicMock()
        ok_status.output_values = {"answer": "recovered"}
        flow.start_conversation.return_value.execute_async = AsyncMock(return_value=ok_status)
        result = await session.execute("ok", "t1")
        assert result == "recovered"

    async def test_execute_logs_error_on_failure(self, caplog):
        """Flow failure is logged at ERROR level."""
        session = FlowSession(_failing_flow(), SAMPLE_CLIENT_SETTINGS)
        with caplog.at_level(logging.ERROR, logger="server.app.runtime.wayflow.session"):
            await session.execute("boom", "t1")
        assert any("Flow execution failed" in r.message for r in caplog.records)
