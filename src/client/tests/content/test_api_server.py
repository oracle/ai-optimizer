"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.api_server (functions only — not module-level page code)
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

import pytest

from client.tests.conftest import AttrDict

MODULE = "client.app.content.api_server"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_state(extra=None):
    """Build a minimal AttrDict mimicking session_state."""
    data = AttrDict(
        {
            "optimizer_client": "test-client",
        }
    )
    if extra:
        data.update(extra)
    return data


# ---------------------------------------------------------------------------
# _advertised_api_base_url
# ---------------------------------------------------------------------------
class TestAdvertisedApiBaseUrl:
    """Tests for the API URL displayed on the API Server page."""

    def _settings(self, **overrides):
        settings = MagicMock()
        settings.server_url_prefix = overrides.get("server_url_prefix", "")
        settings.server_port = overrides.get("server_port", 8000)
        settings.server_address = overrides.get("server_address", "127.0.0.1")
        return settings

    def test_local_internal_url_uses_browser_host_for_display(self):
        """Loopback internal URLs are converted to a browser-reachable host."""
        settings = self._settings(server_address="0.0.0.0")
        with (
            patch(f"{MODULE}.client_settings", settings),
            patch(f"{MODULE}._base_url", return_value="https://127.0.0.1:8000/v1"),
        ):
            from client.app.content.api_server import _advertised_api_base_url

            result = _advertised_api_base_url("https://release-ai.appoci.oraclecorp.com:8501/api_server")
        assert result == "https://release-ai.appoci.oraclecorp.com:8000/v1"

    def test_loopback_bind_does_not_advertise_browser_host(self):
        """A loopback-bound server is not externally reachable just because the UI is."""
        settings = self._settings(server_address="127.0.0.1")
        with (
            patch(f"{MODULE}.client_settings", settings),
            patch(f"{MODULE}._base_url", return_value="https://127.0.0.1:8000/v1"),
        ):
            from client.app.content.api_server import _advertised_api_base_url

            result = _advertised_api_base_url("https://release-ai.appoci.oraclecorp.com:8501/api_server")
        assert result == "https://127.0.0.1:8000/v1"

    def test_external_internal_url_is_displayed_as_is(self):
        """Already external API URLs do not need inference."""
        settings = self._settings()
        with (
            patch(f"{MODULE}.client_settings", settings),
            patch(f"{MODULE}._base_url", return_value="https://api.example.com/v1"),
        ):
            from client.app.content.api_server import _advertised_api_base_url

            assert _advertised_api_base_url("https://ui.example.com:8501/api_server") == "https://api.example.com/v1"

    def test_local_browser_url_keeps_internal_url(self):
        """Local development should still display the local API URL."""
        settings = self._settings()
        with (
            patch(f"{MODULE}.client_settings", settings),
            patch(f"{MODULE}._base_url", return_value="http://127.0.0.1:8000/v1"),
        ):
            from client.app.content.api_server import _advertised_api_base_url

            result = _advertised_api_base_url("http://localhost:8501/api_server")
        assert result == "http://127.0.0.1:8000/v1"


# ---------------------------------------------------------------------------
# _copy_to_server
# ---------------------------------------------------------------------------
class TestCopyToServer:
    """Tests for _copy_to_server."""

    def test_calls_api_post(self, mock_st):
        """Calls api_post with correct copy URL."""
        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_post") as mock_post,
        ):
            from client.app.content.api_server import _copy_to_server

            _copy_to_server()
        mock_post.assert_called_once_with("settings/server/copy?client=test-client")

    def test_handles_exception(self, mock_st):
        """Exception from api_post is caught and shown as error."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", side_effect=Exception("fail")),
        ):
            from client.app.content.api_server import _copy_to_server

            _copy_to_server()  # Should not raise
        mock_st.error.assert_called_once()

    def test_constructs_url_with_client(self, mock_st):
        """URL includes the optimizer_client name."""
        state = _make_state()
        state["optimizer_client"] = "my-custom-client"
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post") as mock_post,
        ):
            from client.app.content.api_server import _copy_to_server

            _copy_to_server()
        assert "my-custom-client" in mock_post.call_args[0][0]

    def test_no_error_on_success(self, mock_st):
        """Successful copy does not call st.error."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post"),
        ):
            from client.app.content.api_server import _copy_to_server

            _copy_to_server()
        mock_st.error.assert_not_called()


# ---------------------------------------------------------------------------
# _server_activity
# ---------------------------------------------------------------------------
class TestServerActivity:
    """Tests for _server_activity."""

    def _call(self, mock_st, history):
        """Call the unwrapped _server_activity with mocked dependencies."""
        mock_st.chat_message.return_value = MagicMock()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.load_chat_history", return_value=history),
        ):
            from client.app.content.api_server import _server_activity

            # Access the unwrapped function directly for the unit test
            fn = getattr(_server_activity, "__wrapped__", _server_activity)
            fn()

    def test_no_history(self, mock_st):
        """Empty history shows 'No Server Activity'."""
        self._call(mock_st, [])
        mock_st.write.assert_any_call("No Server Activity")
        mock_st.chat_message.assert_not_called()

    def test_ai_message(self, mock_st):
        """AI role message renders as 'ai' chat message."""
        self._call(mock_st, [{"role": "ai", "content": "hello"}])
        mock_st.chat_message.assert_called_with("ai")

    def test_human_message(self, mock_st):
        """Human role message renders as 'human' chat message."""
        self._call(mock_st, [{"role": "human", "content": "hi"}])
        mock_st.chat_message.assert_called_with("human")

    def test_alternate_roles(self, mock_st):
        """'assistant' and 'user' roles map to 'ai' and 'human' chat messages."""
        history = [
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "question"},
        ]
        self._call(mock_st, history)
        calls = [c[0][0] for c in mock_st.chat_message.call_args_list]
        assert "ai" in calls
        assert "human" in calls
