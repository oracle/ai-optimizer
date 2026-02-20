"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for logging_config.py
"""

import logging

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

        assert record.__version__ == "existing"


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
        logging_config.configure_logging()

        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(name)
            assert logger.propagate is False

    def test_pil_logger_configured(self):
        """configure_logging should configure PIL logger."""
        logging_config.configure_logging()

        logger = logging.getLogger("PIL")
        assert logger.propagate is False
        assert logger.level == logging.INFO

    def test_streamlit_logger_configured(self):
        """configure_logging should configure streamlit logger."""
        logging_config.configure_logging()

        logger = logging.getLogger("streamlit")
        assert logger.propagate is False


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
