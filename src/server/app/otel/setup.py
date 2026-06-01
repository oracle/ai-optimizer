"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OpenTelemetry tracing and log-export setup for the server. Opt-in via OTEL_*
environment variables; returns silently when not configured or when the [otel]
extra is not installed.
"""
# spell-checker: ignore instrumentors instrumentor openinference millis

from __future__ import annotations

import contextlib
import importlib
import logging
import os
import uuid
from typing import TYPE_CHECKING

from _version import __version__
from logging_redaction import RedactingFilter
from server.app.core.settings import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

    # Aliased because ``Resource`` at module scope is bound to either the SDK
    # class or ``None`` depending on whether the [otel] extra is installed;
    # ``ResourceType`` keeps annotations referring to the class unambiguously.
    from opentelemetry.sdk.resources import Resource as ResourceType

LOGGER = logging.getLogger(__name__)

# Optional [otel] extra. Each block isolates one class of functionality so a
# partial install (e.g. trace SDK present, logs SDK absent) still degrades
# gracefully. Functions below check the module-level sentinels (``is None``)
# and exit early when absent.
#
# Pyright treats imports inside ``try/except ImportError`` as conditional, so
# reportMissingImports stays clean without the [otel] extra installed.
#
# Modules with patchable symbols (set_logger_provider, LoggingInstrumentor,
# LangChainInstrumentor) are imported as modules — not as direct symbols — so
# monkeypatch.setattr at the upstream path is honored at call time.
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import OTELResourceDetector, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )
except ImportError:
    trace = None
    OTELResourceDetector = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
    ConsoleSpanExporter = None
    SimpleSpanProcessor = None

try:
    from opentelemetry import _logs as _otel_logs
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
except ImportError:
    _otel_logs = None
    LoggerProvider = None
    LoggingHandler = None
    BatchLogRecordProcessor = None

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
except ImportError:
    FastAPIInstrumentor = None

try:
    from opentelemetry.instrumentation import logging as _otel_logging_instr
except ImportError:
    _otel_logging_instr = None

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as _GrpcSpanExporter
except ImportError:
    _GrpcSpanExporter = None

try:
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter as _GrpcLogExporter
except ImportError:
    _GrpcLogExporter = None

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as _HttpSpanExporter
except ImportError:
    _HttpSpanExporter = None

try:
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as _HttpLogExporter
except ImportError:
    _HttpLogExporter = None

try:
    from openinference.instrumentation import TraceConfig
    from openinference.instrumentation import langchain as _oi_langchain
    from openinference.instrumentation.config import REDACTED_VALUE
except ImportError:
    TraceConfig = None
    _oi_langchain = None
    REDACTED_VALUE = None

_INSTRUMENTORS = (
    ("opentelemetry.instrumentation.httpx", "HTTPXClientInstrumentor"),
    ("opentelemetry.instrumentation.requests", "RequestsInstrumentor"),
)
_SUPPORTED_EXPORTERS = frozenset({"otlp", "console"})


def init_telemetry(service_name: str = "ai-optimizer-server") -> None:
    """Configure global OpenTelemetry tracing and log export.

    Tracing activates when OTEL_EXPORTER_OTLP_ENDPOINT is set or when
    OTEL_TRACES_EXPORTER includes "console". Logs are additionally exported via
    OTLP whenever the OTLP trace exporter is active and OTEL_LOGS_EXPORTER is
    not "none". Idempotent: a second call after a TracerProvider is installed
    is a no-op.
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

    if (
        trace is None
        or TracerProvider is None
        or Resource is None
        or OTELResourceDetector is None
        or BatchSpanProcessor is None
        or SimpleSpanProcessor is None
        or ConsoleSpanExporter is None
    ):
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
        protocol = _otlp_protocol("TRACES")
        span_exporter_cls = _GrpcSpanExporter if protocol == "grpc" else _HttpSpanExporter
        if span_exporter_cls is None:
            LOGGER.warning("OTLP %s exporter requested but not installed; skipping", protocol)
        else:
            provider.add_span_processor(BatchSpanProcessor(span_exporter_cls()))
            attached.add("otlp")

    if "console" in exporters:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        attached.add("console")

    if not attached:
        return

    trace.set_tracer_provider(provider)

    if "otlp" in attached:
        _init_logs(resource)

    _instrument_libraries()
    LOGGER.info(
        "OTel telemetry initialized: service=%s exporters=%s",
        resource.attributes.get("service.name", service_name),
        sorted(attached),
    )


def instrument_fastapi(app: "FastAPI") -> None:
    """No-op when tracing is not initialized."""
    if not _tracing_active():
        return
    if FastAPIInstrumentor is None:
        return
    FastAPIInstrumentor.instrument_app(app)


def _tracing_active() -> bool:
    if trace is None or TracerProvider is None:
        return False
    return isinstance(trace.get_tracer_provider(), TracerProvider)


