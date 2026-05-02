"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OpenTelemetry tracing setup for the server. Opt-in via OTEL_* environment variables;
returns silently when not configured or when the [otel] extra is not installed.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import os
import uuid
from typing import TYPE_CHECKING

from _version import __version__
from server.app.core.settings import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

LOGGER = logging.getLogger(__name__)

_INSTRUMENTORS = (
    ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
    ("opentelemetry.instrumentation.requests", "RequestsInstrumentor"),
)
_SUPPORTED_EXPORTERS = frozenset({"otlp", "console"})


def init_tracing(service_name: str = "ai-optimizer-server") -> None:
    """Configure global OpenTelemetry tracing.

    Activated when OTEL_EXPORTER_OTLP_ENDPOINT is set (default OTLP exporter)
    or when OTEL_TRACES_EXPORTER includes "console". Idempotent: a second call
    after a TracerProvider is installed is a no-op.
    """
    exporters = {e.strip() for e in os.getenv("OTEL_TRACES_EXPORTER", "otlp").split(",") if e.strip()}
    exporters &= _SUPPORTED_EXPORTERS
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    if "otlp" in exporters and not endpoint:
        exporters.discard("otlp")
    if not exporters:
        return

    if _tracing_active():
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import OTELResourceDetector, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
    except ImportError:
        return

    # Our values are defaults; OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES override.
    defaults = Resource(
        attributes={
            "service.name": service_name,
            "service.version": __version__,
            "deployment.environment": settings.env,
            "service.instance.id": os.getenv("HOSTNAME") or str(uuid.uuid4()),
        }
    )
    resource = defaults.merge(OTELResourceDetector().detect())
    provider = TracerProvider(resource=resource)
    attached: set[str] = set()

    if "otlp" in exporters:
        protocol = (
            os.getenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL")
            or os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL")
            or "grpc"
        ).lower()
        try:
            if protocol == "grpc":
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            else:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            attached.add("otlp")
        except ImportError:
            LOGGER.warning("OTLP %s exporter requested but not installed; skipping", protocol)

    if "console" in exporters:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        attached.add("console")

    if not attached:
        return

    trace.set_tracer_provider(provider)

    _instrument_libraries()
    LOGGER.info(
        "OTel tracing initialized: service=%s exporters=%s",
        resource.attributes.get("service.name", service_name),
        sorted(attached),
    )


def instrument_fastapi(app: "FastAPI") -> None:
    """No-op when tracing is not initialized."""
    if not _tracing_active():
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        return
    FastAPIInstrumentor.instrument_app(app)


def _tracing_active() -> bool:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError:
        return False
    return isinstance(trace.get_tracer_provider(), TracerProvider)


def _instrument_libraries() -> None:
    for module_name, class_name in _INSTRUMENTORS:
        with contextlib.suppress(ImportError):
            getattr(importlib.import_module(module_name), class_name)().instrument()
