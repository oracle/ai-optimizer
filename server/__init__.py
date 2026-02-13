"""Server package initialization and logging configuration."""

from __future__ import annotations

from collections.abc import Iterable
import logging
import os
from logging.config import dictConfig

from ._version import __version__


FORMATTER = {
    'format': '%(asctime)s (v%(__version__)s) - %(levelname)-8s - (%(name)s): %(message)s',
    'datefmt': '%Y-%b-%d %H:%M:%S',
}

_UVICORN_LOGGERS = ('uvicorn', 'uvicorn.error', 'uvicorn.access')


class _VersionFilter(logging.Filter):
    """Add package version information to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, '__version__'):
            record.__version__ = __version__
        return True


_VERSION_FILTER = _VersionFilter()


def _attach_filter(handler: logging.Handler) -> None:
    if not any(isinstance(existing, _VersionFilter) for existing in handler.filters):
        handler.addFilter(_VERSION_FILTER)


def _configure_handlers(loggers: Iterable[logging.Logger], formatter: logging.Formatter) -> None:
    for logger in loggers:
        for handler in logger.handlers:
            handler.setFormatter(formatter)
            _attach_filter(handler)


def configure_logging() -> None:
    """Apply unified logging settings across server components."""

    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    uvicorn_access_level = os.getenv('UVICORN_ACCESS_LOG_LEVEL', 'INFO').upper()
    dictConfig(
        {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {
                'standard': {
                    'format': FORMATTER['format'],
                    'datefmt': FORMATTER['datefmt'],
                },
            },
            'filters': {
                'inject_version': {'()': _VersionFilter},
            },
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'standard',
                    'filters': ['inject_version'],
                },
            },
            'root': {
                'handlers': ['console'],
                'level': log_level,
            },
            'loggers': {
                'uvicorn': {
                    'handlers': ['console'],
                    'level': log_level,
                    'propagate': False,
                },
                'uvicorn.error': {
                    'handlers': ['console'],
                    'level': log_level,
                    'propagate': False,
                },
                'uvicorn.access': {
                    'handlers': ['console'],
                    'level': uvicorn_access_level,
                    'propagate': False,
                },
            },
        }
    )

    root_logger = logging.getLogger()
    formatter = logging.Formatter(FORMATTER['format'], FORMATTER['datefmt'])
    target_loggers = [root_logger, *(logging.getLogger(name) for name in _UVICORN_LOGGERS)]
    _configure_handlers(target_loggers, formatter)


configure_logging()

__all__ = ('FORMATTER', 'configure_logging')