def _init_logs(resource: "ResourceType") -> None:
    """Wire OTLP log export and attach an OTel handler to root + propagate=False loggers."""
    # Log export is a separate opt-in from tracing because application logs can
    # include request content. Operators choose the backend and retention
    # settings before enabling this path.
    if not _env_bool("AIO_OTEL_LOGS_ENABLED", default=False):
        return

    # OTEL_LOGS_EXPORTER is comma-separated per the OTel spec. Only ship over
    # OTLP when the operator's exporter list actually includes "otlp"; "none"
    # is the explicit disable sentinel. console-only or unsupported values
    # leave OTLP wiring untouched so log content is not exported against
    # operator intent.
    log_exporters_raw = os.getenv("OTEL_LOGS_EXPORTER")
    log_exporters = (
        {e.strip().lower() for e in log_exporters_raw.split(",") if e.strip()} if log_exporters_raw else {"otlp"}
    )
    if "none" in log_exporters or "otlp" not in log_exporters:
        return

    # OTLPLogExporter() reads OTEL_EXPORTER_OTLP_LOGS_ENDPOINT then falls back
    # to OTEL_EXPORTER_OTLP_ENDPOINT. If neither is set (operator configured
    # only OTEL_EXPORTER_OTLP_TRACES_ENDPOINT), the SDK would default to
    # localhost:4317 silently. Skip log export instead.
    if not (os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")):
        LOGGER.info("OTLP log export skipped: no logs/generic endpoint configured")
        return

    if (
        _otel_logs is None
        or LoggerProvider is None
        or LoggingHandler is None
        or BatchLogRecordProcessor is None
    ):
        return

    protocol = _otlp_protocol("LOGS")
    log_exporter_cls = _GrpcLogExporter if protocol == "grpc" else _HttpLogExporter
    if log_exporter_cls is None:
        LOGGER.warning("OTLP %s log exporter requested but not installed; skipping", protocol)
        return

    provider = LoggerProvider(resource=resource)
    # Order matters: the SDK invokes processors in registration order, so this
    # processor must prepare body/exception attributes before batching.
    # RedactingFilter on the handler mutates record.msg/args; LoggingHandler
    # then writes record.exc_info into separate SDK-side exception attributes.
    # This processor applies the same treatment to those attributes.
    # The processor is structurally compatible with LogRecordProcessor; not a
    # subclass so its definition stays free of the optional [otel] base class.
    provider.add_log_record_processor(_RedactingLogProcessor())  # type: ignore[arg-type]
    provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter_cls()))
    _otel_logs.set_logger_provider(provider)

    # Project's logging_config sets propagate=False on uvicorn, streamlit, etc.,
    # so root-only attachment would silently miss them. Attach to every named
    # logger that owns its own handlers and isn't propagating to root.
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=provider)
    # Exclude records from the OTel SDK and the HTTP/gRPC transport libraries
    # used by the exporter, so exporter activity is not reprocessed here.
    handler.addFilter(_NotExporterDependency())
    # Apply the project's field-value normalization directly on the OTel
    # handler. Some propagate=False logger chains do not include the project
    # filter, so attach it here for consistent exported records.
    handler.addFilter(RedactingFilter())
    logging.getLogger().addHandler(handler)
    for name in list(logging.root.manager.loggerDict):
        named = logging.getLogger(name)
        if named.handlers and not named.propagate:
            named.addHandler(handler)


class _NotExporterDependency(logging.Filter):
    """Drop records from exporter-related libraries handled elsewhere."""

    _PREFIXES = ("opentelemetry", "urllib3", "requests", "httpx", "httpcore", "grpc")

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(self._PREFIXES)


class _RedactingLogProcessor:
    """LogRecordProcessor that normalizes configured fields on SDK log records.

    Standalone class (not a subclass of LogRecordProcessor) so the optional
    [otel] import is contained inside _init_logs; subclassing at module scope
    would require importing LogRecordProcessor at module load.
    """

    _EXCEPTION_KEYS = ("exception.message", "exception.stacktrace")

    def __init__(self) -> None:
        self._filter = RedactingFilter()

    def on_emit(self, log_record) -> None:  # type: ignore[no-untyped-def]
        record = log_record.log_record
        attrs = record.attributes
        if attrs:
            for key in self._EXCEPTION_KEYS:
                value = attrs.get(key)
                if isinstance(value, str):
                    attrs[key] = self._filter.scrub(value)
        if isinstance(record.body, str):
            record.body = self._filter.scrub(record.body)

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # noqa: ARG002
        return True


def _instrument_libraries() -> None:
    for module_name, class_name in _INSTRUMENTORS:
        with contextlib.suppress(ImportError):
            getattr(importlib.import_module(module_name), class_name)().instrument()
    _instrument_logging()
    _instrument_langchain()


def _instrument_logging() -> None:
    """Enable LoggingInstrumentor while keeping handler ownership local.

    LoggingInstrumentor().instrument() can attach its own OTLP LoggingHandler
    to root, duplicating the handler installed by _init_logs. That handler would
    not use the same filters, so enable_log_auto_instrumentation=False keeps the
    record-factory hook (used by OTEL_PYTHON_LOG_CORRELATION) and skips the
    duplicate handler.
    """
    if _otel_logging_instr is None:
        return
    _otel_logging_instr.LoggingInstrumentor().instrument(enable_log_auto_instrumentation=False)


