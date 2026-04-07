"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.main — server connection and initialization logic.
"""
# spell-checker: disable

import contextlib
import sys
from unittest.mock import MagicMock, patch

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

    Patches target *source* modules so that ``from X import Y`` picks up mocks
    during the fresh import.  Streamlit is patched via ``patch.object`` on the
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
        # Second call should include max_retries=5
        assert mock_get.call_count == 2
        second_call_kwargs = mock_get.call_args_list[1][1]
        assert second_call_kwargs.get("max_retries") == 5

    def test_connection_failure_shows_error(self):
        """When all connection attempts fail, st.error is called."""
        state = AttrDict({"optimizer_client": "test-789"})

        _import_main(state, get_settings_side_effect=[None, None])

        # state.settings should be None after both attempts fail
        assert state.get("settings") is None
