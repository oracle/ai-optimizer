"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.core.auth.
"""
# spell-checker: disable

import sys
from unittest.mock import patch

import pytest

from client.app.core.auth import (
    _SIGNIN_ERROR_KEY,
    _SIGNIN_QUERY_PARAM,
    _SIGNIN_REQUESTED_KEY,
    _STATE_KEY,
    _WIDGET_KEY,
)
from client.tests.conftest import AttrDict

MODULE = "client.app.core.auth"

pytestmark = pytest.mark.unit


def _passthrough_dialog(*_args, **_kwargs):
    """Replacement for ``@st.dialog`` so the decorated function stays callable."""

    def decorator(fn):
        return fn

    return decorator


@pytest.fixture(autouse=True)
def _reload_auth_module():
    """Reload ``auth`` with ``st.dialog`` patched to a passthrough decorator.

    ``@st.dialog`` is applied at import time, so the patch must be in place
    before the module is imported.
    """
    import streamlit as real_st

    sys.modules.pop(MODULE, None)
    with patch.object(real_st, "dialog", _passthrough_dialog):
        import client.app.core.auth  # noqa: F401

        yield
    sys.modules.pop(MODULE, None)


def _import_auth():
    from client.app.core import auth

    return auth


# ---------------------------------------------------------------------------
# is_authenticated()
# ---------------------------------------------------------------------------
class TestIsAuthenticated:
    """Tests for is_authenticated."""

    def test_returns_true_when_password_unset(self):
        """Gate disabled → always authenticated."""
        auth = _import_auth()
        with patch(f"{MODULE}._expected_password", return_value=None):
            assert auth.is_authenticated() is True

    def test_returns_false_when_password_set_and_flag_missing(self):
        """Gate enabled and state flag absent → not authenticated."""
        auth = _import_auth()
        state = AttrDict({})
        with (
            patch(f"{MODULE}._expected_password", return_value="secret"),
            patch(f"{MODULE}.state", state),
        ):
            assert auth.is_authenticated() is False

    def test_returns_true_when_state_flag_set(self):
        """Gate enabled and state flag True → authenticated."""
        auth = _import_auth()
        state = AttrDict({_STATE_KEY: True})
        with (
            patch(f"{MODULE}._expected_password", return_value="secret"),
            patch(f"{MODULE}.state", state),
        ):
            assert auth.is_authenticated() is True


# ---------------------------------------------------------------------------
# locked_notice()
# ---------------------------------------------------------------------------
class TestLockedNotice:
    """Tests for locked_notice."""

    def test_no_op_when_password_unset(self, mock_st):
        """When the gate is disabled, nothing is rendered."""
        auth = _import_auth()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._expected_password", return_value=None),
        ):
            auth.locked_notice()
        mock_st.caption.assert_not_called()

    def test_no_op_when_authenticated(self, mock_st):
        """Signed-in users do not see the locked notice."""
        auth = _import_auth()
        state = AttrDict({_STATE_KEY: True})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="secret"),
        ):
            auth.locked_notice()
        mock_st.caption.assert_not_called()

    def test_renders_inline_signin_caption(self, mock_st):
        """Unauthenticated users see one caption with an inline ``sign-in`` link.

        The link must use ``target="_self"`` so clicking it stays in the same
        browser tab (Streamlit's default markdown link behavior is _blank).
        """
        auth = _import_auth()
        state = AttrDict({})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="secret"),
        ):
            auth.locked_notice()
        mock_st.caption.assert_called_once()
        rendered = mock_st.caption.call_args[0][0]
        assert "sign-in" in rendered
        assert "?signin=1" in rendered
        assert 'target="_self"' in rendered
        kwargs = mock_st.caption.call_args.kwargs
        assert kwargs.get("unsafe_allow_html") is True
        # No separate button — the link is inline.
        mock_st.button.assert_not_called()


# ---------------------------------------------------------------------------
# _signin_dialog()
# ---------------------------------------------------------------------------
class TestSigninDialog:
    """Tests for the password dialog body."""

    def test_no_op_when_password_unset(self, mock_st):
        """Dialog body is a no-op when the gate is disabled."""
        auth = _import_auth()
        state = AttrDict({})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value=None),
        ):
            auth._signin_dialog()
        mock_st.text_input.assert_not_called()

    def test_renders_text_input_with_on_change_callback(self, mock_st):
        """Dialog body renders the password input wired to the ``_try_signin`` callback."""
        auth = _import_auth()
        state = AttrDict({})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="correct"),
        ):
            auth._signin_dialog()
        mock_st.text_input.assert_called_once()
        assert mock_st.text_input.call_args.kwargs.get("on_change") is auth._try_signin
        mock_st.button.assert_not_called()

    def test_body_dismisses_dialog_when_already_authenticated(self, mock_st):
        """If the user just authenticated (via the on_change callback), the body calls st.rerun to close."""
        auth = _import_auth()
        state = AttrDict({_STATE_KEY: True})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="correct"),
        ):
            auth._signin_dialog()
        mock_st.rerun.assert_called_once()

    def test_body_shows_error_after_failed_attempt(self, mock_st):
        """A ``_signin_error`` flag set by the callback surfaces as st.error and is consumed."""
        auth = _import_auth()
        state = AttrDict({_SIGNIN_ERROR_KEY: True})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="correct"),
        ):
            auth._signin_dialog()
        mock_st.error.assert_called_once()
        assert _SIGNIN_ERROR_KEY not in state


# ---------------------------------------------------------------------------
# _try_signin() — on_change callback
# ---------------------------------------------------------------------------
class TestTrySignin:
    """Tests for the password-field on_change callback."""

    def test_empty_password_is_noop(self):
        """An empty widget value is ignored; no flags written."""
        auth = _import_auth()
        state = AttrDict({_WIDGET_KEY: ""})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="correct"),
        ):
            auth._try_signin()
        assert state.get(_STATE_KEY) is None
        assert _SIGNIN_ERROR_KEY not in state

    def test_no_op_when_password_unset(self):
        """Gate disabled (no configured password) → callback is a no-op."""
        auth = _import_auth()
        state = AttrDict({_WIDGET_KEY: "anything"})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value=None),
        ):
            auth._try_signin()
        assert state.get(_STATE_KEY) is None
        assert _SIGNIN_ERROR_KEY not in state

    def test_wrong_password_sets_error_flag_and_logs(self, caplog):
        """Wrong password sets the error flag, clears the widget, and logs."""
        auth = _import_auth()
        state = AttrDict({_WIDGET_KEY: "wrong"})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="correct"),
            caplog.at_level("WARNING", logger="client.app.core.auth"),
        ):
            auth._try_signin()
        assert state.get(_STATE_KEY) is None
        assert state.get(_SIGNIN_ERROR_KEY) is True
        assert _WIDGET_KEY not in state
        assert "sign-in was not completed" in caplog.text

    def test_correct_password_sets_state_and_clears_widget(self):
        """Correct password sets auth_ok and clears the widget key."""
        auth = _import_auth()
        state = AttrDict({_WIDGET_KEY: "correct"})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="correct"),
        ):
            auth._try_signin()
        assert state[_STATE_KEY] is True
        assert _WIDGET_KEY not in state
        assert _SIGNIN_ERROR_KEY not in state

    def test_non_ascii_correct_password_matches(self):
        """A configured password with non-ASCII characters must compare cleanly."""
        auth = _import_auth()
        state = AttrDict({_WIDGET_KEY: "café\U0001f511"})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="café\U0001f511"),
        ):
            auth._try_signin()
        assert state[_STATE_KEY] is True
        assert _WIDGET_KEY not in state

    def test_non_ascii_wrong_password_sets_error(self):
        """A wrong attempt containing non-ASCII must set the error flag, not raise."""
        auth = _import_auth()
        state = AttrDict({_WIDGET_KEY: "café"})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="latte"),
        ):
            auth._try_signin()
        assert state.get(_STATE_KEY) is None
        assert state.get(_SIGNIN_ERROR_KEY) is True

    def test_non_ascii_configured_password_with_ascii_attempt(self):
        """A non-ASCII configured password compared against an ASCII wrong attempt must not raise."""
        auth = _import_auth()
        state = AttrDict({_WIDGET_KEY: "wrong"})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="café"),
        ):
            auth._try_signin()
        assert state.get(_STATE_KEY) is None
        assert state.get(_SIGNIN_ERROR_KEY) is True


# ---------------------------------------------------------------------------
# auth_sidebar()
# ---------------------------------------------------------------------------
class TestAuthSidebar:
    """Tests for auth_sidebar."""

    def test_no_op_when_password_unset(self, mock_st):
        """No button is rendered when the gate is disabled."""
        auth = _import_auth()
        state = AttrDict({})
        mock_st.query_params = {}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value=None),
        ):
            auth.auth_sidebar()
        mock_st.sidebar.button.assert_not_called()

    def test_no_op_when_unauthenticated_without_query_param(self, mock_st):
        """Unauthenticated users see no sidebar affordance — sign-in is inline."""
        auth = _import_auth()
        state = AttrDict({})
        mock_st.query_params = {}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="secret"),
        ):
            auth.auth_sidebar()
        mock_st.sidebar.button.assert_not_called()

    def test_query_param_opens_dialog_and_is_cleared(self, mock_st):
        """A ``?signin=1`` query param triggers the sign-in dialog and clears the param."""
        auth = _import_auth()
        state = AttrDict({})
        query_params = {_SIGNIN_QUERY_PARAM: "1", "other": "keep"}
        mock_st.query_params = query_params
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="secret"),
            patch(f"{MODULE}._signin_dialog") as mock_dialog,
        ):
            auth.auth_sidebar()
        mock_dialog.assert_called_once()
        assert _SIGNIN_QUERY_PARAM not in query_params
        assert query_params.get("other") == "keep"
        mock_st.sidebar.button.assert_not_called()

    def test_query_param_ignored_when_already_authenticated(self, mock_st):
        """Already-authenticated users do not retrigger the dialog from a leftover param."""
        auth = _import_auth()
        state = AttrDict({_STATE_KEY: True})
        query_params = {_SIGNIN_QUERY_PARAM: "1"}
        mock_st.query_params = query_params
        mock_st.sidebar.button.return_value = False
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="secret"),
            patch(f"{MODULE}._signin_dialog") as mock_dialog,
        ):
            auth.auth_sidebar()
        mock_dialog.assert_not_called()

    def test_signin_requested_flag_opens_dialog_and_clears_flag(self, mock_st):
        """A ``state['_signin_requested']`` flag triggers the dialog and is consumed."""
        auth = _import_auth()
        state = AttrDict({_SIGNIN_REQUESTED_KEY: True})
        mock_st.query_params = {}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="secret"),
            patch(f"{MODULE}._signin_dialog") as mock_dialog,
        ):
            auth.auth_sidebar()
        mock_dialog.assert_called_once()
        assert _SIGNIN_REQUESTED_KEY not in state

    def test_signin_flag_ignored_when_already_authenticated(self, mock_st):
        """An already-signed-in user does not retrigger the dialog from a leftover flag."""
        auth = _import_auth()
        state = AttrDict({_STATE_KEY: True, _SIGNIN_REQUESTED_KEY: True})
        mock_st.query_params = {}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="secret"),
            patch(f"{MODULE}._signin_dialog") as mock_dialog,
        ):
            auth.auth_sidebar()
        mock_dialog.assert_not_called()

    def test_authenticated_renders_no_widgets(self, mock_st):
        """Authenticated users get no sidebar widgets — Sign out is a nav page now."""
        auth = _import_auth()
        state = AttrDict({_STATE_KEY: True})
        mock_st.query_params = {}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._expected_password", return_value="secret"),
        ):
            auth.auth_sidebar()
        mock_st.sidebar.button.assert_not_called()
        mock_st.sidebar.markdown.assert_not_called()


# ---------------------------------------------------------------------------
# gate_active()
# ---------------------------------------------------------------------------
class TestGateActive:
    """Tests for gate_active."""

    def test_returns_false_when_password_unset(self):
        """Gate disabled → False."""
        auth = _import_auth()
        with patch(f"{MODULE}._expected_password", return_value=None):
            assert auth.gate_active() is False

    def test_returns_true_when_password_set(self):
        """Gate enabled → True."""
        auth = _import_auth()
        with patch(f"{MODULE}._expected_password", return_value="secret"):
            assert auth.gate_active() is True


# ---------------------------------------------------------------------------
# request_signin() / sign_out()
# ---------------------------------------------------------------------------
class TestRequestSignin:
    """Tests for the public ``request_signin`` helper."""

    def test_sets_flag(self):
        auth = _import_auth()
        state = AttrDict({})
        with patch(f"{MODULE}.state", state):
            auth.request_signin()
        assert state.get(_SIGNIN_REQUESTED_KEY) is True


class TestSignOut:
    """Tests for the public ``sign_out`` helper."""

    def test_clears_auth_state(self):
        auth = _import_auth()
        state = AttrDict({_STATE_KEY: True, _WIDGET_KEY: "leftover"})
        with patch(f"{MODULE}.state", state):
            auth.sign_out()
        assert _STATE_KEY not in state
        assert _WIDGET_KEY not in state

    def test_safe_when_already_signed_out(self):
        auth = _import_auth()
        state = AttrDict({})
        with patch(f"{MODULE}.state", state):
            auth.sign_out()
        assert _STATE_KEY not in state


# ---------------------------------------------------------------------------
# redacted_password_input()
# ---------------------------------------------------------------------------
class TestRedactedPasswordInput:
    """Tests for the masking helper used by api_server, databases, models."""

    def test_renders_widget_when_authenticated(self, mock_st):
        """Signed-in users see a real password text_input with the value."""
        auth = _import_auth()
        mock_st.text_input.return_value = "secret-value"
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.is_authenticated", return_value=True),
        ):
            result = auth.redacted_password_input(
                "Password:", value="secret-value", key="form_pw", disabled=False
            )
        mock_st.text_input.assert_called_once()
        kwargs = mock_st.text_input.call_args.kwargs
        assert kwargs.get("value") == "secret-value"
        assert kwargs.get("type") == "password"
        assert kwargs.get("key") == "form_pw"
        assert kwargs.get("disabled") is False
        assert result == "secret-value"
        mock_st.markdown.assert_not_called()

    def test_renders_placeholder_when_unauthenticated(self, mock_st):
        """Unauthenticated users see a ``••••••••`` markdown placeholder, no widget."""
        auth = _import_auth()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.is_authenticated", return_value=False),
        ):
            result = auth.redacted_password_input(
                "API Key:", value="real-secret-do-not-leak", key="form_key"
            )
        mock_st.text_input.assert_not_called()
        mock_st.markdown.assert_called_once()
        rendered = mock_st.markdown.call_args[0][0]
        assert "real-secret-do-not-leak" not in rendered
        assert "API Key" in rendered
        assert result is None