def _instrument_langchain() -> None:
    """Instrument LangChain with conservative payload defaults.

    Detailed LangChain content attributes use conservative defaults;
    operators can change visibility through the standard
    OPENINFERENCE_HIDE_* env vars.
    """
    # openinference-instrumentation-langchain ships in the optional [otel]
    # extra and is absent under .[server,dev]. The module-level sentinels
    # keep this a runtime no-op when not installed.
    if TraceConfig is None or _oi_langchain is None or REDACTED_VALUE is None:
        return

    # OpenInference's TraceConfig hide_* flags cover the standard value,
    # message, prompt, and choice attributes. Apply the same default treatment
    # to prompt-template variables, retrieved document content, and tool
    # parameters when hide_inputs is in effect.
    _INPUT_EXTRA_PATTERNS = (
        "llm.prompt_template.variables",
        "llm.prompt_template.template",
        ".document.content",
        ".document.metadata",
        "tool.parameters",
    )

    class _AioTraceConfig(TraceConfig):
        def mask(self, key, value):  # type: ignore[override]
            result = super().mask(key, value)
            if result is None:
                return None
            if self.hide_inputs and any(p in key for p in _INPUT_EXTRA_PATTERNS):
                return REDACTED_VALUE
            return result

    # OPENINFERENCE_HIDE_EMBEDDING_VECTORS (singular) is deprecated upstream;
    # OPENINFERENCE_HIDE_EMBEDDINGS_VECTORS (plural) is current. TraceConfig
    # OR-combines the two fields when masking, so binding only one with our
    # default-true would let the other's default silently override an explicit
    # "false" on either env var. Resolve once (modern wins, deprecated as
    # fallback) and bind both fields to the same value.
    hide_embeddings_vectors_value = _env_bool(
        "OPENINFERENCE_HIDE_EMBEDDINGS_VECTORS",
        default=_env_bool("OPENINFERENCE_HIDE_EMBEDDING_VECTORS", default=True),
    )
    config = _AioTraceConfig(
        hide_inputs=_env_bool("OPENINFERENCE_HIDE_INPUTS", default=True),
        hide_outputs=_env_bool("OPENINFERENCE_HIDE_OUTPUTS", default=True),
        hide_input_messages=_env_bool("OPENINFERENCE_HIDE_INPUT_MESSAGES", default=True),
        hide_output_messages=_env_bool("OPENINFERENCE_HIDE_OUTPUT_MESSAGES", default=True),
        hide_input_text=_env_bool("OPENINFERENCE_HIDE_INPUT_TEXT", default=True),
        hide_output_text=_env_bool("OPENINFERENCE_HIDE_OUTPUT_TEXT", default=True),
        hide_input_images=_env_bool("OPENINFERENCE_HIDE_INPUT_IMAGES", default=True),
        hide_embedding_vectors=hide_embeddings_vectors_value,
        hide_embeddings_vectors=hide_embeddings_vectors_value,
        hide_embeddings_text=_env_bool("OPENINFERENCE_HIDE_EMBEDDINGS_TEXT", default=True),
        hide_prompts=_env_bool("OPENINFERENCE_HIDE_PROMPTS", default=True),
        hide_choices=_env_bool("OPENINFERENCE_HIDE_CHOICES", default=True),
    )
    _oi_langchain.LangChainInstrumentor().instrument(config=config)


_OTLP_PROTOCOLS = frozenset({"grpc", "http/protobuf"})
_OTLP_DEFAULT_PROTOCOL = "grpc"


def _otlp_protocol(signal: str) -> str:
    """Return the OTLP protocol for a signal (TRACES / LOGS / METRICS).

    Per the OTel spec, the signal-specific OTEL_EXPORTER_OTLP_<SIGNAL>_PROTOCOL
    overrides the generic OTEL_EXPORTER_OTLP_PROTOCOL; fallback default is grpc.
    Values outside the spec-defined set (grpc, http/protobuf) — including the
    unsupported http/json — are coerced to the default with a warning so a typo
    or stray whitespace does not silently route exports to the wrong transport.
    """
    raw = (
        os.getenv(f"OTEL_EXPORTER_OTLP_{signal}_PROTOCOL")
        or os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL")
        or _OTLP_DEFAULT_PROTOCOL
    )
    normalized = raw.strip().lower()
    if normalized not in _OTLP_PROTOCOLS:
        LOGGER.warning(
            "Unrecognized OTLP %s protocol %r; falling back to %s",
            signal, raw, _OTLP_DEFAULT_PROTOCOL,
        )
        return _OTLP_DEFAULT_PROTOCOL
    return normalized


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    v = raw.strip().lower()
    if v in ("true", "1", "yes", "on"):
        return True
    if v in ("false", "0", "no", "off"):
        return False
    return default
