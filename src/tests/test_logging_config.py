"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for logging_config.py
"""

import logging
import types

import logging_config
from _version import __version__


class TestInjectVersion:
    """Tests for _inject_version logging filter."""

    def test_injects_version_into_record(self):
        """_inject_version should inject __version__ into log records."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = logging_config._inject_version(record)

        assert result is True
        assert hasattr(record, "__version__")
        assert getattr(record, "__version__") == __version__

    def test_does_not_overwrite_existing_version(self):
        """_inject_version should not overwrite an existing __version__."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.__version__ = "existing"

        logging_config._inject_version(record)

        assert getattr(record, "__version__") == "existing"


class TestDropSuccessfulProbeAccess:
    """Tests for _drop_successful_probe_access logging filter."""

    @staticmethod
    def _record(args):
        return logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='%s - "%s %s HTTP/%s" %d',
            args=args,
            exc_info=None,
        )

    def test_drops_2xx_readiness(self):
        record = self._record(("10.0.0.1:1234", "GET", "/v1/readiness", "1.1", 200))
        assert logging_config._drop_successful_probe_access(record) is False

    def test_drops_2xx_liveness(self):
        record = self._record(("10.0.0.1:1234", "GET", "/v1/liveness", "1.1", 204))
        assert logging_config._drop_successful_probe_access(record) is False

    def test_keeps_non_2xx_probe(self):
        record = self._record(("10.0.0.1:1234", "GET", "/v1/readiness", "1.1", 503))
        assert logging_config._drop_successful_probe_access(record) is True

    def test_keeps_non_probe_path(self):
        record = self._record(("10.0.0.1:1234", "GET", "/v1/chat/completions", "1.1", 200))
        assert logging_config._drop_successful_probe_access(record) is True

    def test_ignores_query_string_on_probe(self):
        record = self._record(("10.0.0.1:1234", "GET", "/v1/readiness?verbose=1", "1.1", 200))
        assert logging_config._drop_successful_probe_access(record) is False

    def test_passes_through_unexpected_args_shape(self):
        record = self._record(None)
        assert logging_config._drop_successful_probe_access(record) is True


class TestConfigureLogging:
    """Tests for configure_logging function."""

    def test_configure_logging_sets_root_handlers(self):
        """configure_logging should set up root logger handlers."""
        logging_config.configure_logging()

        root = logging.getLogger()
        assert len(root.handlers) > 0

    def test_configure_logging_respects_level_argument(self):
        """configure_logging should use the provided log level."""
        logging_config.configure_logging(log_level="WARNING")

        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_configure_logging_default_level(self, monkeypatch):
        """configure_logging should default to INFO when no env var is set."""
        monkeypatch.delenv("AIO_LOG_LEVEL", raising=False)

        logging_config.configure_logging()

        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_configure_logging_from_env(self, monkeypatch):
        """configure_logging should read AIO_LOG_LEVEL from environment."""
        monkeypatch.setenv("AIO_LOG_LEVEL", "DEBUG")

        logging_config.configure_logging()

        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_uvicorn_loggers_configured(self):
        """configure_logging should configure uvicorn loggers."""
        logging_config.configure_logging(log_level="DEBUG")

        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            LOGGER = logging.getLogger(name)
            assert LOGGER.propagate is False
            assert LOGGER.level == logging.INFO

    def test_pil_logger_configured(self):
        """configure_logging should configure PIL LOGGER."""
        logging_config.configure_logging()

        LOGGER = logging.getLogger("PIL")
        assert LOGGER.propagate is False
        assert LOGGER.level == logging.INFO

    def test_streamlit_logger_configured(self):
        """configure_logging should configure streamlit LOGGER."""
        logging_config.configure_logging()

        LOGGER = logging.getLogger("streamlit")
        assert LOGGER.propagate is False

    def test_litellm_logger_uses_application_configuration(self):
        """configure_logging should prevent duplicate LiteLLM output."""
        logging_config.configure_logging(log_level="DEBUG")

        LOGGER = logging.getLogger("LiteLLM")
        assert LOGGER.level == logging.INFO
        assert LOGGER.propagate is False
        assert LOGGER.handlers == logging.getLogger().handlers

    def test_transformers_helper_keeps_error_threshold(self, monkeypatch):
        """Transformers helper should not lower configured verbosity."""
        calls = []

        fake_logging = types.SimpleNamespace()

        def disable_default_handler():
            calls.append("disable_default_handler")

        def set_verbosity_error():
            calls.append("set_verbosity_error")
            logging.getLogger("transformers").setLevel(logging.ERROR)

        def set_verbosity_warning():
            calls.append("set_verbosity_warning")
            logging.getLogger("transformers").setLevel(logging.WARNING)

        fake_logging.disable_default_handler = disable_default_handler
        fake_logging.set_verbosity_error = set_verbosity_error
        fake_logging.set_verbosity_warning = set_verbosity_warning

        # ``_transformers_logging`` is resolved at module import; patch the
        # module-level reference so ``configure_logging`` picks up the fake.
        monkeypatch.setattr(logging_config, "_transformers_logging", fake_logging)

        logging_config.configure_logging()

        LOGGER = logging.getLogger("transformers")
        assert LOGGER.level == logging.ERROR
        assert calls == ["disable_default_handler", "set_verbosity_error"]


class TestFormatterConfig:
    """Tests for formatter constants."""

    def test_formatter_format_string(self):
        """Format string should contain expected fields."""
        assert "%(asctime)s" in logging_config._FORMATTER_FORMAT
        assert "%(levelname)" in logging_config._FORMATTER_FORMAT
        assert "%(name)s" in logging_config._FORMATTER_FORMAT
        assert "%(message)s" in logging_config._FORMATTER_FORMAT
        assert "%(__version__)s" in logging_config._FORMATTER_FORMAT

    def test_formatter_date_format(self):
        """Date format should match expected pattern."""
        assert logging_config._FORMATTER_DATEFMT == "%Y-%b-%d %H:%M:%S"
