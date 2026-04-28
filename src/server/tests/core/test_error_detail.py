"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for :func:`server.app.core.error_detail.response_error_detail`.
"""

import logging

import pytest

from server.app.core.error_detail import response_error_detail


@pytest.mark.unit
def test_returns_only_the_fallback_string():
    """The provided fallback is returned unchanged."""
    detail = response_error_detail(Exception("marker-alpha marker-beta"), "Database connection failed.")
    assert detail == "Database connection failed."


@pytest.mark.unit
def test_logs_full_exception_at_error_level(caplog):
    """The original exception text is still logged."""
    with caplog.at_level(logging.ERROR, logger="server.app.core.error_detail"):
        response_error_detail(
            RuntimeError("marker-alpha marker-beta"),
            "Operation failed.",
        )
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "marker-alpha" in joined
    assert "marker-beta" in joined


@pytest.mark.unit
def test_handles_exception_with_no_message():
    """Bare exceptions still return the fallback unchanged."""
    detail = response_error_detail(ValueError(), "Validation failed.")
    assert detail == "Validation failed."


@pytest.mark.unit
def test_uses_fallback_even_when_exception_message_is_short():
    """The fallback is unconditional."""
    detail = response_error_detail(ValueError("marker-alpha"), "Operation failed.")
    assert "marker-alpha" not in detail
