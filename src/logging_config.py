"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared logging configuration for server and client packages.
"""
# spell-checker:ignore scriptrunner byteflow

import logging
import os
import warnings
from logging.config import dictConfig

from _version import __version__
from logging_redaction import RedactingFilter

try:
    from transformers.utils import logging as _transformers_logging
except ImportError:
    _transformers_logging = None

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


_PROBE_PATHS = frozenset({"/v1/liveness", "/v1/readiness"})


def _drop_successful_probe_access(record: logging.LogRecord) -> bool:
    """Drop uvicorn access logs for successful K8s probe requests.

    uvicorn's access logger passes
    ``(client_addr, method, full_path, http_version, status)`` as ``record.args``;
    non-tuple or short args fall through unfiltered.
    """
    args = record.args
    if not isinstance(args, tuple) or len(args) < 5:
        return True
    path, status = args[2], args[4]
    if not isinstance(path, str) or not isinstance(status, int):
        return True
    return not (200 <= status < 300 and path.split("?", 1)[0] in _PROBE_PATHS)


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
            "filters": {
                "redact": {"()": "logging_redaction.RedactingFilter"},
            },
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
                    "filters": ["redact"],
                },
            },
            "root": {
                "handlers": ["console"],
                "level": level,
            },
            "loggers": {
                "asyncio": {
                    "handlers": ["console"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "docket.worker": {
                    "handlers": ["console"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "numba.core": {
                    "handlers": ["console"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "transformers": {
                    "handlers": ["console"],
                    "level": "ERROR",
                    "propagate": False,
                },
                "uvicorn": {
                    "handlers": ["console"],
                    "level": "INFO",
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console"],
                    "level": "INFO",
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["console"],
                    "level": "INFO",
                    "propagate": False,
                },
                "LiteLLM": {
                    "handlers": ["console"],
                    "level": "INFO",
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
    logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").addFilter(_drop_script_run_context)
    logging.getLogger("uvicorn.access").addFilter(_drop_successful_probe_access)

    # ``transformers`` installs its own ``StreamHandler`` with a non-standard
    # ``[transformers] ...`` format. Remove it so messages flow through the
    # standard handler configured above (matching the project's log format).
    if _transformers_logging is not None:
        _transformers_logging.disable_default_handler()
        # Keep this in sync with the dictConfig threshold above; the helper mutates the logger level.
        _transformers_logging.set_verbosity_error()

    for handler in logging.getLogger().handlers:
        handler.addFilter(_inject_version)

    # Surface the value-filter keyset provenance once at startup.
    # ``key_source == "static"`` means the schema-derived path failed and
    # the filter is running on the static fallback set; diagnostic only.
    for handler in logging.getLogger().handlers:
        for flt in handler.filters:
            if isinstance(flt, RedactingFilter):
                logging.getLogger("logging_redaction").debug(
                    "log value filter initialized with %d field patterns (source=%s)",
                    flt.key_count,
                    flt.key_source,
                )
                break
        else:
            continue
        break

    logging.captureWarnings(True)
