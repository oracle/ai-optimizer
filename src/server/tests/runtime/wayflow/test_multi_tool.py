"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the Combined session (hybrid Python-level routing).
"""
# spell-checker: disable

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from wayflowcore.executors.executionstatus import FinishedStatus

from server.app.runtime.wayflow.multi_tool import CombinedSession
from server.app.runtime.wayflow.nl2sql import NL2SQLAgentSession
from server.app.runtime.wayflow.session import FlowSession
from server.tests.conftest import (
    SAMPLE_CLIENT_SETTINGS_OBJ as SAMPLE_CLIENT_SETTINGS,
)
from server.tests.conftest import (
    mock_agent_conv,
    mock_flow,
)
from server.tests.runtime.multi_tool_base import (
    ClassificationBase,
    CredentialsBase,
    MetadataBase,
    RoutingBase,
    StreamingBase,
)
from server.tests.runtime.shared_helpers import mock_litellm_response

PATCH_PATH = "server.app.runtime.wayflow.multi_tool"
COMMON_PATH = "server.app.runtime.common"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_flow_with_metadata(
    content: str = "answer",
    vs_metadata: str = "",
    grade_relevant: str = "yes",
) -> MagicMock:
    """Create a mock flow whose status is a real FinishedStatus (for vs_metadata extraction)."""
    flow = mock_flow(content)
    output_values = {"answer": content}
    if vs_metadata:
        output_values["vs_metadata"] = vs_metadata
    output_values["grade_relevant"] = grade_relevant
    status = FinishedStatus(output_values=output_values)
    conv = flow.start_conversation.return_value
    conv.execute_async = AsyncMock(return_value=status)
    return flow


def _make_combined_session(
    vs_answer: str = "doc answer",
    nl2sql_answer: str = "sql answer",
    classifier_model: str = "ollama/qwen3:8b",
    nl2sql_token_usage: bool = False,
    api_key: str | None = None,
    api_base: str | None = None,
    **_kwargs,
) -> CombinedSession:
    """Build a CombinedSession with mocked sub-sessions.

    Parameters
    ----------
    nl2sql_token_usage:
        If True, set realistic token_usage on the NL2SQL conversation mock.
    api_key:
        Optional API key to pass to CombinedSession.
    api_base:
        Optional API base URL to pass to CombinedSession.
    """
    vs_flow = mock_flow(vs_answer)
    vs_session = FlowSession(vs_flow, SAMPLE_CLIENT_SETTINGS)

    agent, conv = mock_agent_conv(nl2sql_answer)
    # NL2SQLAgentSession.__init__ reads/writes custom_instruction
    agent.custom_instruction = ""
    agent._update_internal_state = MagicMock()
    if nl2sql_token_usage:
        tu = MagicMock()
        tu.input_tokens = 100
        tu.output_tokens = 50
        tu.total_tokens = 150
        conv.token_usage = tu
    else:
        conv.token_usage = None
    nl2sql_session = NL2SQLAgentSession(agent, SAMPLE_CLIENT_SETTINGS, thread_id="t-1")

    return CombinedSession(
        vs_session,
        nl2sql_session,
        classifier_model,
        "Test system prompt",
        api_key=api_key,
        api_base=api_base,
    )


# ---------------------------------------------------------------------------
# WayFlow mixin for shared base classes
# ---------------------------------------------------------------------------


class _WayFlowMixin:
    """Provides PATCH_PATH, make_session, and mock_response for WayFlow."""

    PATCH_PATH = PATCH_PATH

    @staticmethod
    def make_session(**kwargs):
        """Create a WayFlow combined session for testing."""
        return _make_combined_session(**kwargs)

    @staticmethod
    def mock_response(content, usage=None):
        """Create a mock LiteLLM response."""
        return mock_litellm_response(content, usage)


class TestClassification(_WayFlowMixin, ClassificationBase):
    """Tests for the classify() method."""


class TestCombinedSessionRouting(_WayFlowMixin, RoutingBase):
    """Tests for execute() routing to the correct sub-session."""


class TestCombinedSessionCredentials(_WayFlowMixin, CredentialsBase):
    """Tests for api_key/api_base forwarding to litellm calls."""


class TestCombinedSessionStreaming(_WayFlowMixin, StreamingBase):
    """Tests for execute_streaming() routing and queue events."""

    def make_session_irrelevant(self):
        """WayFlow needs _mock_flow_with_metadata for grade_relevant support."""
        session = _make_combined_session(nl2sql_answer="sql result")
        session.vs_session.flow = _mock_flow_with_metadata(
            "doc answer",
            grade_relevant='{"relevant": "no", "formatted_documents": ""}',
        )
        return session


# ---------------------------------------------------------------------------
# Metadata tests (WayFlow-specific: uses _mock_flow_with_metadata)
# ---------------------------------------------------------------------------


class TestCombinedSessionMetadata(_WayFlowMixin, MetadataBase):
    """Tests for vs_metadata propagation."""

    def make_vs_metadata_session(self, documents):
        """WayFlow uses _mock_flow_with_metadata for vs_metadata setup."""
        import json

        session = _make_combined_session()
        session.vs_session.flow = _mock_flow_with_metadata(
            "doc answer",
            vs_metadata=json.dumps({"documents": documents}),
        )
        return session


# ---------------------------------------------------------------------------
# Grade-relevant suppression tests
# ---------------------------------------------------------------------------


class TestCombinedSessionGradeRelevant:
    """Tests for skipping synthesis and suppressing vs_metadata when grade_relevant='no'."""

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_both_skips_synthesis_when_irrelevant(self, mock_acompletion):
        """Verify 'both' route returns only nl2sql answer when grade_relevant='no'."""
        mock_acompletion.return_value = mock_litellm_response("both")
        session = _make_combined_session(nl2sql_answer="sql result")
        # grade_relevant="no" via VectorGradeResponse JSON
        session.vs_session.flow = _mock_flow_with_metadata(
            "doc answer",
            vs_metadata='{"documents": [{"source": "doc1"}]}',
            grade_relevant='{"relevant": "no", "formatted_documents": "", "grading_performed": true}',
        )
        result = await session.execute("list connections", thread_id="t-1")
        assert result == "sql result"
        # Only the classify call, no synthesis call
        assert mock_acompletion.await_count == 1

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_both_suppresses_vs_metadata_when_irrelevant(self, mock_acompletion):
        """Verify 'both' route has empty metadata when grade_relevant='no'."""
        mock_acompletion.return_value = mock_litellm_response("both")
        session = _make_combined_session()
        session.vs_session.flow = _mock_flow_with_metadata(
            "doc answer",
            vs_metadata='{"documents": [{"source": "doc1"}]}',
            grade_relevant='{"relevant": "no", "formatted_documents": ""}',
        )
        await session.execute("list connections", thread_id="t-1")
        assert session.last_metadata.vs_metadata is not None
        assert session.last_metadata.vs_metadata.documents == []

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_both_preserves_grade_relevant_when_irrelevant(self, mock_acompletion):
        """Verify grade_relevant is in last_metadata even when vecsearch was skipped."""
        mock_acompletion.return_value = mock_litellm_response("both")
        session = _make_combined_session()
        grade_json = '{"relevant": "no", "formatted_documents": ""}'
        session.vs_session.flow = _mock_flow_with_metadata(
            "doc answer",
            grade_relevant=grade_json,
        )
        await session.execute("list connections", thread_id="t-1")
        assert session.last_metadata.grade_relevant == "no"

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_both_synthesizes_when_relevant(self, mock_acompletion):
        """Verify 'both' route synthesizes and propagates vs_metadata when grade_relevant='yes'."""
        mock_acompletion.side_effect = [
            mock_litellm_response("both"),
            mock_litellm_response("synthesized answer"),
        ]
        session = _make_combined_session()
        session.vs_session.flow = _mock_flow_with_metadata(
            "doc answer",
            vs_metadata='{"documents": [{"source": "doc2"}]}',
            grade_relevant='{"relevant": "yes", "formatted_documents": "docs"}',
        )
        result = await session.execute("Is redo log right?", thread_id="t-1")
        assert result == "synthesized answer"
        vs = session.last_metadata.vs_metadata
        assert vs is not None
        assert vs.model_dump(exclude_none=True) == {"documents": [{"source": "doc2"}]}

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_vecsearch_suppresses_vs_metadata_when_irrelevant(self, mock_acompletion):
        """Verify standalone vecsearch suppresses vs_metadata when grade_relevant='no'."""
        mock_acompletion.return_value = mock_litellm_response("vecsearch")
        session = _make_combined_session()
        session.vs_session.flow = _mock_flow_with_metadata(
            "no relevant info",
            vs_metadata='{"documents": [{"source": "doc1"}]}',
            grade_relevant='{"relevant": "no", "formatted_documents": ""}',
        )
        await session.execute("irrelevant question", thread_id="t-1")
        assert session.last_metadata.vs_metadata is not None
        assert session.last_metadata.vs_metadata.documents == []


# ---------------------------------------------------------------------------
# Token usage tests
# ---------------------------------------------------------------------------


class TestCombinedSessionTokenUsage:
    """Tests for token usage telemetry in CombinedSession."""

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_nl2sql_route_extracts_token_usage(self, mock_acompletion):
        """Verify NL2SQL route populates last_metadata.token_usage."""
        mock_acompletion.return_value = mock_litellm_response("nl2sql")
        session = _make_combined_session(nl2sql_token_usage=True)
        await session.execute("How many tables?", thread_id="t-1")
        tu = session.last_metadata.token_usage
        assert tu is not None
        assert tu.prompt_tokens == 100
        assert tu.completion_tokens == 50
        assert tu.total_tokens == 150

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_nl2sql_route_no_token_usage_when_none(self, mock_acompletion):
        """Verify NL2SQL route has no token_usage when conversation has none."""
        mock_acompletion.return_value = mock_litellm_response("nl2sql")
        session = _make_combined_session(nl2sql_token_usage=False)
        await session.execute("How many tables?", thread_id="t-1")
        assert session.last_metadata.token_usage is None

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_both_route_merges_token_usage(self, mock_acompletion):
        """Verify 'both' route sums token usage from both sub-sessions."""
        from server.app.api.v1.schemas.chat import TokenUsage
        from server.app.runtime.common import SessionMetadata as _SessionMetadata

        mock_acompletion.side_effect = [
            mock_litellm_response("both"),
            mock_litellm_response("synthesized"),
        ]
        session = _make_combined_session(nl2sql_token_usage=True)
        # Set up vs_session with token_usage in its flow metadata
        session.vs_session.flow = _mock_flow_with_metadata(
            "doc answer", vs_metadata='{"documents": [{"source": "doc1"}]}'
        )
        # Manually inject token_usage that FlowSession._extract_token_usage would find
        # (mock flow won't have real LLM steps, so we patch last_metadata after execute)
        original_execute = session.vs_session.execute

        async def patched_execute(*args, **kwargs):
            result = await original_execute(*args, **kwargs)
            session.vs_session.last_metadata = _SessionMetadata(
                token_usage=TokenUsage(prompt_tokens=200, completion_tokens=80, total_tokens=280),
            )
            return result

        session.vs_session.execute = patched_execute
        await session.execute("Is redo log right?", thread_id="t-1")
        tu = session.last_metadata.token_usage
        assert tu is not None
        assert tu.prompt_tokens == 300  # 200 + 100
        assert tu.completion_tokens == 130  # 80 + 50
        assert tu.total_tokens == 430  # 280 + 150
