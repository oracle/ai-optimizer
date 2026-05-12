"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared-password access controls for selected Streamlit client UI.

When ``AIO_CLIENT_PASSWORD`` is unset, access checks are disabled. When set,
page modules call ``is_authenticated()`` to decide whether to show selected
widgets and values.

This applies only to the Streamlit UI. The FastAPI server continues to use
``AIO_API_KEY`` for API access.

Scope
-----
The shared-password check is applied to selected shared configuration and
shared-state controls, including Configuration tabs, stored connection
fields, reset/delete actions, and import/export. Pages that act as user
workspaces (ChatBot, Tools, Testbed) remain usable while unsigned-in; only
workspace controls that change shared state for other users are gated.
"""
# spell-checker:ignore streamlit

import hmac
import logging

import streamlit as st
from streamlit import session_state as state

from client.app.core.secrets import reveal
from client.app.core.settings import settings

LOGGER = logging.getLogger("client.app.core.auth")

_STATE_KEY = "auth_ok"
_WIDGET_KEY = "auth_password_input"
_SIGNIN_REQUESTED_KEY = "_signin_requested"
_SIGNIN_ERROR_KEY = "_signin_error"
_SIGNIN_QUERY_PARAM = "signin"
_LOCKED_NOTICE = (
    "Some features on this page require sign-in. "
    f'<a href="?{_SIGNIN_QUERY_PARAM}=1" target="_self">Sign in</a> to continue.'
)
_REDACTED_PLACEHOLDER = "`••••••••`"


def _expected_password() -> str | None:
    """Return the configured shared password, or None when the gate is off."""
    return reveal(settings.client_password)


def is_authenticated() -> bool:
    """Return True when the current session can use gated controls.

    Always True when no shared password is configured (gate disabled).
    """
    if not _expected_password():
        return True
    return state.get(_STATE_KEY) is True


def gate_active() -> bool:
    """Return True when a shared password is configured, i.e. gating is active."""
    return _expected_password() is not None


def request_signin() -> None:
    """Signal that the sign-in dialog should open on the next page render.

    Set by ``content/signin.py`` (the Sign-in nav page) just before it
    ``st.switch_page``s to ChatBot; consumed by ``auth_sidebar`` on the
    resulting render.
    """
    state[_SIGNIN_REQUESTED_KEY] = True


def sign_out() -> None:
    """Clear the auth flag and any in-flight password input.

    Called from ``content/signout.py`` (the Sign-out nav page) just before it
    ``st.switch_page``s to ChatBot.
    """
    state.pop(_STATE_KEY, None)
    state.pop(_WIDGET_KEY, None)


def redacted_password_input(
    label: str,
    *,
    value: str,
    key: str,
    disabled: bool = False,
    help: str | None = None,
) -> str | None:
    """Render a password ``st.text_input`` when signed in, a placeholder otherwise.

    When not signed in, the widget is omitted and ``None`` is returned. The
    placeholder uses the label sans trailing ``:``.
    """
    if is_authenticated():
        return st.text_input(
            label,
            value=value,
            type="password",
            key=key,
            disabled=disabled,
            help=help,
        )
    st.markdown(f"**{label.rstrip(':')}:** {_REDACTED_PLACEHOLDER}")
    return None


def locked_notice() -> None:
    """Render the inline sign-in notice.

    Renders a single subdued caption with an inline anchor to ``?signin=1``.
    ``auth_sidebar`` detects the param on the resulting rerun and opens the
    sign-in dialog. No-op when the gate is disabled or the user is already
    signed in.
    """
    if not _expected_password() or is_authenticated():
        return
    st.caption(_LOCKED_NOTICE, unsafe_allow_html=True)


def _try_signin() -> None:
    """``on_change`` callback for the password field — attempt auth on submit.

    Streamlit fires ``on_change`` only when the user actively commits a new
    value (Enter or focus loss), not on re-render, so a pre-existing widget
    value never auto-submits. ``st.rerun()`` is a no-op inside callbacks, so
    we only update session_state here; the dialog body picks up the result
    on the rerun that Streamlit issues automatically after the callback.
    """
    pw = state.get(_WIDGET_KEY, "")
    if not pw:
        return
    expected = _expected_password()
    if not expected:
        return
    # Compare on UTF-8 bytes; hmac.compare_digest only accepts ASCII-only str.
    if hmac.compare_digest(pw.encode("utf-8"), expected.encode("utf-8")):
        state[_STATE_KEY] = True
        state.pop(_WIDGET_KEY, None)
    else:
        LOGGER.warning("Streamlit client sign-in was not completed")
        state[_SIGNIN_ERROR_KEY] = True
        state.pop(_WIDGET_KEY, None)


@st.dialog("Sign in")
def _signin_dialog() -> None:
    """Modal dialog with a single password field. Submit by pressing Enter.

    There are no Submit / Cancel buttons — the user dismisses the dialog via
    the X icon or Esc, and submits by hitting Enter in the password field.
    Streamlit re-invokes the dialog body on every rerun while the dialog is
    open; on the post-callback rerun we detect ``is_authenticated()`` and
    dismiss the dialog with ``st.rerun()`` (which IS effective in script
    bodies, just not in callbacks).
    """
    expected = _expected_password()
    if not expected:
        return
    if is_authenticated():
        st.rerun()
    if state.pop(_SIGNIN_ERROR_KEY, False):
        st.error("Incorrect password.")
    st.caption("Enter the shared password to continue.")
    st.text_input(
        "Password",
        type="password",
        key=_WIDGET_KEY,
        autocomplete="current-password",
        on_change=_try_signin,
    )


def auth_sidebar() -> None:
    """Per-render auth hook: open the sign-in dialog when triggered.

    Called once per script run from ``main.py``. Two triggers open the dialog:

    1. ``?signin=1`` query param — set by clicking the inline ``sign-in`` link
       inside ``locked_notice`` (the user stays on the same page).
    2. ``state["_signin_requested"]`` flag — set by ``content/signin.py`` when
       the user clicks the sidebar nav entry. ``st.switch_page`` strips query
       params, so this nav-to-dialog signal travels via session_state instead.
    """
    if not _expected_password() or is_authenticated():
        return
    param_set = _SIGNIN_QUERY_PARAM in st.query_params
    flag_set = state.pop(_SIGNIN_REQUESTED_KEY, False)
    if param_set:
        del st.query_params[_SIGNIN_QUERY_PARAM]
    if param_set or flag_set:
        _signin_dialog()
