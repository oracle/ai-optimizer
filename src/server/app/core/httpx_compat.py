"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

HTTPX compatibility helpers.
"""

import logging

import httpx
from httpx import _client

LOGGER = logging.getLogger(__name__)


def disable_zstd_response_compression() -> bool:
    """Stop HTTPX 0.28.1 clients from advertising zstd response compression.

    HTTPX 0.28.1 cannot decode a streaming response composed of multiple zstd
    frames when each frame arrives in a separate network chunk. OCI GenAI can
    send chat streams in that form, so clients must not negotiate zstd until
    the HTTPX decoder is upgraded.

    Returns ``True`` when zstd was removed. The operation is process-wide and
    must run before creating HTTPX clients.
    """
    if httpx.__version__ != "0.28.1" or "zstd" not in _client.ACCEPT_ENCODING.split(", "):
        return False

    _client.ACCEPT_ENCODING = ", ".join(
        encoding for encoding in _client.ACCEPT_ENCODING.split(", ") if encoding != "zstd"
    )
    LOGGER.info("Disabled zstd response compression for HTTPX %s", httpx.__version__)
    return True
