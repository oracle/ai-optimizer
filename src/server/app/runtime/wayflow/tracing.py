"""
Console span exporter, span processor factory, and trace context manager.

Combines the dev-time ConsoleSpanExporter, the build_span_processors()
factory, and the maybe_trace() context manager so tracing configuration
lives in a single module.
"""
# spell-checker: ignore spanprocessor wayflow wayflowcore millis spanexporter

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, List, Optional, Sequence, cast

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from wayflowcore.tracing.opentelemetry import OtelSimpleSpanProcessor
from wayflowcore.tracing.spanexporter import SpanExporter
from wayflowcore.tracing.spanprocessor import SimpleSpanProcessor, SpanProcessor
from wayflowcore.tracing.trace import Trace

LOGGER = logging.getLogger(__name__)


class ConsoleSpanExporter(SpanExporter):
    """Logs each span as structured JSON via the standard logging module."""

    _TOP_LEVEL_KEYS = frozenset({"name", "span_type", "start_time", "end_time", "duration"})

    def export(
        self,
        spans: List[Any],
        mask_sensitive_information: bool = True,
    ) -> None:
        for span in spans:
            info = span.to_tracing_info(mask_sensitive_information=mask_sensitive_information)
            start = info.get("start_time")
            end = info.get("end_time")
            duration = info.get("duration")
            if duration is None and start is not None and end is not None:
                duration = end - start
            record = {
                "name": info.get("name"),
                "span_type": info.get("span_type"),
                "start_time": start,
                "end_time": end,
                "duration": duration,
                "attributes": {k: v for k, v in info.items() if k not in self._TOP_LEVEL_KEYS},
            }
            LOGGER.info(json.dumps(record, default=str))

    def startup(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        LOGGER.debug("Forcing flush; timeout: %i", timeout_millis)
        return True


def build_span_processors(
    console: bool = True,
    otel_endpoint: Optional[str] = None,
    mask_sensitive: bool = True,
) -> List[SpanProcessor]:
    """Build a list of span processors based on the requested exporters.

    Parameters
    ----------
    console:
        If True, include a ConsoleSpanExporter.
    otel_endpoint:
        If set, include an OTel OTLP exporter pointing at this endpoint.
    mask_sensitive:
        Whether to mask sensitive information in exported spans.
    """
    processors: List[SpanProcessor] = []

    if console:
        processors.append(
            SimpleSpanProcessor(
                span_exporter=ConsoleSpanExporter(),
                mask_sensitive_information=mask_sensitive,
            )
        )

    if otel_endpoint:
        processors.append(
            OtelSimpleSpanProcessor(
                span_exporter=OTLPSpanExporter(endpoint=otel_endpoint),
                mask_sensitive_information=mask_sensitive,
            )
        )

    return processors


@contextmanager
def maybe_trace(name: str, span_processors: Optional[Sequence[SpanProcessor]]):
    """Wrap body in a Trace if *span_processors* exist, otherwise no-op."""
    if span_processors:
        with Trace(
            name=name,
            span_processors=cast(List[SpanProcessor], span_processors),
            shutdown_on_exit=False,
        ):
            yield
    else:
        yield
