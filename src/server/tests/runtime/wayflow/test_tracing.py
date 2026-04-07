"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for tracing: ConsoleSpanExporter, build_span_processors, and integration.
"""
# spell-checker: disable

import importlib
import json
import logging
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from wayflowcore.tracing.span import ToolExecutionSpan
from wayflowcore.tracing.spanprocessor import SimpleSpanProcessor

from server.app.runtime.wayflow.session import FlowSession
from server.app.runtime.wayflow.tracing import ConsoleSpanExporter, build_span_processors
from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ as SAMPLE_CLIENT_SETTINGS
from server.tests.runtime.wayflow.helpers import load_test_flow, ollama_available

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_span(info: dict) -> MagicMock:
    """Create a mock span whose to_tracing_info returns *info*."""
    span = MagicMock()
    span.to_tracing_info.return_value = info
    return span


def _make_real_span(
    name: str = "test_tool",
    start: int = 1000,
    end: int = 2000,
) -> ToolExecutionSpan:
    """Create a real ToolExecutionSpan with mocked tool/request."""
    mock_tool = MagicMock()
    mock_tool.name = name
    mock_tool.description = "a test tool"
    mock_request = MagicMock()
    span = ToolExecutionSpan(
        name=name,
        tool=mock_tool,
        tool_request=mock_request,
    )
    span.start_time = start
    span.end_time = end
    return span


# ---------------------------------------------------------------------------
# ConsoleSpanExporter
# ---------------------------------------------------------------------------


class TestConsoleSpanExporter:
    """Unit tests for the ConsoleSpanExporter using mock spans."""

    def test_export_logs_span_data(self, caplog):
        """Exported span data is logged as structured JSON with attributes."""
        exporter = ConsoleSpanExporter()
        info = {
            "name": "test_span",
            "span_type": "ToolExecutionSpan",
            "start_time": 1000,
            "end_time": 2000,
            "duration": 1000,
            "model": "qwen3:8b",
        }
        span = _make_span(info)

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            exporter.export([span])

        assert len(caplog.records) == 1
        record = json.loads(caplog.records[0].message)
        assert record["name"] == "test_span"
        assert record["span_type"] == "ToolExecutionSpan"
        assert record["duration"] == 1000
        assert record["attributes"]["model"] == "qwen3:8b"

    def test_export_computes_duration_when_missing(self, caplog):
        """Duration is computed from end_time - start_time when absent."""
        exporter = ConsoleSpanExporter()
        info = {
            "name": "no_duration",
            "start_time": 1000,
            "end_time": 3000,
        }
        span = _make_span(info)

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            exporter.export([span])

        record = json.loads(caplog.records[0].message)
        assert record["duration"] == 2000

    def test_export_duration_none_when_no_times(self, caplog):
        """Duration is None when start_time and end_time are both missing."""
        exporter = ConsoleSpanExporter()
        span = _make_span({"name": "no_times"})

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            exporter.export([span])

        record = json.loads(caplog.records[0].message)
        assert record["duration"] is None

    def test_export_passes_mask_flag_true(self):
        """mask_sensitive_information=True is forwarded to to_tracing_info."""
        exporter = ConsoleSpanExporter()
        span = _make_span({"name": "s"})

        exporter.export([span], mask_sensitive_information=True)
        span.to_tracing_info.assert_called_once_with(mask_sensitive_information=True)

    def test_export_passes_mask_flag_false(self):
        """mask_sensitive_information=False is forwarded to to_tracing_info."""
        exporter = ConsoleSpanExporter()
        span = _make_span({"name": "s"})

        exporter.export([span], mask_sensitive_information=False)
        span.to_tracing_info.assert_called_once_with(mask_sensitive_information=False)

    def test_startup_shutdown_force_flush_do_not_raise(self):
        """Lifecycle methods complete without raising."""
        exporter = ConsoleSpanExporter()
        exporter.startup()
        exporter.shutdown()
        assert exporter.force_flush() is True

    def test_export_multiple_spans(self, caplog):
        """Each span produces one log record."""
        exporter = ConsoleSpanExporter()
        spans = [_make_span({"name": f"span_{i}"}) for i in range(3)]

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            exporter.export(spans)

        assert len(caplog.records) == 3


class TestConsoleSpanExporterRealSpans:
    """Tests using real wayflowcore Span objects (not mocks)."""

    def test_export_real_tool_span(self, caplog):
        """ConsoleSpanExporter handles a real ToolExecutionSpan correctly."""
        exporter = ConsoleSpanExporter()
        span = _make_real_span("my_tool", start=1000, end=5000)

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            exporter.export([span])

        assert len(caplog.records) == 1
        record = json.loads(caplog.records[0].message)
        assert record["name"] == "my_tool"
        assert record["span_type"] == "ToolExecutionSpan"
        assert record["start_time"] == 1000
        assert record["end_time"] == 5000
        assert record["duration"] == 4000
        assert "tool.name" in record["attributes"]

    def test_real_span_json_serialises_all_types(self, caplog):
        """json.dumps(default=str) handles UUIDs, None, and lists from real spans."""
        exporter = ConsoleSpanExporter()
        span = _make_real_span()

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            exporter.export([span])

        raw = caplog.records[0].message
        record = json.loads(raw)
        assert isinstance(record["attributes"]["span_id"], str)
        assert isinstance(record["attributes"]["events"], list)

    def test_real_span_masking_flag_forwarded(self, caplog):
        """mask_sensitive_information is forwarded to real span's to_tracing_info."""
        exporter = ConsoleSpanExporter()
        span = _make_real_span()

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            exporter.export([span], mask_sensitive_information=False)

        # If we get here without error, the flag was accepted by the real span
        assert len(caplog.records) == 1


