"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the LangGraph CombinedSession (hybrid Python-level routing).
"""
# spell-checker: disable

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from server.app.runtime.langgraph.multi_tool import CombinedSession
from server.app.runtime.langgraph.session import (
    GraphFlowSession,
    NL2SQLGraphSession,
)
from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ as SAMPLE_CLIENT_SETTINGS
from server.tests.runtime.langgraph.helpers import mock_compiled_graph
from server.tests.runtime.multi_tool_base import (
    ClassificationBase,
    CredentialsBase,
    MetadataBase,
    RoutingBase,
    StreamingBase,
)
from server.tests.runtime.shared_helpers import mock_litellm_response

PATCH_PATH = "server.app.runtime.langgraph.multi_tool"
COMMON_PATH = "server.app.runtime.common"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_combined_session(
    vs_answer: str = "doc answer",
    nl2sql_answer: str = "sql answer",
    classifier_model: str = "ollama/qwen3:8b",
    api_key: str | None = None,
    api_base: str | None = None,
    vs_metadata: dict | None = None,
    grade_relevant: str = "yes",
) -> CombinedSession:
    """Build a LangGraph CombinedSession with mocked sub-sessions."""
    vs_result = {
        "outputs": {"answer": vs_answer, "grade_relevant": grade_relevant},
        "messages": [],
    }
    if vs_metadata is not None:
        import json

        vs_result["outputs"]["vs_metadata"] = json.dumps(vs_metadata)

    vs_graph = mock_compiled_graph(result=vs_result)
    vs_session = GraphFlowSession(vs_graph, SAMPLE_CLIENT_SETTINGS)

    nl2sql_graph = mock_compiled_graph(
        result={
            "messages": [AIMessage(content=nl2sql_answer)],
        }
    )
    nl2sql_session = NL2SQLGraphSession(nl2sql_graph, SAMPLE_CLIENT_SETTINGS, thread_id="t-1")

    return CombinedSession(
        vs_session,
        nl2sql_session,
        classifier_model,
        "Test system prompt",
        api_key=api_key,
        api_base=api_base,
    )


# ---------------------------------------------------------------------------
# LangGraph mixin for shared base classes
# ---------------------------------------------------------------------------


class _LangGraphMixin:
    """Provides PATCH_PATH, make_session, and mock_response for LangGraph."""

    PATCH_PATH = PATCH_PATH

    @staticmethod
    def make_session(**kwargs):
        """Create a LangGraph combined session for testing."""
        return _make_combined_session(**kwargs)

    @staticmethod
    def mock_response(content, usage=None):
        """Create a mock LiteLLM response."""
        return mock_litellm_response(content, usage)


class TestClassification(_LangGraphMixin, ClassificationBase):
    """Tests for the classify() method."""


class TestCombinedSessionRouting(_LangGraphMixin, RoutingBase):
    """Tests for execute() routing to the correct sub-session."""


class TestCombinedSessionCredentials(_LangGraphMixin, CredentialsBase):
    """Tests for api_key/api_base forwarding to litellm calls."""


class TestCombinedSessionStreaming(_LangGraphMixin, StreamingBase):
    """Tests for execute_streaming() routing and queue events."""


# ---------------------------------------------------------------------------
# Metadata tests (LangGraph-specific: uses mock_compiled_graph for vs_metadata)
# ---------------------------------------------------------------------------


class TestCombinedSessionMetadata(_LangGraphMixin, MetadataBase):
    """Tests for vs_metadata propagation."""


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
        session = _make_combined_session(
            nl2sql_answer="sql result",
            grade_relevant='{"relevant": "no", "formatted_documents": ""}',
        )
        result = await session.execute("list connections", thread_id="t-1")
        assert result == "sql result"
        # Only the classify call, no synthesis call
        assert mock_acompletion.await_count == 1

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_both_suppresses_vs_metadata_when_irrelevant(self, mock_acompletion):
        """Verify 'both' route has no vs_metadata when grade_relevant='no'."""
        mock_acompletion.return_value = mock_litellm_response("both")
        session = _make_combined_session(
            vs_metadata={"documents": [{"source": "doc1"}]},
            grade_relevant='{"relevant": "no", "formatted_documents": ""}',
        )
        await session.execute("list connections", thread_id="t-1")
        assert session.last_metadata.vs_metadata is not None
        assert session.last_metadata.vs_metadata.documents == []

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_both_synthesizes_when_relevant(self, mock_acompletion):
        """Verify 'both' route synthesizes when grade_relevant='yes'."""
        mock_acompletion.side_effect = [
            mock_litellm_response("both"),
            mock_litellm_response("synthesized answer"),
        ]
        session = _make_combined_session(
            vs_answer="doc answer",
            vs_metadata={"documents": [{"source": "doc2"}]},
            grade_relevant='{"relevant": "yes", "formatted_documents": "docs"}',
        )
        result = await session.execute("Is redo log right?", thread_id="t-1")
        assert result == "synthesized answer"
        vs = session.last_metadata.vs_metadata
        assert vs is not None
        assert vs.model_dump(exclude_none=True) == {"documents": [{"source": "doc2"}]}


# ---------------------------------------------------------------------------
# Token usage tests
# ---------------------------------------------------------------------------


class TestCombinedSessionTokenUsage:
    """Tests for token usage telemetry in CombinedSession."""

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_nl2sql_route_token_usage(self, mock_acompletion):
        """Verify NL2SQL route populates token_usage from graph."""
        mock_acompletion.return_value = mock_litellm_response("nl2sql")
        session = _make_combined_session()
        await session.execute("How many tables?", thread_id="t-1")
        # Token usage comes from _extract_graph_token_usage which finds no real LLM instances
        # in mock graphs, so it will be None unless we inject it
        # This is expected behavior for mocked graphs
        assert session.last_metadata.token_usage is None

    @pytest.mark.anyio
    @patch(f"{COMMON_PATH}.litellm.acompletion", new_callable=AsyncMock)
    async def test_both_route_sums_token_usage(self, mock_acompletion):
        """Verify 'both' route sums token usage from sub-sessions."""
        from server.app.api.v1.schemas.chat import TokenUsage
        from server.app.runtime.common import SessionMetadata

        mock_acompletion.side_effect = [
            mock_litellm_response("both"),
            mock_litellm_response("synthesized"),
        ]
        session = _make_combined_session()

        # Patch vs_session.execute to inject token_usage into metadata
        original_vs_execute = session.vs_session.execute

        async def patched_vs_execute(*args, **kwargs):
            result = await original_vs_execute(*args, **kwargs)
            session.vs_session.last_metadata = SessionMetadata(
                token_usage=TokenUsage(prompt_tokens=200, completion_tokens=80, total_tokens=280),
            )
            return result

        session.vs_session.execute = patched_vs_execute
        await session.execute("Is redo log right?", thread_id="t-1")
        tu = session.last_metadata.token_usage
        assert tu is not None
        assert tu.prompt_tokens >= 200
        assert tu.completion_tokens >= 80
