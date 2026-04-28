"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Helpers for producing fallback exception details in HTTP responses.
"""

import logging

LOGGER = logging.getLogger(__name__)


def response_error_detail(exc: BaseException, fallback: str) -> str:
    """Return *fallback* and log the original exception with its traceback."""
    LOGGER.exception("Request handling failed: %s", exc)
    return fallback