class TestProcessorPipeline:
    """Test the full SimpleSpanProcessor -> ConsoleSpanExporter pipeline."""

    def test_processor_on_end_exports_span(self, caplog):
        """A real span fed through SimpleSpanProcessor.on_end produces logged JSON."""
        exporter = ConsoleSpanExporter()
        processor = SimpleSpanProcessor(
            span_exporter=exporter,
            mask_sensitive_information=True,
        )
        processor.startup()

        span = _make_real_span("pipeline_tool", start=100, end=500)

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            processor.on_end(span)

        assert len(caplog.records) == 1
        record = json.loads(caplog.records[0].message)
        assert record["name"] == "pipeline_tool"
        assert record["span_type"] == "ToolExecutionSpan"
        assert record["duration"] == 400
        processor.shutdown()

    def test_processor_multiple_spans(self, caplog):
        """Multiple spans fed sequentially through a processor each produce a log."""
        exporter = ConsoleSpanExporter()
        processor = SimpleSpanProcessor(
            span_exporter=exporter,
            mask_sensitive_information=True,
        )
        processor.startup()

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            for i in range(3):
                span = _make_real_span(f"tool_{i}", start=i * 100, end=(i + 1) * 100)
                processor.on_end(span)

        assert len(caplog.records) == 3
        names = [json.loads(r.message)["name"] for r in caplog.records]
        assert names == ["tool_0", "tool_1", "tool_2"]
        processor.shutdown()


# ---------------------------------------------------------------------------
# build_span_processors
# ---------------------------------------------------------------------------


