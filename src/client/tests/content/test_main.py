"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.main — server connection and initialization logic.
"""
# spell-checker: disable

import contextlib
import sys
from unittest.mock import MagicMock, call, patch

import pytest

from client.tests.conftest import AttrDict

MODULE = "client.app.main"
API_MODULE = "client.app.core.api"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _remove_main_module():
    """Remove client.app.main from sys.modules so it can be re-imported."""
    sys.modules.pop("client.app.main", None)


def _import_main(state, get_settings_side_effect):
    """Import client.app.main with all module-level dependencies mocked.

    Mock target *source* modules so that ``from X import Y`` picks up mocks
    during the fresh import.  Streamlit is replaced via ``patch.object`` on the
    real module so ``from streamlit import session_state as state`` binds to
    our AttrDict.
    """
    import streamlit as real_st

    mock_get_settings = MagicMock(side_effect=get_settings_side_effect)
    mock_start = MagicMock()
    mock_api_get = MagicMock(return_value=[])

    _remove_main_module()

    with (  # noqa: SIM117
        # Streamlit session_state binding
        patch.object(real_st, "session_state", state),
        # Prevent real HTTP calls — patch at the SOURCE module
        patch(f"{API_MODULE}.get_server_settings", mock_get_settings),
        patch(f"{API_MODULE}.start_server", mock_start),
        patch(f"{API_MODULE}.api_get", mock_api_get),
        # Suppress logging config
        patch("logging_config.configure_logging"),
    ):
        with contextlib.suppress(SystemExit):
            import client.app.main  # noqa: F401

    return mock_get_settings, mock_start


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMainConnectionLogic:
    """Tests for the server connection logic in client/app/main.py."""

    def setup_method(self):
        """Remove cached module before each test."""
        _remove_main_module()

    def test_about_details_show_signed_in_email_and_opaque_session(self):
        state = AttrDict({"optimizer_client": "session-123"})
        valid_settings = {"database_configs": [], "model_configs": [], "client_settings": {}}
        _import_main(state, get_settings_side_effect=[valid_settings])
        about_details = sys.modules[MODULE]._about_details

        assert (
            about_details("session-123", "alice@example.com")
            == "Signed in as: alice@example.com\n\nSession: session-123"
        )

    def test_successful_first_connection(self):
        """When get_server_settings returns data, start_server is not called."""
        state = AttrDict({"optimizer_client": "test-123"})
        valid_settings = {"database_configs": [], "model_configs": [], "client_settings": {}}

        _, mock_start = _import_main(state, get_settings_side_effect=[valid_settings])

        mock_start.assert_not_called()
        assert "settings" in state

    def test_connection_retry_after_start(self):
        """When first connection fails, starts server and retries."""
        state = AttrDict({"optimizer_client": "test-456"})
        valid_settings = {"database_configs": [], "model_configs": [], "client_settings": {}}

        mock_get, mock_start = _import_main(state, get_settings_side_effect=[None, valid_settings])

        mock_start.assert_called_once()
        assert mock_get.call_count == 2

    def test_connection_failure_shows_error(self):
        """When all connection attempts fail, st.error is called."""
        state = AttrDict({"optimizer_client": "test-789"})

        _import_main(state, get_settings_side_effect=[None, None])

        # state.settings should be None after both attempts fail
        assert state.get("settings") is None

    def test_oidc_startup_adds_sidebar_space_before_spinner(self):
        """The OIDC startup indicator must not render directly beneath the logo."""
        import streamlit as real_st

        state = AttrDict({"optimizer_client": "test-oidc"})
        sidebar = MagicMock()
        sidebar.spinner.return_value = contextlib.nullcontext()
        user = MagicMock(is_logged_in=False)
        login = MagicMock()
        navigation = MagicMock()

        _remove_main_module()
        with (
            patch.object(real_st, "session_state", state),
            patch.object(real_st, "sidebar", sidebar),
            patch.object(real_st, "secrets", {"auth": {}}),
            patch.object(real_st, "user", user),
            patch.object(real_st, "login", login),
            patch.object(real_st, "Page", return_value=MagicMock()),
            patch.object(real_st, "navigation", navigation),
            patch.object(real_st, "stop", side_effect=SystemExit),
            patch(f"{API_MODULE}._server_module_available", return_value=True),
            patch(f"{API_MODULE}.start_server"),
            patch(f"{API_MODULE}.get_server_settings", return_value={}),
            patch(f"{API_MODULE}.api_get", return_value=[]),
            patch("logging_config.configure_logging"),
            contextlib.suppress(SystemExit),
        ):
            import client.app.main  # noqa: F401

        assert sidebar.method_calls.index(call.space(size="small")) < sidebar.method_calls.index(
            call.spinner("Starting server...", show_time=True)
        )
        login.assert_called_once_with()
        navigation.assert_not_called()

    def test_signed_out_oidc_starts_native_login_automatically(self):
        """The signed-out branch starts native OIDC without adding a navigation page."""
        import streamlit as real_st

        state = AttrDict({"optimizer_client": "test-signin"})
        sidebar = MagicMock()
        sidebar.spinner.return_value = contextlib.nullcontext()
        user = MagicMock(is_logged_in=False)
        login = MagicMock()
        navigation = MagicMock()

        with (
            patch.object(real_st, "session_state", state),
            patch.object(real_st, "sidebar", sidebar),
            patch.object(real_st, "secrets", {"auth": {}}),
            patch.object(real_st, "user", user),
            patch.object(real_st, "login", login),
            patch.object(real_st, "navigation", navigation),
            patch.object(real_st, "stop", side_effect=SystemExit),
            patch(f"{API_MODULE}._server_module_available", return_value=True),
            patch(f"{API_MODULE}.start_server"),
            patch(f"{API_MODULE}.get_server_settings", return_value={}),
            patch(f"{API_MODULE}.api_get", return_value=[]),
            patch("logging_config.configure_logging"),
        ):
            _remove_main_module()
            with contextlib.suppress(SystemExit):
                import client.app.main  # noqa: F401

        login.assert_called_once_with()
        navigation.assert_not_called()

    def test_signed_in_oidc_adds_signout_as_the_last_navigation_item(self):
        """The native sign-out action is the final sidebar navigation item."""
        import streamlit as real_st

        state = AttrDict({"optimizer_client": "test-signout"})
        sidebar = MagicMock()
        user = MagicMock(is_logged_in=True)
        logout = MagicMock()
        pages = []
        navigation_result = MagicMock()
        navigation_result.run.side_effect = lambda: None

        def page(*args, **kwargs):
            page_result = MagicMock()
            pages.append((args, kwargs, page_result))
            return page_result

        def navigation(*args, **kwargs):
            return navigation_result

        with (
            patch.object(real_st, "session_state", state),
            patch.object(real_st, "sidebar", sidebar),
            patch.object(real_st, "secrets", {"auth": {}}),
            patch.object(real_st, "user", user),
            patch.object(real_st, "logout", logout),
            patch.object(real_st, "Page", side_effect=page),
            patch.object(real_st, "navigation", side_effect=navigation),
            patch(f"{API_MODULE}._server_module_available", return_value=False),
            patch(f"{API_MODULE}.get_server_settings", return_value={}),
            patch(f"{API_MODULE}.api_get", return_value=[]),
            patch("logging_config.configure_logging"),
        ):
            _remove_main_module()
            import client.app.main  # noqa: F401

            pages[-1][0][0]()
            logout.assert_called_once_with()

        assert pages[-1][1] == {"title": "Sign out", "icon": "🔓"}
        assert pages[-1][0][0].__name__ == "sign_out"
        sidebar.button.assert_not_called()

    def test_split_pod_retries_on_subsequent_rerun(self):
        """In split client images `_server_module_available()` is False, so
        the inner spawn-and-retry block is skipped. A transient first
        /settings failure must not be cached as a permanent None — the next
        Streamlit rerun has to retry once the remote server pod becomes
        ready. Otherwise the UI is stuck on the connection error until the
        session is reset."""
        state = AttrDict({"optimizer_client": "test-split"})
        valid_settings = {"database_configs": [], "model_configs": [], "client_settings": {}}

        # First rerun: remote server still booting.
        with patch(f"{API_MODULE}._server_module_available", return_value=False):
            _, mock_start = _import_main(state, get_settings_side_effect=[None])
        mock_start.assert_not_called()
        assert state.get("settings") is None

        # Second rerun (simulated by re-importing main against the same
        # session state): the remote server is now answering /settings.
        with patch(f"{API_MODULE}._server_module_available", return_value=False):
            mock_get2, mock_start2 = _import_main(state, get_settings_side_effect=[valid_settings])
        mock_start2.assert_not_called()
        assert state.get("settings") == valid_settings, (
            "second rerun must retry the connection; the previous failed "
            "attempt was cached and the UI would stay stuck on the error."
        )
        assert mock_get2.call_count == 1
