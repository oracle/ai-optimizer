"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.otel.setup: env-var-driven OpenTelemetry initialization,
payload defaults for LangChain spans, and signal-specific endpoint guards.
"""
# spell-checker: disable

import contextlib
import importlib.util
import logging
import os
from unittest import mock

import pytest

from server.app.otel import setup

pytestmark = pytest.mark.unit


def _otel_extra_installed() -> bool:
    """All OTel-touching tests require the [otel] extra; check before running."""
    for mod in (
        "opentelemetry.sdk._logs",
        "opentelemetry.instrumentation.fastapi",
        "openinference.instrumentation.langchain",
    ):
        if importlib.util.find_spec(mod) is None:
            return False
    return True


OTEL_AVAILABLE = _otel_extra_installed()
requires_otel = pytest.mark.skipif(not OTEL_AVAILABLE, reason="requires [otel] extra")


# ---------------------------------------------------------------------------
# _env_bool - default-preserving boolean parser
# ---------------------------------------------------------------------------


class TestEnvBool:
    @pytest.mark.parametrize("default", [True, False])
    def test_unset_returns_default(self, monkeypatch, default):
        monkeypatch.delenv("AIO_TEST_BOOL", raising=False)
        assert setup._env_bool("AIO_TEST_BOOL", default=default) is default

    @pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "YES", "on", "ON"])
    def test_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv("AIO_TEST_BOOL", value)
        assert setup._env_bool("AIO_TEST_BOOL", default=False) is True

    @pytest.mark.parametrize("value", ["false", "FALSE", "False", "0", "no", "off"])
    def test_falsy_values(self, monkeypatch, value):
        monkeypatch.setenv("AIO_TEST_BOOL", value)
        assert setup._env_bool("AIO_TEST_BOOL", default=True) is False

    @pytest.mark.parametrize("value", ["", "tre", "hide", "maybe", "  "])
    def test_malformed_preserves_default(self, monkeypatch, value):
        # Malformed input must not flip the configured default.
        monkeypatch.setenv("AIO_TEST_BOOL", value)
        assert setup._env_bool("AIO_TEST_BOOL", default=True) is True
        assert setup._env_bool("AIO_TEST_BOOL", default=False) is False


# ---------------------------------------------------------------------------
# _init_logs — endpoint resolution guard
# ---------------------------------------------------------------------------


@requires_otel
class TestInitLogs:
    @pytest.fixture
    def resource(self):
        from opentelemetry.sdk.resources import Resource

        return Resource.create({})

    def test_skips_when_only_traces_endpoint_set(self, monkeypatch, caplog, resource):
        # With only OTEL_EXPORTER_OTLP_TRACES_ENDPOINT set, OTLPLogExporter()
        # would default to localhost:4317 silently — _init_logs must skip log
        # export entirely in that case.
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "true")
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://collector:4317")

        set_provider = mock.MagicMock()
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", set_provider)

        with caplog.at_level(logging.INFO, logger="server.app.otel.setup"):
            setup._init_logs(resource)

        set_provider.assert_not_called()
        assert "OTLP log export skipped" in caplog.text

    def test_skips_when_OTEL_LOGS_EXPORTER_none(self, monkeypatch, resource):
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "true")
        monkeypatch.setenv("OTEL_LOGS_EXPORTER", "none")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

        set_provider = mock.MagicMock()
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", set_provider)

        setup._init_logs(resource)

        set_provider.assert_not_called()

    def test_skips_when_OTEL_LOGS_EXPORTER_console_only(self, monkeypatch, resource):
        # OTEL_LOGS_EXPORTER is comma-separated per the OTel
        # spec. An operator who set it to "console" wants console-only logs
        # and must not get OTLP shipping just because a trace endpoint is set.
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "true")
        monkeypatch.setenv("OTEL_LOGS_EXPORTER", "console")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

        set_provider = mock.MagicMock()
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", set_provider)

        setup._init_logs(resource)

        set_provider.assert_not_called()

    def test_proceeds_when_OTEL_LOGS_EXPORTER_includes_otlp_and_console(self, monkeypatch, resource):
        # Comma-separated list with otlp present is a valid opt-in.
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "true")
        monkeypatch.setenv("OTEL_LOGS_EXPORTER", "otlp,console")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

        set_provider = mock.MagicMock()
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", set_provider)

        setup._init_logs(resource)

        set_provider.assert_called_once()

    def test_proceeds_when_OTEL_LOGS_EXPORTER_empty_string(self, monkeypatch, resource):
        # Empty string must fall back to the spec default ("otlp"), not be
        # treated as "no exporter requested".
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "true")
        monkeypatch.setenv("OTEL_LOGS_EXPORTER", "")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

        set_provider = mock.MagicMock()
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", set_provider)

        setup._init_logs(resource)

        set_provider.assert_called_once()

    def test_skips_when_AIO_OTEL_LOGS_ENABLED_unset(self, monkeypatch, resource):
        # Log export requires explicit opt-in; a trace endpoint alone must not
        # enable log shipping because application logs can include request
        # content.
        monkeypatch.delenv("AIO_OTEL_LOGS_ENABLED", raising=False)
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

        set_provider = mock.MagicMock()
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", set_provider)

        setup._init_logs(resource)

        set_provider.assert_not_called()

    def test_skips_when_AIO_OTEL_LOGS_ENABLED_false(self, monkeypatch, resource):
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "false")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

        set_provider = mock.MagicMock()
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", set_provider)

        setup._init_logs(resource)

        set_provider.assert_not_called()

    def test_skips_when_AIO_OTEL_LOGS_ENABLED_malformed(self, monkeypatch, resource):
        # Malformed value must fail safe (default = False, opt-in not granted).
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "tre")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")

        set_provider = mock.MagicMock()
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", set_provider)

        setup._init_logs(resource)

        set_provider.assert_not_called()

    def test_handler_applies_project_filter(self, monkeypatch, resource):
        # OTel log handler must apply the project filter even when reached via
        # a propagate=False logger whose own handler chain does not include it.
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
        monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", mock.MagicMock())

        from opentelemetry.sdk._logs import LoggingHandler

        root = logging.getLogger()
        original_handlers = list(root.handlers)
        try:
            setup._init_logs(resource)

            new_otel_handlers = [
                h for h in root.handlers if isinstance(h, LoggingHandler) and h not in original_handlers
            ]
            assert new_otel_handlers, "expected an OTel handler attached to root"
            handler = new_otel_handlers[0]

            record = logging.LogRecord(
                name="server.app.api.v1.something",
                level=logging.INFO,
                pathname="x",
                lineno=0,
                msg="connecting with password=hunter2 dsn=foo",
                args=(),
                exc_info=None,
            )
            handler.filter(record)

            assert "hunter2" not in record.getMessage(), (
                "configured field value should be normalized before OTLP export"
            )
        finally:
            root.handlers = original_handlers
            for name in list(logging.root.manager.loggerDict):
                named = logging.getLogger(name)
                named.handlers = [h for h in named.handlers if not isinstance(h, LoggingHandler)]

    @pytest.mark.parametrize(
        "logger_name",
        [
            # OTel SDK / exporter loggers are handled through their normal
            # diagnostics path.
            "opentelemetry.exporter.otlp.proto.grpc.exporter",
            "opentelemetry.sdk._logs._internal",
            # HTTP OTLP exporter goes through requests/urllib3;
            # at DEBUG with the collector unreachable, urllib3.connectionpool
            # emits connection/retry records. Include these dependencies so
            # exporter activity is not passed through the app log exporter.
            "urllib3.connectionpool",
            "urllib3.util.retry",
            "requests.adapters",
            "httpx",
            "httpcore.connection",
            # gRPC OTLP exporter emits transport records under grpc.*.
            "grpc",
            "grpc._channel",
        ],
    )
    def test_handler_filters_exporter_dependency_records(self, monkeypatch, resource, logger_name):
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
        monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", mock.MagicMock())

        from opentelemetry.sdk._logs import LoggingHandler

        root = logging.getLogger()
        original_handlers = list(root.handlers)
        try:
            setup._init_logs(resource)

            new_otel_handlers = [
                h for h in root.handlers if isinstance(h, LoggingHandler) and h not in original_handlers
            ]
            assert len(new_otel_handlers) == 1, "expected one new OTel handler attached to root"
            handler = new_otel_handlers[0]

            record = logging.LogRecord(
                name=logger_name,
                level=logging.WARNING,
                pathname="x",
                lineno=0,
                msg="dummy",
                args=(),
                exc_info=None,
            )
            assert not handler.filter(record), f"{logger_name} records must be filtered out"
        finally:
            root.handlers = original_handlers
            for name in list(logging.root.manager.loggerDict):
                named = logging.getLogger(name)
                named.handlers = [h for h in named.handlers if not isinstance(h, LoggingHandler)]

    def test_handler_passes_application_records(self, monkeypatch, resource):
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
        monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", mock.MagicMock())

        from opentelemetry.sdk._logs import LoggingHandler

        root = logging.getLogger()
        original_handlers = list(root.handlers)
        try:
            setup._init_logs(resource)
            handler = next(
                h for h in root.handlers if isinstance(h, LoggingHandler) and h not in original_handlers
            )

            app_record = logging.LogRecord(
                name="server.app.api.v1.chat",
                level=logging.INFO,
                pathname="x",
                lineno=0,
                msg="hello",
                args=(),
                exc_info=None,
            )
            assert handler.filter(app_record), "application records must pass through"
        finally:
            root.handlers = original_handlers
            for name in list(logging.root.manager.loggerDict):
                named = logging.getLogger(name)
                named.handlers = [h for h in named.handlers if not isinstance(h, LoggingHandler)]

    def test_log_processor_normalizes_exception_attributes(self):
        # LoggingHandler exports record.exc_info as separate
        # exception.message / exception.stacktrace attributes after the handler
        # filter chain, so the processor applies the same treatment to the
        # SDK-side attributes.
        from opentelemetry._logs import LogRecord
        from opentelemetry.sdk._logs import ReadWriteLogRecord

        record = LogRecord(
            body="login failed: password=hunter2",
            attributes={
                "exception.type": "ValueError",
                "exception.message": "boom: password=hunter2 dsn=foo",
                "exception.stacktrace": "Traceback (most recent call last)\n  oracle://user:hunter2@db",
                "code.filepath": "x.py",
            },
        )
        rw = ReadWriteLogRecord(log_record=record)

        processor = setup._RedactingLogProcessor()
        processor.on_emit(rw)

        attrs = rw.log_record.attributes
        body = rw.log_record.body
        assert attrs is not None
        for key in ("exception.message", "exception.stacktrace"):
            value = attrs[key]
            assert isinstance(value, str)
            assert "hunter2" not in value
        assert isinstance(body, str)
        assert "hunter2" not in body
        # Non-credential attributes are preserved unchanged.
        assert attrs["code.filepath"] == "x.py"
        assert attrs["exception.type"] == "ValueError"

    def test_logger_provider_wires_normalizing_processor_first(self, monkeypatch, resource):
        # The processor must run before BatchLogRecordProcessor: the SDK
        # invokes processors in registration order, and batching should receive
        # the normalized exception attributes.
        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
        monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", mock.MagicMock())

        add_processor = mock.MagicMock()
        monkeypatch.setattr(
            "opentelemetry.sdk._logs.LoggerProvider.add_log_record_processor",
            add_processor,
        )

        setup._init_logs(resource)

        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        assert add_processor.call_count == 2, (
            f"expected 2 processor registrations, got {add_processor.call_count}"
        )
        first = add_processor.call_args_list[0].args[0]
        second = add_processor.call_args_list[1].args[0]
        assert isinstance(first, setup._RedactingLogProcessor)
        assert isinstance(second, BatchLogRecordProcessor)


# ---------------------------------------------------------------------------
# _instrument_libraries — auto-instrumentor wiring
# ---------------------------------------------------------------------------


@requires_otel
class TestInstrumentLibraries:
    @staticmethod
    def _mock_other_instrumentors(monkeypatch):
        # Out-of-scope instrumentors get neutralized so the test only exercises
        # the LoggingInstrumentor wiring.
        for path in (
            "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor",
            "opentelemetry.instrumentation.requests.RequestsInstrumentor",
            "openinference.instrumentation.langchain.LangChainInstrumentor",
        ):
            monkeypatch.setattr(path, mock.MagicMock(return_value=mock.MagicMock()))

    def test_logging_instrumentor_skips_auto_handler(self, monkeypatch):
        # opentelemetry-instrumentation-logging's
        # LoggingInstrumentor.instrument() defaults to attaching a second
        # OTLP LoggingHandler to root, duplicating the one _init_logs already
        # installed. We opt out via enable_log_auto_instrumentation=False while
        # keeping the record-factory hook for trace/span correlation.
        instrument = mock.MagicMock()
        instrumentor_class = mock.MagicMock(return_value=mock.MagicMock(instrument=instrument))
        monkeypatch.setattr(
            "opentelemetry.instrumentation.logging.LoggingInstrumentor",
            instrumentor_class,
        )
        self._mock_other_instrumentors(monkeypatch)

        setup._instrument_libraries()

        instrument.assert_called_once_with(enable_log_auto_instrumentation=False)

    def test_logging_instrumentor_does_not_register_second_root_handler(self, monkeypatch):
        # End-to-end guard against future regressions even if the upstream
        # kwarg name changes: after _init_logs + _instrument_libraries, exactly
        # one OTel-owned handler must be attached to root (ours, with filters).
        # Note: _init_logs uses opentelemetry.sdk._logs.LoggingHandler while
        # LoggingInstrumentor uses opentelemetry.instrumentation.logging.handler.LoggingHandler
        # — different classes, so we filter by module prefix to catch both.
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        from opentelemetry.sdk.resources import Resource

        def _is_otel_handler(h: logging.Handler) -> bool:
            return type(h).__module__.startswith("opentelemetry")

        monkeypatch.setenv("AIO_OTEL_LOGS_ENABLED", "true")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
        monkeypatch.delenv("OTEL_LOGS_EXPORTER", raising=False)
        # Clear upstream auto-instrumentation env knobs so the test exercises
        # the default code path (without them, the duplicate handler is added).
        monkeypatch.delenv("OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION", raising=False)
        monkeypatch.delenv("OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED", raising=False)
        monkeypatch.setattr("opentelemetry._logs.set_logger_provider", mock.MagicMock())
        self._mock_other_instrumentors(monkeypatch)

        # BaseInstrumentor is a singleton; .instrument() no-ops once
        # _is_instrumented_by_opentelemetry is True on the instance. Force a
        # clean slate so the test exercises the actual instrumentation path.
        LoggingInstrumentor()._is_instrumented_by_opentelemetry = False
        LoggingInstrumentor._logging_handler = None
        LoggingInstrumentor._old_factory = None

        root = logging.getLogger()
        original_handlers = list(root.handlers)
        try:
            setup._init_logs(Resource.create({}))
            setup._instrument_libraries()

            new_otel_handlers = [
                h for h in root.handlers if _is_otel_handler(h) and h not in original_handlers
            ]
            assert len(new_otel_handlers) == 1, (
                f"expected exactly one OTel handler on root, got {len(new_otel_handlers)}: "
                f"{[type(h).__module__ + '.' + type(h).__name__ for h in new_otel_handlers]}"
            )
        finally:
            root.handlers = [h for h in root.handlers if not _is_otel_handler(h)]
            for name in list(logging.root.manager.loggerDict):
                named = logging.getLogger(name)
                named.handlers = [h for h in named.handlers if not _is_otel_handler(h)]
            with contextlib.suppress(Exception):
                LoggingInstrumentor().uninstrument()


# ---------------------------------------------------------------------------
# _instrument_langchain - payload-default TraceConfig
# ---------------------------------------------------------------------------


@requires_otel
class TestInstrumentLangchain:
    HIDE_VARS = (
        "OPENINFERENCE_HIDE_INPUTS",
        "OPENINFERENCE_HIDE_OUTPUTS",
        "OPENINFERENCE_HIDE_INPUT_MESSAGES",
        "OPENINFERENCE_HIDE_OUTPUT_MESSAGES",
        "OPENINFERENCE_HIDE_INPUT_TEXT",
        "OPENINFERENCE_HIDE_OUTPUT_TEXT",
        "OPENINFERENCE_HIDE_EMBEDDING_VECTORS",
        "OPENINFERENCE_HIDE_EMBEDDINGS_VECTORS",
    )

    def _patch_instrumentor(self, monkeypatch):
        instrument_method = mock.MagicMock()
        instrumentor_class = mock.MagicMock(return_value=mock.MagicMock(instrument=instrument_method))
        monkeypatch.setattr(
            "openinference.instrumentation.langchain.LangChainInstrumentor",
            instrumentor_class,
        )
        return instrument_method

    def _clear_hide_vars(self, monkeypatch):
        for var in self.HIDE_VARS:
            monkeypatch.delenv(var, raising=False)

    def test_default_hides_all_payloads(self, monkeypatch):
        self._clear_hide_vars(monkeypatch)
        instrument = self._patch_instrumentor(monkeypatch)

        setup._instrument_langchain()

        instrument.assert_called_once()
        config = instrument.call_args.kwargs["config"]
        assert config.hide_inputs is True
        assert config.hide_outputs is True
        assert config.hide_input_messages is True
        assert config.hide_output_messages is True
        assert config.hide_input_text is True
        assert config.hide_output_text is True
        # Both the deprecated singular and current plural fields must be set —
        # TraceConfig OR-combines them when masking, so leaving the modern field
        # at its False default would let an operator's explicit "false" on the
        # singular var be silently overridden (and vice versa).
        assert config.hide_embedding_vectors is True
        assert config.hide_embeddings_vectors is True

    def test_operator_opt_in_via_env(self, monkeypatch):
        self._clear_hide_vars(monkeypatch)
        monkeypatch.setenv("OPENINFERENCE_HIDE_INPUTS", "false")
        monkeypatch.setenv("OPENINFERENCE_HIDE_OUTPUTS", "false")

        instrument = self._patch_instrumentor(monkeypatch)
        setup._instrument_langchain()

        config = instrument.call_args.kwargs["config"]
        assert config.hide_inputs is False
        assert config.hide_outputs is False
        # Untouched flags retain the configured default.
        assert config.hide_input_messages is True
        assert config.hide_output_messages is True

    def test_malformed_env_preserves_configured_default(self, monkeypatch):
        # Typo'd value must not flip the configured default.
        self._clear_hide_vars(monkeypatch)
        monkeypatch.setenv("OPENINFERENCE_HIDE_INPUTS", "tre")

        instrument = self._patch_instrumentor(monkeypatch)
        setup._instrument_langchain()

        config = instrument.call_args.kwargs["config"]
        assert config.hide_inputs is True

    @pytest.mark.parametrize(
        "key",
        [
            "llm.prompt_template.variables",
            "llm.prompt_template.template",
            "retrieval.documents.0.document.content",
            "retrieval.documents.5.document.metadata",
            "tool.parameters",
        ],
    )
    def test_default_masks_extra_input_payload_attributes(self, monkeypatch, key):
        # These OpenInference-specific payload attributes should follow the
        # same default visibility setting as other input payloads.
        self._clear_hide_vars(monkeypatch)
        instrument = self._patch_instrumentor(monkeypatch)
        setup._instrument_langchain()

        config = instrument.call_args.kwargs["config"]
        masked = config.mask(key, "user-supplied content")

        assert masked != "user-supplied content", f"{key} must follow default payload visibility"

    def test_default_masks_message_tool_calls(self, monkeypatch):
        # Output-message tool-call arguments should follow the output
        # visibility setting.
        self._clear_hide_vars(monkeypatch)
        instrument = self._patch_instrumentor(monkeypatch)
        setup._instrument_langchain()

        config = instrument.call_args.kwargs["config"]
        masked = config.mask(
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments",
            '{"query": "sample query"}',
        )

        assert masked != '{"query": "sample query"}'

    def test_embedding_vectors_hidden_by_default(self, monkeypatch):
        # Default setting: with neither env var set, embedding vector payloads
        # are hidden by TraceConfig.mask().
        self._clear_hide_vars(monkeypatch)
        instrument = self._patch_instrumentor(monkeypatch)
        setup._instrument_langchain()

        config = instrument.call_args.kwargs["config"]
        masked = config.mask("embedding.embeddings.0.embedding.vector", (0.1, 0.2, 0.3))

        assert masked != (0.1, 0.2, 0.3), "embedding vectors should be hidden by default"

    def test_modern_embeddings_vectors_env_can_unhide(self, monkeypatch):
        # OPENINFERENCE_HIDE_EMBEDDING_VECTORS (singular) is
        # deprecated upstream; OPENINFERENCE_HIDE_EMBEDDINGS_VECTORS (plural)
        # is current. TraceConfig OR-combines the two fields, so binding only
        # the deprecated field with our default-true would silently override
        # an explicit "false" on the modern env var. Operator opt-out via the
        # current variable must actually unhide vectors.
        self._clear_hide_vars(monkeypatch)
        monkeypatch.setenv("OPENINFERENCE_HIDE_EMBEDDINGS_VECTORS", "false")

        instrument = self._patch_instrumentor(monkeypatch)
        setup._instrument_langchain()

        config = instrument.call_args.kwargs["config"]
        masked = config.mask("embedding.embeddings.0.embedding.vector", (0.1, 0.2, 0.3))

        assert masked == (0.1, 0.2, 0.3)

    def test_deprecated_embedding_vectors_env_still_honored(self, monkeypatch):
        # Back-compat: operators on the older env-var name can still unhide.
        self._clear_hide_vars(monkeypatch)
        monkeypatch.setenv("OPENINFERENCE_HIDE_EMBEDDING_VECTORS", "false")

        instrument = self._patch_instrumentor(monkeypatch)
        setup._instrument_langchain()

        config = instrument.call_args.kwargs["config"]
        masked = config.mask("embedding.embeddings.0.embedding.vector", (0.1, 0.2, 0.3))

        assert masked == (0.1, 0.2, 0.3)

    def test_hide_inputs_false_unmasks_extra_attributes(self, monkeypatch):
        # When hide_inputs is false, the extra input-payload patterns
        # follow the same setting and are returned unmasked.
        self._clear_hide_vars(monkeypatch)
        monkeypatch.setenv("OPENINFERENCE_HIDE_INPUTS", "false")

        instrument = self._patch_instrumentor(monkeypatch)
        setup._instrument_langchain()

        config = instrument.call_args.kwargs["config"]
        masked = config.mask("llm.prompt_template.variables", "user question")

        assert masked == "user question"


# ---------------------------------------------------------------------------
# init_telemetry — opt-out / unsupported config guards
# ---------------------------------------------------------------------------


@requires_otel
class TestInitTelemetryGuards:
    """Verify init_telemetry takes the early-exit path for various opt-out configs."""

    @pytest.fixture
    def no_set_tracer_provider(self, monkeypatch):
        m = mock.MagicMock()
        monkeypatch.setattr("opentelemetry.trace.set_tracer_provider", m)
        return m

    @staticmethod
    def _clear_otel_env(monkeypatch):
        for var in list(os.environ):
            if var.startswith(("OTEL_", "OPENINFERENCE_")):
                monkeypatch.delenv(var, raising=False)

    def test_no_op_when_no_env_vars(self, monkeypatch, no_set_tracer_provider):
        self._clear_otel_env(monkeypatch)

        setup.init_telemetry()

        no_set_tracer_provider.assert_not_called()

    def test_no_op_when_otlp_requested_but_no_endpoint(self, monkeypatch, no_set_tracer_provider):
        self._clear_otel_env(monkeypatch)
        monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp")

        setup.init_telemetry()

        no_set_tracer_provider.assert_not_called()

    def test_no_op_when_OTEL_TRACES_EXPORTER_none(self, monkeypatch, no_set_tracer_provider):
        self._clear_otel_env(monkeypatch)
        monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://x:4317")

        setup.init_telemetry()

        no_set_tracer_provider.assert_not_called()

    def test_no_op_when_unsupported_exporter_value(self, monkeypatch, no_set_tracer_provider):
        self._clear_otel_env(monkeypatch)
        monkeypatch.setenv("OTEL_TRACES_EXPORTER", "jaeger")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://x:4317")

        setup.init_telemetry()

        no_set_tracer_provider.assert_not_called()


# ---------------------------------------------------------------------------
# instrument_fastapi — gate on tracing-active
# ---------------------------------------------------------------------------


@requires_otel
class TestInstrumentFastapi:
    def test_no_op_when_tracing_not_active(self, monkeypatch):
        from fastapi import FastAPI
        from opentelemetry.trace import ProxyTracerProvider

        # _tracing_active() returns False when get_tracer_provider() returns
        # something other than a real (SDK) TracerProvider.
        monkeypatch.setattr(
            "opentelemetry.trace.get_tracer_provider",
            lambda: ProxyTracerProvider(),
        )

        instrument_app = mock.MagicMock()
        monkeypatch.setattr(
            "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app",
            instrument_app,
        )

        setup.instrument_fastapi(FastAPI())

        instrument_app.assert_not_called()
