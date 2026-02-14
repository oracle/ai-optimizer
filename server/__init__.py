"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Server package initialization and logging configuration.
"""

import logging
from logging.config import dictConfig
from server.app.core.config import settings
from ._version import __version__


_FORMATTER_FORMAT = "%(asctime)s (v%(__version__)s) - %(levelname)-8s - (%(name)s): %(message)s"
_FORMATTER_DATEFMT = "%Y-%b-%d %H:%M:%S"


def _inject_version(record: logging.LogRecord) -> bool:
    """Add package version information to log records."""
    if not hasattr(record, "__version__"):
        record.__version__ = __version__
    return True


def configure_logging() -> None:
    """Apply unified logging settings across server components."""

    log_level = settings.log_level.upper()
    uvicorn_access_level = settings.log_level.upper()
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
                "level": log_level,
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["console"],
                    "level": log_level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console"],
                    "level": log_level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["console"],
                    "level": uvicorn_access_level,
                    "propagate": False,
                },
            },
        }
    )

    for handler in logging.getLogger().handlers:
        handler.addFilter(_inject_version)


configure_logging()

__all__ = ("configure_logging",)
