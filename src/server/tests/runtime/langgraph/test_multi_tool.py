"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the LangGraph CombinedSession (hybrid Python-level routing).
"""
# spell-checker: disable

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from server.app.api.v1.schemas.chat import SqlMetadata
from server.app.runtime.common import SessionMetadata
from server.app.runtime.langgraph.multi_tool import CombinedSession
from server.app.runtime.langgraph.session import (
    GraphFlowSession,
    NL2SQLGraphSession,
)
from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ as SAMPLE_CLIENT_SETTINGS
from server.tests.constants import TEST_OLLAMA_MODEL_KEY
from server.tests.runtime.langgraph.helpers import mock_compiled_graph
from server.tests.runtime.multi_tool_base import (
    ClassificationBase,
    MetadataBase,
    RoutingBase,
    StreamingBase,
)
from server.tests.runtime.shared_helpers import mock_litellm_response

PATCH_PATH = "server.app.runtime.langgraph.multi_tool"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_combined_session(
    vs_answer: str = "doc answer",
    nl2sql_answer: str = "sql answer",
    classifier_model: str = TEST_OLLAMA_MODEL_KEY,
    api_key: str | None = None,
    api_base: str | None = None,
    model_kwargs: dict | None = None,
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

    kwargs: dict = {"api_key": api_key, "api_base": api_base}
    if model_kwargs is not None:
        kwargs["model_kwargs"] = model_kwargs
    return CombinedSession(
        vs_session,
        nl2sql_session,
        classifier_model,
        "Test system prompt",
        **kwargs,
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


class TestCombinedSessionCredentials:
    """Verify api_key / api_base reach the OracleChatLiteLLM that classify/synthesize construct."""

    @pytest.mark.anyio
    async def test_classify_constructs_llm_with_credentials(self):
        with patch(
            "server.app.runtime.langgraph.multi_tool.OracleChatLiteLLM",
        ) as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="vecsearch", usage_metadata=None))
            mock_llm_cls.return_value = mock_llm
            session = _make_combined_session(api_key="sk-test-123", api_base="https://my-llm.example.com")
            await session.classify("test query")
        assert mock_llm_cls.call_args.kwargs["api_key"] == "sk-test-123"
        assert mock_llm_cls.call_args.kwargs["api_base"] == "https://my-llm.example.com"

    @pytest.mark.anyio
    async def test_synthesize_constructs_llm_with_credentials(self):
        with patch(
            "server.app.runtime.langgraph.multi_tool.OracleChatLiteLLM",
        ) as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="synthesized", usage_metadata=None))
            mock_llm_cls.return_value = mock_llm
            session = _make_combined_session(api_key="sk-test-456", api_base="https://api.example.com")
            await session.synthesize("query", "vs answer", "sql answer")
        assert mock_llm_cls.call_args.kwargs["api_key"] == "sk-test-456"
        assert mock_llm_cls.call_args.kwargs["api_base"] == "https://api.example.com"

    @pytest.mark.anyio
    async def test_no_credentials_when_none(self):
        with patch(
            "server.app.runtime.langgraph.multi_tool.OracleChatLiteLLM",
        ) as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="vecsearch", usage_metadata=None))
            mock_llm_cls.return_value = mock_llm
            session = _make_combined_session()
            await session.classify("test query")
        assert mock_llm_cls.call_args.kwargs["api_key"] is None
        assert mock_llm_cls.call_args.kwargs["api_base"] is None

    @pytest.mark.anyio
    async def test_classify_forwards_model_kwargs_for_oci_auth(self):
        oci_kwargs = {
            "oci_user": "ocid1.user.oc1..u",
            "oci_fingerprint": "aa:bb:cc",
            "oci_tenancy": "ocid1.tenancy.oc1..t",
            "oci_compartment_id": "ocid1.compartment.oc1..c",
            "oci_key_file": "/etc/oci/key.pem",
        }
        with patch(
            "server.app.runtime.langgraph.multi_tool.OracleChatLiteLLM",
        ) as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="vecsearch", usage_metadata=None))
            mock_llm_cls.return_value = mock_llm
            session = _make_combined_session(
                classifier_model="oci/openai.gpt-oss-120b",
                model_kwargs=oci_kwargs,
            )
            await session.classify("test query")
        assert mock_llm_cls.call_args.kwargs.get("model_kwargs") == oci_kwargs

    @pytest.mark.anyio
    async def test_synthesize_forwards_model_kwargs_for_oci_auth(self):
        oci_kwargs = {
            "oci_user": "ocid1.user.oc1..u",
            "oci_fingerprint": "aa:bb:cc",
            "oci_tenancy": "ocid1.tenancy.oc1..t",
            "oci_compartment_id": "ocid1.compartment.oc1..c",
            "oci_key_file": "/etc/oci/key.pem",
        }
        with patch(
            "server.app.runtime.langgraph.multi_tool.OracleChatLiteLLM",
        ) as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="synthesized", usage_metadata=None))
            mock_llm_cls.return_value = mock_llm
            session = _make_combined_session(
                classifier_model="oci/openai.gpt-oss-120b",
                model_kwargs=oci_kwargs,
            )
            await session.synthesize("query", "vs answer", "sql answer")
        assert mock_llm_cls.call_args.kwargs.get("model_kwargs") == oci_kwargs


class TestCombinedSessionV1ContentBlocks:
    """LangChain v1 mode delivers AIMessage.content as typed blocks; classify/synthesize must extract text."""

    @pytest.mark.anyio
    async def test_classify_handles_v1_content_blocks(self):
        """Coercing list-content with ``str()`` produces a Python repr that won't match the route names."""
        with patch(
            "server.app.runtime.langgraph.multi_tool.OracleChatLiteLLM",
        ) as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(
                return_value=AIMessage(
                    content=[{"type": "text", "text": "vecsearch"}],
                    usage_metadata=None,
                ),
            )
            mock_llm_cls.return_value = mock_llm
            session = _make_combined_session()
            decision, _ = await session.classify("test query")
        assert decision == "vecsearch"

    @pytest.mark.anyio
    async def test_synthesize_handles_v1_content_blocks(self):
        with patch(
            "server.app.runtime.langgraph.multi_tool.OracleChatLiteLLM",
        ) as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(
                return_value=AIMessage(
                    content=[{"type": "text", "text": "synthesized answer"}],
                    usage_metadata=None,
                ),
            )
            mock_llm_cls.return_value = mock_llm
            session = _make_combined_session()
            answer, _ = await session.synthesize("q", "vs", "sql")
        assert answer == "synthesized answer"

    @pytest.mark.anyio
    async def test_classify_strips_thinking_block_prefix(self):
        """Reasoning-capable providers prepend ``{"type": "thinking", ...}`` blocks.

        Serializing those into the flattened reply pollutes the routing decision
        with JSON that won't match ``vecsearch | nl2sql | both`` and defaults to
        ``both``. Non-text blocks must be dropped when reading model output.
        """
        with patch(
            "server.app.runtime.langgraph.multi_tool.OracleChatLiteLLM",
        ) as mock_llm_cls:
            mock_llm = MagicMock()
            mock_llm.ainvoke = AsyncMock(
                return_value=AIMessage(
                    content=[
                        {"type": "thinking", "thinking": "User wants knowledge — vecsearch."},
                        {"type": "text", "text": "vecsearch"},
                    ],
                    usage_metadata=None,
                ),
            )
            mock_llm_cls.return_value = mock_llm
            session = _make_combined_session()
            decision, _ = await session.classify("test query")
        assert decision == "vecsearch"


