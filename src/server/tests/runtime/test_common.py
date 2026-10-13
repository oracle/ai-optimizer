"""
Copyright (c) 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for shared LLM error details.
"""

import pytest
from litellm.exceptions import AuthenticationError

from server.app.runtime.common import llm_error_detail


@pytest.mark.unit
def test_provider_authentication_error_omits_key_material():
    error = AuthenticationError(
        message="Incorrect API key provided: sk-proj-****AQEA",
        llm_provider="openai",
        model="text-embedding-3-small",
    )

    assert llm_error_detail(error) == "AuthenticationError: Incorrect API key provided"
    assert (
        llm_error_detail(error, fallback="Vector store operation failed.")
        == "AuthenticationError: Incorrect API key provided"
    )


@pytest.mark.unit
def test_wrapped_provider_authentication_error_uses_same_detail():
    provider_error = AuthenticationError(
        message="Incorrect API key provided: sk-proj-****AQEA",
        llm_provider="openai",
        model="text-embedding-3-small",
    )
    wrapped = RuntimeError("Embedding failed")
    wrapped.__cause__ = provider_error

    assert llm_error_detail(wrapped) == "AuthenticationError: Incorrect API key provided"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("No API key provided: sk-proj-secret", "AuthenticationError: API key is missing"),
        ("OCI signer expired: secret", "AuthenticationError: Credentials have expired"),
        ("API key does not have access to this model: secret", "AuthenticationError: Access denied"),
        ("Authentication rejected: secret", "AuthenticationError: Authentication failed"),
    ],
)
def test_other_authentication_failures_keep_safe_distinct_reasons(message, expected):
    error = AuthenticationError(message=message, llm_provider="openai", model="test-model")
    wrapped = RuntimeError("Model call failed")
    wrapped.__cause__ = error

    assert llm_error_detail(error) == expected
    assert llm_error_detail(wrapped, fallback="Vector store operation failed.") == expected


@pytest.mark.unit
def test_other_llm_error_retains_provider_message():
    assert llm_error_detail(RuntimeError("Provider unavailable")) == "RuntimeError: Provider unavailable"
    assert llm_error_detail(RuntimeError("Provider unavailable"), fallback="Vector store operation failed.") == (
        "Vector store operation failed."
    )
