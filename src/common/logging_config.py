"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Default Logging Configuration
"""
# pylint: disable=too-few-public-methods
# spell-checker:ignore levelname inotify openai httpcore fsevents litellm

import os
import asyncio
import logging
import warnings
from logging.config import dictConfig
from common._version import __version__

# --- Debug toggle ---
DEBUG_MODE = os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"

# --- Control DeprecationWarnings globally ---
if DEBUG_MODE:
    warnings.filterwarnings("default", category=DeprecationWarning)
else:
    warnings.filterwarnings("ignore", category=DeprecationWarning)


class VersionFilter(logging.Filter):
    """Logging filter that injects the current application version into log"""

    def filter(self, record):
        record.__version__ = __version__
        return True


class PrettifyCancelledError(logging.Filter):
    """Filter that keeps the log but removes the traceback and replaces the message."""

    def _contains_cancelled(self, exc: BaseException) -> bool:
        if isinstance(exc, asyncio.CancelledError):
            return True
        if hasattr(exc, "exceptions") and isinstance(exc, BaseExceptionGroup):  # type: ignore[name-defined]
            return any(self._contains_cancelled(e) for e in exc.exceptions)  # type: ignore[attr-defined]
        return False

    def filter(self, record: logging.LogRecord) -> bool:
        exc_info = record.__dict__.get("exc_info")
        if not exc_info:
            return True
        _, exc, _ = exc_info
        if exc and self._contains_cancelled(exc):
            # Strip the traceback and make it pretty
            record.exc_info = None
            record.msg = "Shutdown cancelled — graceful timeout exceeded."
            record.levelno = logging.WARNING
            record.levelname = logging.getLevelName(logging.WARNING)
        return True


# --- Standard formatter ---
FORMATTER = {
    "format": "%(asctime)s (v%(__version__)s) - %(levelname)-8s - (%(name)s): %(message)s",
    "datefmt": "%Y-%b-%d %H:%M:%S",
}
LOG_LEVEL = os.environ.get("LOG_LEVEL", default=logging.INFO)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": FORMATTER,
    },
    "filters": {
        "version_filter": {"()": VersionFilter},
        "prettify_cancelled": {"()": PrettifyCancelledError},
    },
    "handlers": {
        "default": {
            "level": LOG_LEVEL,
            "formatter": "standard",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.__stdout__",
            "filters": ["version_filter"],
        },
    },
    "loggers": {
        "": {  # root logger
            "level": LOG_LEVEL,
            "handlers": ["default"],
            "propagate": False,
        },
        "py.warnings": {  # capture warnings here
            "level": "DEBUG" if DEBUG_MODE else "ERROR",
            "handlers": ["default"],
            "propagate": False,
        },
        "uvicorn.error": {
            "level": LOG_LEVEL,
            "handlers": ["default"],
            "propagate": False,
            "filters": ["prettify_cancelled"],
        },
        "uvicorn.access": {
            "level": LOG_LEVEL,
            "handlers": ["default"],
            "propagate": False,
        },
        "asyncio": {
            "level": LOG_LEVEL,
            "handlers": ["default"],
            "propagate": False,
            "filters": ["prettify_cancelled"],
        },
        "watchdog.observers.inotify_buffer": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "PIL": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "fsevents": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "numba": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "docket.worker": {"level": "WARNING", "handlers": ["default"], "propagate": False},
        "fakeredis": {"level": "WARNING", "handlers": ["default"], "propagate": False},
        "oci": {"level": LOG_LEVEL, "handlers": ["default"], "propagate": False},
        "openai": {"level": LOG_LEVEL, "handlers": ["default"], "propagate": False},
        "httpcore": {"level": LOG_LEVEL, "handlers": ["default"], "propagate": False},
        "sagemaker.config": {"level": "WARNING", "handlers": ["default"], "propagate": False},
        "LiteLLM": {"level": LOG_LEVEL, "handlers": ["default"], "propagate": False},
        "LiteLLM Proxy": {"level": LOG_LEVEL, "handlers": ["default"], "propagate": False},
        "LiteLLM Router": {"level": LOG_LEVEL, "handlers": ["default"], "propagate": False},
    },
}

for name in ["LiteLLM", "LiteLLM Proxy", "LiteLLM Router"]:
    logger = logging.getLogger(name)
    logger.handlers = []  # clear handlers
    logger.propagate = False

dictConfig(LOGGING_CONFIG)

# --- Capture warnings into logging system ---
logging.captureWarnings(True)
