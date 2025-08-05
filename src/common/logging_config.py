"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Default Logging Configuration
"""
# spell-checker:ignore levelname inotify openai httpcore fsevents litellm

import os
import logging
from logging.config import dictConfig
from common._version import __version__


class VersionFilter(logging.Filter):
    """Logging filter that injects the current application version into log"""

    def filter(self, record):
        record.__version__ = __version__
        return True


# Standard formatter
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
        "version_filter": {
            "()": VersionFilter,
        },
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
        "uvicorn.error": {
            "level": LOG_LEVEL,
            "handlers": ["default"],
            "propagate": False,
        },
        "uvicorn.access": {
            "level": LOG_LEVEL,
            "handlers": ["default"],
            "propagate": False,
        },
        "asyncio": {"level": LOG_LEVEL, "handlers": ["default"], "propagate": False},
        "watchdog.observers.inotify_buffer": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "PIL": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "fsevents": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "numba": {"level": "INFO", "handlers": ["default"], "propagate": False},
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
