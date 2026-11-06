"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.main — server connection and initialization logic.
"""
# spell-checker: disable

import contextlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from client.app.core.local_bootstrap import LocalCoreConfig, LocalCoreSource, ResolvedLocalCore
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


def _core_config() -> LocalCoreConfig:
    return LocalCoreConfig(
        username="AI_OPTIMIZER",
        password=SecretStr("secret"),
        dsn="localhost:1521/FREEPDB1",
    )


def _import_main(
    state,
    get_settings_side_effect,
    *,
    resolved=None,
    submitted=None,
    server_started=True,
    config_path=None,
):
    """Import client.app.main with all module-level dependencies mocked.

    Mock target *source* modules so that ``from X import Y`` picks up mocks
    during the fresh import.  Streamlit is replaced via ``patch.object`` on the
    real module so ``from streamlit import session_state as state`` binds to
    our AttrDict.
    """
    import streamlit as real_st

    mock_get_settings = MagicMock(side_effect=get_settings_side_effect)
    mock_start = MagicMock(return_value=server_started)
    mock_api_get = MagicMock(return_value=[])
    mock_persist = MagicMock()
    mock_stop = MagicMock()
    mock_display_setup = MagicMock(return_value=submitted)
    resolved = resolved or ResolvedLocalCore(config=_core_config(), source=LocalCoreSource.ENVIRONMENT)

    _remove_main_module()

    with (  # noqa: SIM117
        # Streamlit session_state binding
        patch.object(real_st, "session_state", state),
        # Prevent real HTTP calls — patch at the SOURCE module
        patch(f"{API_MODULE}.get_server_settings", mock_get_settings),
        patch(f"{API_MODULE}.start_server", mock_start),
        patch(f"{API_MODULE}.api_get", mock_api_get),
        patch(f"{API_MODULE}.stop_server", mock_stop),
        patch("client.app.core.local_bootstrap.resolve_local_core", return_value=resolved),
        patch("client.app.core.local_bootstrap.local_core_config_path", return_value=config_path),
        patch("client.app.core.local_bootstrap.persist_local_core", mock_persist),
        patch("client.app.content.local_database_setup.display_local_database_setup", mock_display_setup),
        patch.object(real_st, "stop", side_effect=SystemExit),
        patch.object(real_st, "rerun", side_effect=SystemExit),
        # Suppress logging config
        patch("logging_config.configure_logging"),
    ):
        with contextlib.suppress(SystemExit):
            import client.app.main  # noqa: F401

    return mock_get_settings, mock_start, mock_stop, mock_persist, mock_display_setup


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

        _, mock_start, _, _, _ = _import_main(state, get_settings_side_effect=[valid_settings])

        mock_start.assert_not_called()
        assert "settings" in state

    def test_connection_retry_after_start(self):
        """When first connection fails, starts server and retries."""
        state = AttrDict({"optimizer_client": "test-456"})
        valid_settings = {"database_configs": [], "model_configs": [], "client_settings": {}}

        mock_get, mock_start, _, _, _ = _import_main(state, get_settings_side_effect=[None, valid_settings])

        mock_start.assert_called_once_with(_core_config().child_environment())
        assert mock_get.call_count == 2

    def test_connection_failure_shows_error(self):
        """When all connection attempts fail, st.error is called."""
        state = AttrDict({"optimizer_client": "test-789"})

        with patch(f"{API_MODULE}._server_module_available", return_value=False):
            _import_main(state, get_settings_side_effect=[None])

        # state.settings should be None after both attempts fail
        assert state.get("settings") is None

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
            _, mock_start, _, _, _ = _import_main(state, get_settings_side_effect=[None])
        mock_start.assert_not_called()
        assert state.get("settings") is None

        # Second rerun (simulated by re-importing main against the same
        # session state): the remote server is now answering /settings.
        with patch(f"{API_MODULE}._server_module_available", return_value=False):
            mock_get2, mock_start2, _, _, _ = _import_main(state, get_settings_side_effect=[valid_settings])
        mock_start2.assert_not_called()
        assert state.get("settings") == valid_settings, (
            "second rerun must retry the connection; the previous failed "
            "attempt was cached and the UI would stay stuck on the error."
        )
        assert mock_get2.call_count == 1

    def test_missing_local_core_shows_only_setup(self):
        state = AttrDict({"optimizer_client": "test-setup"})
        missing = ResolvedLocalCore(config=None, source=LocalCoreSource.MISSING)

        _, mock_start, _, mock_persist, mock_display = _import_main(
            state,
            get_settings_side_effect=[None],
            resolved=missing,
        )

        mock_display.assert_called_once()
        mock_start.assert_not_called()
        mock_persist.assert_not_called()
        assert state.get("settings") is None
        assert "optimizer_help" not in state

    def test_valid_setup_starts_then_retains_in_memory(self):
        state = AttrDict({"optimizer_client": "test-setup-valid"})
        missing = ResolvedLocalCore(config=None, source=LocalCoreSource.MISSING)
        submitted = _core_config()

        _, mock_start, _, mock_persist, _ = _import_main(
            state,
            get_settings_side_effect=[None],
            resolved=missing,
            submitted=submitted,
        )

        mock_start.assert_called_once_with(submitted.child_environment())
        assert state.get("_local_core_config") is submitted
        mock_persist.assert_not_called()
        assert state.get("_clear_local_core_secrets") is True

    def test_valid_container_setup_persists_to_configured_volume(self):
        state = AttrDict({"optimizer_client": "test-container-valid"})
        missing = ResolvedLocalCore(config=None, source=LocalCoreSource.MISSING)
        submitted = _core_config()
        config_path = Path("/app/data/core.json")

        _, mock_start, _, mock_persist, _ = _import_main(
            state,
            get_settings_side_effect=[None],
            resolved=missing,
            submitted=submitted,
            config_path=config_path,
        )

        mock_start.assert_called_once_with(submitted.child_environment())
        mock_persist.assert_called_once_with(submitted, config_path)

    def test_failed_setup_is_not_retained(self):
        state = AttrDict({"optimizer_client": "test-setup-invalid"})
        missing = ResolvedLocalCore(config=None, source=LocalCoreSource.MISSING)

        _, mock_start, mock_stop, mock_persist, _ = _import_main(
            state,
            get_settings_side_effect=[None],
            resolved=missing,
            submitted=_core_config(),
            server_started=False,
        )

        mock_start.assert_called_once()
        mock_stop.assert_called_once_with()
        mock_persist.assert_not_called()
        assert state.get("_local_core_config") is None
        assert state.get("_local_core_edit") is True
        assert "failed" in state.get("_local_core_setup_error", "").lower()

    def test_memory_configuration_restarts_without_setup_form(self):
        state = AttrDict({"optimizer_client": "test-memory"})
        valid_settings = {"database_configs": [], "model_configs": [], "client_settings": {}}
        retained = ResolvedLocalCore(config=_core_config(), source=LocalCoreSource.MEMORY)

        mock_get, mock_start, _, mock_persist, mock_display = _import_main(
            state,
            get_settings_side_effect=[None, valid_settings],
            resolved=retained,
        )

        mock_start.assert_called_once_with(_core_config().child_environment())
        mock_display.assert_not_called()
        mock_persist.assert_not_called()
        assert mock_get.call_count == 2

    def test_memory_configuration_can_be_explicitly_edited(self):
        state = AttrDict({"optimizer_client": "test-edit", "_local_core_edit": True})
        retained = ResolvedLocalCore(config=_core_config(), source=LocalCoreSource.MEMORY)

        _, mock_start, _, mock_persist, mock_display = _import_main(
            state,
            get_settings_side_effect=[None],
            resolved=retained,
        )

        mock_display.assert_called_once()
        assert mock_display.call_args.kwargs["current"] == retained.config
        mock_start.assert_not_called()
        mock_persist.assert_not_called()