class TestBuildSpanProcessors:
    """Unit tests for the build_span_processors factory."""

    def test_console_true_returns_one_processor(self):
        """console=True produces exactly one SimpleSpanProcessor."""
        result = build_span_processors(console=True)
        assert len(result) == 1
        assert isinstance(result[0], SimpleSpanProcessor)

    def test_console_false_returns_empty(self):
        """console=False with no OTel endpoint returns an empty list."""
        result = build_span_processors(console=False)
        assert not result

    def test_console_processor_uses_console_exporter(self):
        """Console processor wraps a ConsoleSpanExporter."""
        result = build_span_processors(console=True)
        processor = cast(SimpleSpanProcessor, result[0])
        assert isinstance(processor.span_exporter, ConsoleSpanExporter)

    def test_otel_endpoint_with_mocked_imports(self):
        """OTel endpoint with mocked imports produces one processor."""
        mock_otlp_mod = MagicMock()

        # Must mock all opentelemetry submodules that wayflowcore touches
        otel_mocks = {}
        for mod in [
            "opentelemetry",
            "opentelemetry.sdk",
            "opentelemetry.sdk.resources",
            "opentelemetry.sdk.trace",
            "opentelemetry.sdk.trace.export",
            "opentelemetry.trace",
            "opentelemetry.exporter",
            "opentelemetry.exporter.otlp",
            "opentelemetry.exporter.otlp.proto",
            "opentelemetry.exporter.otlp.proto.grpc",
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        ]:
            otel_mocks[mod] = MagicMock()
        otel_mocks["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = mock_otlp_mod
        mock_otlp_mod.OTLPSpanExporter = MagicMock(return_value=MagicMock())

        # Also need to invalidate the cached wayflowcore.tracing.opentelemetry import
        import sys

        wf_otel_key = "wayflowcore.tracing.opentelemetry"
        wf_otel_sp_key = "wayflowcore.tracing.opentelemetry.spanprocessor"
        saved = {k: sys.modules.pop(k, None) for k in [wf_otel_key, wf_otel_sp_key]}

        try:
            with patch.dict("sys.modules", otel_mocks):
                # Force re-import of wayflowcore otel module and our config
                import wayflowcore.tracing.opentelemetry as wf_otel

                importlib.reload(wf_otel)

                import server.app.runtime.wayflow.tracing as tracing_mod

                importlib.reload(tracing_mod)

                result = tracing_mod.build_span_processors(console=False, otel_endpoint="http://localhost:4317")
                assert len(result) == 1
        finally:
            # Restore original modules
            for k, v in saved.items():
                if v is not None:
                    sys.modules[k] = v
                else:
                    sys.modules.pop(k, None)
            import server.app.runtime.wayflow.tracing as tracing_mod

            importlib.reload(tracing_mod)


_ENDPOINT = "http://localhost:4317"


class TestOtelSmoke:
    """Smoke tests using real OTel imports."""

    def test_returns_otel_processor(self):
        """build_span_processors returns an OtelSimpleSpanProcessor wrapping OTLPSpanExporter."""
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from wayflowcore.tracing.opentelemetry import OtelSimpleSpanProcessor

        result = build_span_processors(console=False, otel_endpoint=_ENDPOINT)
        processor = cast(OtelSimpleSpanProcessor, result[0])

        assert len(result) == 1
        assert isinstance(processor, OtelSimpleSpanProcessor)
        assert isinstance(processor.span_exporter, OTLPSpanExporter)

    def test_exporter_endpoint_wired(self):
        """OTLPSpanExporter receives the configured endpoint."""
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from wayflowcore.tracing.opentelemetry import OtelSimpleSpanProcessor

        result = build_span_processors(console=False, otel_endpoint=_ENDPOINT)
        processor = cast(OtelSimpleSpanProcessor, result[0])
        exporter = cast(OTLPSpanExporter, processor.span_exporter)
        assert exporter._endpoint == "localhost:4317"

    def test_shutdown_propagates_without_error(self):
        """shutdown() propagates through the full processor-exporter chain without raising."""
        result = build_span_processors(console=True, otel_endpoint=_ENDPOINT)
        for processor in result:
            processor.shutdown()

    def test_console_and_otel_together(self):
        """console=True with otel_endpoint returns both processor types."""
        from wayflowcore.tracing.opentelemetry import OtelSimpleSpanProcessor

        result = build_span_processors(console=True, otel_endpoint=_ENDPOINT)

        assert len(result) == 2
        assert isinstance(result[0], SimpleSpanProcessor)
        assert isinstance(result[1], OtelSimpleSpanProcessor)

    def test_otel_processor_on_end_with_real_span(self):
        """OtelSimpleSpanProcessor.on_end accepts a real span without error."""
        from wayflowcore.tracing.opentelemetry import OtelSimpleSpanProcessor

        result = build_span_processors(console=False, otel_endpoint=_ENDPOINT)
        processor = cast(OtelSimpleSpanProcessor, result[0])
        processor.startup()

        mock_tool = MagicMock()
        mock_tool.name = "otel_test_tool"
        mock_tool.description = "test"
        span = ToolExecutionSpan(name="otel_test", tool=mock_tool, tool_request=MagicMock())
        span.start_time = 100
        span.end_time = 200

        # on_end should not raise even without a running collector
        processor.on_end(span)
        processor.shutdown()

    def test_recording_exporter_receives_real_span(self):
        """A custom SpanExporter used with OtelSimpleSpanProcessor receives span data."""
        from opentelemetry.sdk.trace.export import SpanExporter as OtelSpanExporter
        from opentelemetry.sdk.trace.export import SpanExportResult
        from wayflowcore.tracing.opentelemetry import OtelSimpleSpanProcessor

        class RecordingExporter(OtelSpanExporter):
            """Captures exported spans for assertion."""

            def __init__(self):
                self.captured = []

            def export(self, spans):
                self.captured.extend(spans)
                return SpanExportResult.SUCCESS

            def shutdown(self):
                pass

            def force_flush(self, timeout_millis=30000):
                return True

        recorder = RecordingExporter()
        processor = OtelSimpleSpanProcessor(span_exporter=recorder, mask_sensitive_information=True)
        processor.startup()

        mock_tool = MagicMock()
        mock_tool.name = "recorded_tool"
        mock_tool.description = "test"
        span = ToolExecutionSpan(name="record_test", tool=mock_tool, tool_request=MagicMock())
        span.start_time = 100
        span.end_time = 300

        processor.on_end(span)

        assert len(recorder.captured) == 1
        # OtelSimpleSpanProcessor converts to OTel _Span objects
        otel_span = recorder.captured[0]
        assert otel_span.name == "record_test"
        assert otel_span.start_time is not None
        assert otel_span.end_time is not None
        processor.shutdown()


# ---------------------------------------------------------------------------
# Integration (requires ollama)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not ollama_available(), reason="ollama not running at 127.0.0.1:11434")
class TestTracingIntegration:
    """End-to-end tracing tests with real WayFlow execution."""

    async def test_flow_session_emits_spans_to_console_exporter(self, caplog):
        """FlowSession with ConsoleSpanExporter logs at least one span as JSON."""
        flow = load_test_flow(llm_node_name="answer_question")
        processors = build_span_processors(console=True)
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS, span_processors=processors)

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            await session.execute("What is 2+2?", "test-thread")

        span_records = [r for r in caplog.records if r.name == "server.app.runtime.wayflow.tracing"]
        assert len(span_records) >= 1, "Expected at least one span logged"

        record = json.loads(span_records[0].message)
        assert "name" in record
        assert "span_type" in record
        assert "start_time" in record
        assert "end_time" in record
        assert record["duration"] is not None

        # Verify we got diverse span types from the flow execution
        span_types = {json.loads(r.message)["span_type"] for r in span_records}
        assert "StepInvocationSpan" in span_types
        assert "FlowExecutionSpan" in span_types

    async def test_multi_turn_tracing_no_processor_shutdown(self, caplog):
        """Span processors survive across multiple execute calls."""
        flow = load_test_flow(llm_node_name="answer_question")
        processors = build_span_processors(console=True)
        session = FlowSession(flow, SAMPLE_CLIENT_SETTINGS, span_processors=processors)

        with caplog.at_level(logging.INFO, logger="server.app.runtime.wayflow.tracing"):
            await session.execute("Say hello", "test-thread")
            caplog.clear()
            await session.execute("Say goodbye", "test-thread")

        span_records = [r for r in caplog.records if r.name == "server.app.runtime.wayflow.tracing"]
        assert len(span_records) >= 1, "Second turn should still emit spans"
