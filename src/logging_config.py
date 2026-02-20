"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared logging configuration for server and client packages.
"""
# spell-checker:ignore scriptrunner

import logging
import os
import warnings
from logging.config import dictConfig

from _version import __version__

_FORMATTER_FORMAT = "%(asctime)s (v%(__version__)s) - %(levelname)-8s - (%(name)s): %(message)s"
_FORMATTER_DATEFMT = "%Y-%b-%d %H:%M:%S"


def _inject_version(record: logging.LogRecord) -> bool:
    """Add package version information to log records."""
    if not hasattr(record, "__version__"):
        record.__version__ = __version__
    return True


def _drop_script_run_context(record: logging.LogRecord) -> bool:
    """Suppress Streamlit's harmless 'missing ScriptRunContext' warnings."""
    return "missing ScriptRunContext" not in record.getMessage()


def configure_logging(log_level: str | None = None) -> None:
    """Apply unified logging settings.

    Args:
        log_level: Override log level.  Falls back to the ``AIO_LOG_LEVEL``
            environment variable, then ``"INFO"``.
    """
    level = (log_level or os.getenv("AIO_LOG_LEVEL", "INFO")).upper()
    debug = level == "DEBUG"

    # Suppress DeprecationWarning (includes PydanticDeprecatedSince20) unless debugging
    if debug:
        warnings.filterwarnings("default", category=DeprecationWarning)
    else:
        warnings.filterwarnings("ignore", category=DeprecationWarning)

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": _FORMATTER_FORMAT,
                    "datefmt": _FORMATTER_DATEFMT,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                },
            },
            "root": {
                "handlers": ["console"],
                "level": level,
            },
            "loggers": {
                "docket.worker": {
                    "handlers": ["console"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "uvicorn": {
                    "handlers": ["console"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["console"],
                    "level": level,
                    "propagate": False,
                },
                "py.warnings": {
                    "handlers": ["console"],
                    "level": "DEBUG" if debug else "ERROR",
                    "propagate": False,
                },
                "PIL": {
                    "handlers": ["console"],
                    "level": "INFO",
                    "propagate": False,
                },
                "streamlit": {
                    "handlers": ["console"],
                    "level": level,
                    "propagate": False,
                },
            },
        }
    )

    # Filter applied to the logger (not handler) so it runs before ALL handlers,
    # including any Streamlit adds after this configuration.
    logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").addFilter(
        _drop_script_run_context
    )

    for handler in logging.getLogger().handlers:
        handler.addFilter(_inject_version)

    logging.captureWarnings(True)
