"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Compatibility helpers for retired client-side access controls.

Shared catalog authority is enforced by the Server from authenticated
principals. These functions preserve page-module imports while leaving client
controls available.
"""
# spell-checker:ignore streamlit

import streamlit as st


def is_authenticated() -> bool:
    """Return true because the Client no longer applies a local access gate."""
    return True


def redacted_password_input(
    label: str,
    *,
    value: str,
    key: str,
    disabled: bool = False,
    help: str | None = None,
) -> str:
    """Render a normal password input without local authorization redaction."""
    return st.text_input(label, value=value, type="password", key=key, disabled=disabled, help=help)


def locked_notice() -> None:
    """Retired local authorization notice."""