class TestCombinedSessionStreaming(_LangGraphMixin, StreamingBase):
    """Tests for execute_streaming() routing and queue events."""


# ---------------------------------------------------------------------------
# Metadata tests (LangGraph-specific: uses mock_compiled_graph for vs_metadata)
# ---------------------------------------------------------------------------


class TestCombinedSessionMetadata(_LangGraphMixin, MetadataBase):
    """Tests for vs_metadata propagation."""

    @pytest.mark.anyio
    @patch("litellm.acompletion", new_callable=AsyncMock)
    async def test_both_route_preserves_sql_metadata(self, mock_acompletion):
        """Combined responses retain SQL details from the NL2SQL branch."""
        mock_acompletion.side_effect = [
            mock_litellm_response("both"),
            mock_litellm_response("synthesized answer"),
        ]
        session = _make_combined_session()
        original_chat = session.nl2sql_session.chat

        async def chat_with_sql_metadata(*args, **kwargs):
            answer = await original_chat(*args, **kwargs)
            session.nl2sql_session.last_metadata = SessionMetadata(
                sql_metadata=SqlMetadata(executed_sql=["SELECT 1 FROM dual"])
            )
            return answer

        session.nl2sql_session.chat = chat_with_sql_metadata

        await session.execute("Is redo log right?", thread_id="t-1")

        assert session.last_metadata.sql_metadata == SqlMetadata(executed_sql=["SELECT 1 FROM dual"])

    @pytest.mark.anyio
    @patch("litellm.acompletion", new_callable=AsyncMock)
    async def test_streaming_both_route_preserves_sql_metadata(self, mock_acompletion):
        """Streaming combined responses retain SQL details from the NL2SQL branch."""
        mock_acompletion.side_effect = [
            mock_litellm_response("both"),
            mock_litellm_response("synthesized answer"),
        ]
        session = _make_combined_session()
        original_chat = session.nl2sql_session.chat

        async def chat_with_sql_metadata(*args, **kwargs):
            answer = await original_chat(*args, **kwargs)
            session.nl2sql_session.last_metadata = SessionMetadata(
                sql_metadata=SqlMetadata(executed_sql=["SELECT 1 FROM dual"])
            )
            return answer

        session.nl2sql_session.chat = chat_with_sql_metadata
        queue: asyncio.Queue = asyncio.Queue()

        await session.execute_streaming(
            "Is redo log right?",
            "t-1",
            "",
            [],
            queue,
            stream_flow=AsyncMock(),
            stream_agent=AsyncMock(),
        )

        assert session.last_metadata.sql_metadata == SqlMetadata(executed_sql=["SELECT 1 FROM dual"])


# ---------------------------------------------------------------------------
# Grade-relevant suppression tests
# ---------------------------------------------------------------------------


class TestCombinedSessionGradeRelevant:
    """Tests for skipping synthesis and suppressing vs_metadata when grade_relevant='no'."""

    @pytest.mark.anyio
    @patch("litellm.acompletion", new_callable=AsyncMock)
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
    @patch("litellm.acompletion", new_callable=AsyncMock)
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
    @patch("litellm.acompletion", new_callable=AsyncMock)
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
    @patch("litellm.acompletion", new_callable=AsyncMock)
    async def test_nl2sql_route_token_usage(self, mock_acompletion):
        """Verify NL2SQL route populates token_usage from graph."""
        mock_acompletion.return_value = mock_litellm_response("nl2sql")
        session = _make_combined_session()
        await session.execute("How many tables?", thread_id="t-1")
        # Token usage is sourced from the UsageMetadataCallbackHandler attached to
        # the sub-session's ainvoke. Mock graphs don't fire on_llm_end so usage is None.
        assert session.last_metadata.token_usage is None

    @pytest.mark.anyio
    @patch("litellm.acompletion", new_callable=AsyncMock)
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
