"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for the sign-in / sign-out navigation page scripts.

Both modules are page-level scripts (they execute at import time), so each
test imports the module fresh inside a controlled patch context.
"""
# spell-checker: disable

import importlib
import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from client.app.core.auth import _SIGNIN_REQUESTED_KEY, _STATE_KEY, _WIDGET_KEY
from client.tests.conftest import AttrDict

pytestmark = pytest.mark.unit


def _run_page(module_path: str, *, st_mock, state_mock, is_auth: bool = False):
    """Import ``module_path`` fresh with streamlit and session_state mocked.

    The page scripts execute imperative code at import time, so we discard
    the cached module before each invocation.
    """
    sys.modules.pop(module_path, None)
    with ExitStack() as stack:
        stack.enter_context(patch("streamlit.session_state", state_mock, create=True))
        stack.enter_context(patch("streamlit.switch_page", st_mock.switch_page))
        stack.enter_context(patch("client.app.core.auth.state", state_mock))
        stack.enter_context(patch("client.app.core.auth.is_authenticated", return_value=is_auth))
        try:
            importlib.import_module(module_path)
        finally:
            sys.modules.pop(module_path, None)


# ---------------------------------------------------------------------------
# signin.py
# ---------------------------------------------------------------------------
class TestSigninPage:
    """Tests for client.app.content.signin."""

    def test_sets_flag_and_switches_when_unauthenticated(self):
        """Unauth visit: sets ``_signin_requested`` flag and navigates to ChatBot."""
        st_mock = MagicMock()
        state_mock = AttrDict({})
        _run_page("client.app.content.signin", st_mock=st_mock, state_mock=state_mock, is_auth=False)
        assert state_mock.get(_SIGNIN_REQUESTED_KEY) is True
        st_mock.switch_page.assert_called_once_with("content/chatbot.py")

    def test_just_switches_when_already_authenticated(self):
        """Already-signed-in visit: no flag, straight to ChatBot."""
        st_mock = MagicMock()
        state_mock = AttrDict({})
        _run_page("client.app.content.signin", st_mock=st_mock, state_mock=state_mock, is_auth=True)
        assert _SIGNIN_REQUESTED_KEY not in state_mock
        st_mock.switch_page.assert_called_once_with("content/chatbot.py")


# ---------------------------------------------------------------------------
# signout.py
# ---------------------------------------------------------------------------
class TestSignoutPage:
    """Tests for client.app.content.signout."""

    def test_clears_auth_state_and_switches(self):
        """Sign-out clears auth_ok and the password widget key, then switches to ChatBot."""
        st_mock = MagicMock()
        state_mock = AttrDict({_STATE_KEY: True, _WIDGET_KEY: "secret"})
        _run_page("client.app.content.signout", st_mock=st_mock, state_mock=state_mock)
        assert _STATE_KEY not in state_mock
        assert _WIDGET_KEY not in state_mock
        st_mock.switch_page.assert_called_once_with("content/chatbot.py")

    def test_safe_when_already_signed_out(self):
        """Pops are no-ops if the keys are absent — script still switches."""
        st_mock = MagicMock()
        state_mock = AttrDict({})
        _run_page("client.app.content.signout", st_mock=st_mock, state_mock=state_mock)
        st_mock.switch_page.assert_called_once_with("content/chatbot.py")
