"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for tracing integration in FlowSession and AgentChatSession.
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

from wayflowcore.tracing.spanprocessor import SpanProcessor
from wayflowcore.tracing.trace import Trace

from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ as SAMPLE_CLIENT_SETTINGS
from server.tests.conftest import mock_agent_conv, mock_flow


class TestFlowSessionTracing:
    """Trace integration for FlowSession."""

    async def test_execute_with_span_processors_uses_trace(self):
        """Trace is created with correct args and used as a sync context manager."""
        from server.app.runtime.wayflow.session import FlowSession

        flow = mock_flow("traced answer")
        processors = [MagicMock(spec=SpanProcessor)]
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS, span_processors=processors)

        mock_trace = MagicMock(spec=Trace)
        mock_trace.__enter__ = MagicMock(return_value=mock_trace)
        mock_trace.__exit__ = MagicMock(return_value=False)

        with patch("server.app.runtime.wayflow.tracing.Trace", return_value=mock_trace) as trace_cls:
            result = await session.execute("q", "t1")

        trace_cls.assert_called_once_with(
            name="flow_execute",
            span_processors=processors,
            shutdown_on_exit=False,
        )
        mock_trace.__enter__.assert_called_once()
        mock_trace.__exit__.assert_called_once()
        assert result == "traced answer"

    async def test_execute_does_not_shutdown_processors(self):
        """Span processors must survive across multiple execute calls."""
        from server.app.runtime.wayflow.session import FlowSession

        flow = mock_flow("answer")
        processor = MagicMock(spec=SpanProcessor)
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS, span_processors=[processor])

        await session.execute("q1", "t1")
        await session.execute("q2", "t1")

        processor.shutdown.assert_not_called()

    async def test_execute_without_span_processors_no_trace(self):
        """No Trace is created when span_processors is not set."""
        from server.app.runtime.wayflow.session import FlowSession

        flow = mock_flow("plain answer")
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS)

        with patch("server.app.runtime.wayflow.tracing.Trace") as trace_cls:
            result = await session.execute("q", "t1")

        trace_cls.assert_not_called()
        assert result == "plain answer"

    async def test_execute_with_span_processors_handles_error(self):
        """Flow failure inside a Trace context returns error string, no crash."""
        from server.app.runtime.wayflow.session import FlowSession

        flow = mock_flow(execute_side_effect=RuntimeError("MCP timeout"))
        processors = [MagicMock(spec=SpanProcessor)]
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS, span_processors=processors)

        result = await session.execute("q", "t1")
        assert result == "An error occurred while processing your request."


class TestAgentChatSessionTracing:
    """Trace integration for AgentChatSession (stateful and stateless)."""

    async def test_chat_with_span_processors_uses_trace(self):
        """Trace is created with correct args for stateful chat."""
        from server.app.runtime.wayflow.llm_only import AgentChatSession

        agent, _ = mock_agent_conv(content="traced reply")
        processors = [MagicMock(spec=SpanProcessor)]
        session = AgentChatSession(agent, span_processors=processors)

        mock_trace = MagicMock(spec=Trace)
        mock_trace.__enter__ = MagicMock(return_value=mock_trace)
        mock_trace.__exit__ = MagicMock(return_value=False)

        with patch("server.app.runtime.wayflow.tracing.Trace", return_value=mock_trace) as trace_cls:
            result = await session.chat("hi", chat_history=True)

        trace_cls.assert_called_once_with(
            name="agent_chat",
            span_processors=processors,
            shutdown_on_exit=False,
        )
        assert result == "traced reply"

    async def test_chat_does_not_shutdown_processors(self):
        """Span processors must survive across multiple chat calls."""
        from server.app.runtime.wayflow.llm_only import AgentChatSession

        agent, _ = mock_agent_conv(content="reply")
        processor = MagicMock(spec=SpanProcessor)
        session = AgentChatSession(agent, span_processors=[processor])

        await session.chat("msg1", chat_history=True)
        await session.chat("msg2", chat_history=True)

        processor.shutdown.assert_not_called()

    async def test_chat_without_span_processors_no_trace(self):
        """No Trace is created when span_processors is not set."""
        from server.app.runtime.wayflow.llm_only import AgentChatSession

        agent, _ = mock_agent_conv(content="plain reply")
        session = AgentChatSession(agent)

        with patch("server.app.runtime.wayflow.tracing.Trace") as trace_cls:
            result = await session.chat("hi", chat_history=True)

        trace_cls.assert_not_called()
        assert result == "plain reply"

    async def test_stateless_chat_with_span_processors_uses_trace(self):
        """Trace is created for stateless chat turns too."""
        from server.app.runtime.wayflow.llm_only import AgentChatSession

        agent, _ = mock_agent_conv(content="stateless")
        processors = [MagicMock(spec=SpanProcessor)]
        session = AgentChatSession(agent, span_processors=processors)

        mock_trace = MagicMock(spec=Trace)
        mock_trace.__enter__ = MagicMock(return_value=mock_trace)
        mock_trace.__exit__ = MagicMock(return_value=False)

        with patch("server.app.runtime.wayflow.tracing.Trace", return_value=mock_trace) as trace_cls:
            result = await session.chat("hi", chat_history=False)

        trace_cls.assert_called_once()
        assert result == "stateless"
