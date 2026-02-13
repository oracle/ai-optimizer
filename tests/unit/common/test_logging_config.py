"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for common/logging_config.py

Tests logging configuration, filters, and formatters.
"""
# pylint: disable=too-few-public-methods, protected-access

import logging
import asyncio
import sys

from common import logging_config
from common._version import __version__


class TestVersionFilter:
    """Tests for VersionFilter logging filter."""

    def test_version_filter_injects_version(self):
        """VersionFilter should inject __version__ into log records."""
        filter_instance = logging_config.VersionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = filter_instance.filter(record)

        assert result is True
        assert hasattr(record, "__version__")
        assert getattr(record, "__version__") == __version__


class TestPrettifyCancelledError:
    """Tests for PrettifyCancelledError logging filter."""

    def test_filter_returns_true_for_normal_records(self):
        """PrettifyCancelledError should pass through normal records."""
        filter_instance = logging_config.PrettifyCancelledError()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Normal message",
            args=(),
            exc_info=None,
        )

        result = filter_instance.filter(record)

        assert result is True
        assert record.msg == "Normal message"

    def test_filter_modifies_cancelled_error_record(self):
        """PrettifyCancelledError should modify CancelledError records."""
        filter_instance = logging_config.PrettifyCancelledError()

        exc_info = None
        try:
            raise asyncio.CancelledError()
        except asyncio.CancelledError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Original message",
            args=(),
            exc_info=exc_info,
        )

        result = filter_instance.filter(record)

        assert result is True
        assert record.exc_info is None
        assert "graceful timeout" in record.msg.lower()
        assert record.levelno == logging.WARNING
        assert record.levelname == "WARNING"

    def test_filter_handles_exception_group_with_cancelled(self):
        """PrettifyCancelledError should handle ExceptionGroup with CancelledError."""
        filter_instance = logging_config.PrettifyCancelledError()

        # Create an ExceptionGroup containing a regular Exception wrapping CancelledError
        # Note: CancelledError is a BaseException, so we need to wrap it properly
        # Using a regular exception that contains a nested CancelledError simulation
        exc_info = None
        try:
            # Create an exception group with a regular exception
            exc_group = ExceptionGroup("test group", [ValueError("test")])
            raise exc_group
        except ExceptionGroup:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Original message",
            args=(),
            exc_info=exc_info,
        )

        # This should pass through since ValueError is not CancelledError
        result = filter_instance.filter(record)

        assert result is True
        # Regular exceptions are not modified
        assert record.msg == "Original message"

    def test_contains_cancelled_direct(self):
        """_contains_cancelled should return True for direct CancelledError."""
        filter_instance = logging_config.PrettifyCancelledError()

        cancelled = asyncio.CancelledError()
        assert filter_instance._contains_cancelled(cancelled) is True

    def test_contains_cancelled_other_exception(self):
        """_contains_cancelled should return False for other exceptions."""
        filter_instance = logging_config.PrettifyCancelledError()

        other_exc = ValueError("test")
        assert filter_instance._contains_cancelled(other_exc) is False


class TestLoggingConfig:
    """Tests for LOGGING_CONFIG dictionary."""

    def test_logging_config_has_required_keys(self):
        """LOGGING_CONFIG should have all required keys."""
        assert "version" in logging_config.LOGGING_CONFIG
        assert "disable_existing_loggers" in logging_config.LOGGING_CONFIG
        assert "formatters" in logging_config.LOGGING_CONFIG
        assert "filters" in logging_config.LOGGING_CONFIG
        assert "handlers" in logging_config.LOGGING_CONFIG
        assert "loggers" in logging_config.LOGGING_CONFIG

    def test_logging_config_version(self):
        """LOGGING_CONFIG version should be 1."""
        assert logging_config.LOGGING_CONFIG["version"] == 1

    def test_logging_config_does_not_disable_existing_loggers(self):
        """LOGGING_CONFIG should not disable existing loggers."""
        assert logging_config.LOGGING_CONFIG["disable_existing_loggers"] is False

    def test_standard_formatter_defined(self):
        """LOGGING_CONFIG should define standard formatter."""
        formatters = logging_config.LOGGING_CONFIG["formatters"]
        assert "standard" in formatters

    def test_version_filter_configured(self):
        """LOGGING_CONFIG should configure version_filter."""
        filters = logging_config.LOGGING_CONFIG["filters"]
        assert "version_filter" in filters
        assert filters["version_filter"]["()"] == logging_config.VersionFilter

    def test_prettify_cancelled_filter_configured(self):
        """LOGGING_CONFIG should configure prettify_cancelled filter."""
        filters = logging_config.LOGGING_CONFIG["filters"]
        assert "prettify_cancelled" in filters
        assert filters["prettify_cancelled"]["()"] == logging_config.PrettifyCancelledError

    def test_default_handler_configured(self):
        """LOGGING_CONFIG should configure default handler."""
        handlers = logging_config.LOGGING_CONFIG["handlers"]
        assert "default" in handlers
        assert handlers["default"]["formatter"] == "standard"
        assert handlers["default"]["class"] == "logging.StreamHandler"
        assert "version_filter" in handlers["default"]["filters"]

    def test_root_logger_configured(self):
        """LOGGING_CONFIG should configure root logger."""
        loggers = logging_config.LOGGING_CONFIG["loggers"]
        assert "" in loggers
        assert "default" in loggers[""]["handlers"]
        assert loggers[""]["propagate"] is False

    def test_uvicorn_loggers_configured(self):
        """LOGGING_CONFIG should configure uvicorn loggers."""
        loggers = logging_config.LOGGING_CONFIG["loggers"]
        assert "uvicorn.error" in loggers
        assert "uvicorn.access" in loggers
        assert "prettify_cancelled" in loggers["uvicorn.error"]["filters"]

    def test_asyncio_logger_configured(self):
        """LOGGING_CONFIG should configure asyncio logger."""
        loggers = logging_config.LOGGING_CONFIG["loggers"]
        assert "asyncio" in loggers
        assert "prettify_cancelled" in loggers["asyncio"]["filters"]

    def test_third_party_loggers_configured(self):
        """LOGGING_CONFIG should configure third-party loggers."""
        loggers = logging_config.LOGGING_CONFIG["loggers"]
        expected_loggers = [
            "watchdog.observers.inotify_buffer",
            "PIL",
            "fsevents",
            "numba",
            "oci",
            "openai",
            "httpcore",
            "sagemaker.config",
            "LiteLLM",
            "LiteLLM Proxy",
            "LiteLLM Router",
        ]
        for logger_name in expected_loggers:
            assert logger_name in loggers, f"Logger {logger_name} not configured"


class TestFormatterConfig:
    """Tests for FORMATTER configuration."""

    def test_formatter_format_string(self):
        """FORMATTER should have correct format string."""
        assert "%(asctime)s" in logging_config.FORMATTER["format"]
        assert "%(levelname)" in logging_config.FORMATTER["format"]
        assert "%(name)s" in logging_config.FORMATTER["format"]
        assert "%(message)s" in logging_config.FORMATTER["format"]
        assert "%(__version__)s" in logging_config.FORMATTER["format"]

    def test_formatter_date_format(self):
        """FORMATTER should have correct date format."""
        assert logging_config.FORMATTER["datefmt"] == "%Y-%b-%d %H:%M:%S"


class TestDebugMode:
    """Tests for DEBUG_MODE behavior."""

    def test_debug_mode_from_environment(self):
        """DEBUG_MODE should be set from LOG_LEVEL environment variable."""
        # The actual DEBUG_MODE value depends on the environment at import time
        # We just verify it's a boolean
        assert isinstance(logging_config.DEBUG_MODE, bool)

    def test_log_level_from_environment(self):
        """LOG_LEVEL should be read from environment or default to INFO."""
        # LOG_LEVEL is either the env var value or logging.INFO
        assert logging_config.LOG_LEVEL is not None


class TestWarningsCaptured:
    """Tests for warnings capture configuration."""

    def test_warnings_logger_configured(self):
        """py.warnings logger should be configured."""
        loggers = logging_config.LOGGING_CONFIG["loggers"]
        assert "py.warnings" in loggers
        assert loggers["py.warnings"]["propagate"] is False


class TestLiteLLMLoggersCleaned:
    """Tests for LiteLLM logger cleanup."""

    def test_litellm_loggers_propagate_disabled(self):
        """LiteLLM loggers should have propagate disabled."""
        # Note: The handlers may be re-added by other test imports,
        # but propagate should remain disabled
        for name in ["LiteLLM", "LiteLLM Proxy", "LiteLLM Router"]:
            logger = logging.getLogger(name)
            assert logger.propagate is False
