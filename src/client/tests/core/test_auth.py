"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for retired client-side access-control compatibility helpers.
"""

import pytest

from client.app.core import auth

pytestmark = pytest.mark.unit


def test_client_access_controls_are_always_available():
    assert auth.is_authenticated() is True


def test_password_input_is_never_redacted(mock_st):
    auth.st = mock_st

    auth.redacted_password_input("Password", value="secret", key="password")

    mock_st.text_input.assert_called_once_with(
        "Password", value="secret", type="password", key="password", disabled=False, help=None
    )
