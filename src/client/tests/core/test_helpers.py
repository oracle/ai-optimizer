"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.core.helpers
"""
# spell-checker: disable

from unittest.mock import patch

import httpx
import pytest

from client.tests.conftest import AttrDict, base_test_settings

MODULE = "client.app.core.helpers"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_state(extra=None):
    """Minimal session state for helpers tests."""
    data = AttrDict(
        {
            "settings": base_test_settings(prompt_configs=[]),
            "optimizer_client": "test-client",
        }
    )
    if extra:
        data.update(extra)
    return data


def _http_error(status_code=400, json_body=None, content=None):
    """Build an httpx.HTTPStatusError for testing."""
    body = content
    if body is None and json_body is not None:
        import json

        body = json.dumps(json_body).encode()
    elif body is None:
        body = b""
    resp = httpx.Response(
        status_code=status_code,
        request=httpx.Request("GET", "http://test"),
        content=body,
        headers={"content-type": "application/json"} if json_body else {},
    )
    return httpx.HTTPStatusError("error", request=resp.request, response=resp)


# ---------------------------------------------------------------------------
# state_configs_lookup
# ---------------------------------------------------------------------------
class TestStateConfigsLookup:
    """Tests for state_configs_lookup."""

    def test_basic_lookup(self):
        """Verify basic lookup returns configs keyed by the specified field."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll"},
            {"id": "m2", "type": "embed"},
        ]
        with patch(f"{MODULE}.state", state):
            from client.app.core.helpers import state_configs_lookup

            result = state_configs_lookup("model_configs", "id")
        assert "m1" in result
        assert "m2" in result
        assert result["m1"]["type"] == "ll"

    def test_with_section_filter(self):
        """Verify section parameter filters to the specified sub-key."""
        state = _make_state()
        state["settings"]["database_configs"] = {
            "postgres": [{"alias": "pg1"}, {"alias": "pg2"}],
            "oracle": [{"alias": "ora1"}],
        }
        with patch(f"{MODULE}.state", state):
            from client.app.core.helpers import state_configs_lookup

            result = state_configs_lookup("database_configs", "alias", section="postgres")
        assert "pg1" in result
        assert "pg2" in result
        assert "ora1" not in result

    def test_missing_key_skipped(self):
        """Verify entries without the lookup key are silently skipped."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1"},
            {"name": "no-id"},
        ]
        with patch(f"{MODULE}.state", state):
            from client.app.core.helpers import state_configs_lookup

            result = state_configs_lookup("model_configs", "id")
        assert len(result) == 1
        assert "m1" in result

    def test_empty_configs(self):
        """Verify an empty config list returns an empty dict."""
        state = _make_state()
        state["settings"]["model_configs"] = []
        with patch(f"{MODULE}.state", state):
            from client.app.core.helpers import state_configs_lookup

            result = state_configs_lookup("model_configs", "id")
        assert result == {}


# ---------------------------------------------------------------------------
# selectbox_index
# ---------------------------------------------------------------------------
class TestSelectboxIndex:
    """Tests for selectbox_index."""

    def test_value_found(self):
        """Verify the correct index is returned when the value exists."""
        from client.app.core.helpers import selectbox_index

        assert selectbox_index(["a", "b", "c"], "b") == 1

    def test_value_not_found_returns_default(self):
        """Verify the default index is returned when the value is absent."""
        from client.app.core.helpers import selectbox_index

        assert selectbox_index(["a", "b"], "z") == 0

    def test_custom_default(self):
        """Verify a custom default value is respected when the value is absent."""
        from client.app.core.helpers import selectbox_index

        assert selectbox_index(["a", "b"], "z", default=99) == 99

    def test_empty_list(self):
        """Verify an empty list returns the default index."""
        from client.app.core.helpers import selectbox_index

        assert selectbox_index([], "a") == 0


# ---------------------------------------------------------------------------
# refresh_settings
# ---------------------------------------------------------------------------
class TestRefreshSettings:
    """Tests for refresh_settings."""

    def test_updates_state_and_clears_runtime(self):
        """Verify settings are updated and runtime keys are cleared."""
        state = _make_state({"mcp_configs": {"tools": []}, "runtime_foo": "bar"})
        server_data = {"database_configs": [], "client_settings": {}}
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_server_settings", return_value=server_data) as mock_get,
        ):
            from client.app.core.helpers import refresh_settings

            refresh_settings()
        mock_get.assert_called_once_with(client="test-client")
        assert state["settings"] == server_data
        assert "mcp_configs" not in state
        assert "runtime_foo" not in state

    def test_skip_clear_runtime(self):
        """Verify runtime keys are preserved when clear_runtime is False."""
        state = _make_state({"runtime_keep": "yes"})
        server_data = {"ok": True}
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_server_settings", return_value=server_data),
        ):
            from client.app.core.helpers import refresh_settings

            refresh_settings(clear_runtime=False)
        assert "runtime_keep" in state

    def test_none_return_noop(self):
        """Verify a None server response leaves settings unchanged."""
        state = _make_state()
        original_settings = state["settings"].copy()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_server_settings", return_value=None),
        ):
            from client.app.core.helpers import refresh_settings

            refresh_settings()
        assert state["settings"] == original_settings

    def test_clears_per_profile_cache_flags(self):
        """Refresh invalidates per-profile sensitive-field cache flags."""
        state = _make_state({"_oci_sensitive_loaded": True, "_template_export": {"x": 1}})
        server_data = {"database_configs": [], "client_settings": {}}
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_server_settings", return_value=server_data),
        ):
            from client.app.core.helpers import refresh_settings

            refresh_settings()
        assert not state.get("_oci_sensitive_loaded")
        assert "_template_export" not in state


# ---------------------------------------------------------------------------
# sync_client_setting
# ---------------------------------------------------------------------------
class TestSyncClientSetting:
    """Tests for sync_client_setting."""

    def test_happy_path(self):
        """Verify a successful PUT updates client settings from the response."""
        state = _make_state()
        state["settings"]["client_settings"] = {}
        updated = {"database": {"alias": "db1"}}
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put", return_value=updated) as mock_put,
        ):
            from client.app.core.helpers import sync_client_setting

            sync_client_setting("database", "alias", "db1")
        mock_put.assert_called_once()
        assert state["settings"]["client_settings"] == updated

    def test_http_error_swallowed(self):
        """Verify an HTTP error is swallowed and the value is set locally."""
        state = _make_state()
        state["settings"]["client_settings"] = {}
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put", side_effect=_http_error(500)),
        ):
            from client.app.core.helpers import sync_client_setting

            sync_client_setting("database", "alias", "db1")
        # Should not raise, value still set locally
        assert state["settings"]["client_settings"]["database"]["alias"] == "db1"

    def test_creates_nested_key(self):
        """Verify a nested key structure is created in client settings."""
        state = _make_state()
        state["settings"]["client_settings"] = {}
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put", return_value={"oci": {"profile": "DEFAULT"}}),
        ):
            from client.app.core.helpers import sync_client_setting

            sync_client_setting("oci", "profile", "DEFAULT")
        assert state["settings"]["client_settings"] == {"oci": {"profile": "DEFAULT"}}


# ---------------------------------------------------------------------------
# clear_runtime_state
# ---------------------------------------------------------------------------
class TestClearRuntimeState:
    """Tests for clear_runtime_state."""

    def test_removes_runtime_keys(self):
        """Verify keys prefixed with runtime_ are removed from state."""
        state = _make_state({"runtime_a": 1, "runtime_b": 2, "keep": 3})
        with patch(f"{MODULE}.state", state):
            from client.app.core.helpers import clear_runtime_state

            clear_runtime_state()
        assert "runtime_a" not in state
        assert "runtime_b" not in state
        assert state["keep"] == 3

    def test_empty_state(self):
        """Verify clearing an empty state does not error."""
        state = _make_state()
        with patch(f"{MODULE}.state", state):
            from client.app.core.helpers import clear_runtime_state

            clear_runtime_state()
        # No error, settings preserved
        assert "settings" in state


# ---------------------------------------------------------------------------
# extract_error_detail
# ---------------------------------------------------------------------------
class TestExtractErrorDetail:
    """Tests for extract_error_detail."""

    def test_json_detail_extraction(self):
        """Verify the detail field is extracted from a JSON error response."""
        from client.app.core.helpers import extract_error_detail

        exc = _http_error(400, json_body={"detail": "Bad input"})
        assert extract_error_detail(exc) == "Bad input"

    def test_fallback_to_str(self):
        """Verify a non-JSON error falls back to a string representation."""
        from client.app.core.helpers import extract_error_detail

        exc = _http_error(500, content=b"")
        result = extract_error_detail(exc)
        assert "error" in result.lower() or "500" in result


# ---------------------------------------------------------------------------
# bool_to_emoji
# ---------------------------------------------------------------------------
class TestBoolToEmoji:
    """Tests for bool_to_emoji."""

    def test_true(self):
        """Verify True returns the check-mark emoji."""
        from client.app.core.helpers import bool_to_emoji

        assert bool_to_emoji(True) == "✅"

    def test_false(self):
        """Verify False returns the cross-mark emoji."""
        from client.app.core.helpers import bool_to_emoji

        assert bool_to_emoji(False) == "❌"


# ---------------------------------------------------------------------------
# update_client_settings
# ---------------------------------------------------------------------------
class TestUpdateClientSettings:
    """Tests for update_client_settings."""

    def test_success_returns_result(self, mock_st):
        """Verify a successful update returns the result and updates state."""
        state = _make_state()
        updated = {"ll_model": {"id": "m1"}}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put", return_value=updated),
        ):
            from client.app.core.helpers import update_client_settings

            result = update_client_settings({"ll_model": {"id": "m1"}})
        assert result == updated
        assert state["settings"]["client_settings"] == updated

    def test_error_returns_none_and_toasts(self, mock_st):
        """Verify an HTTP error returns None and shows a toast."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put", side_effect=_http_error(422, {"detail": "invalid"})),
        ):
            from client.app.core.helpers import update_client_settings

            result = update_client_settings({"bad": "data"})
        assert result is None
        mock_st.toast.assert_called_once()


# ---------------------------------------------------------------------------
# load_chat_history
# ---------------------------------------------------------------------------
class TestLoadChatHistory:
    """Tests for load_chat_history."""

    def test_success(self):
        """Verify a successful response returns the messages list."""
        messages = [{"role": "user", "content": "hello"}]
        with patch(f"{MODULE}.api_get", return_value={"messages": messages}):
            from client.app.core.helpers import load_chat_history

            result = load_chat_history("client-1")
        assert result == messages

    def test_http_error_returns_empty_list(self):
        """Verify a connection error returns an empty list."""
        with patch(f"{MODULE}.api_get", side_effect=httpx.ConnectError("fail")):
            from client.app.core.helpers import load_chat_history

            result = load_chat_history("client-1")
        assert result == []

    def test_extra_header_passed(self):
        """Verify the client header is passed to the API call."""
        with patch(f"{MODULE}.api_get", return_value={"messages": []}) as mock_get:
            from client.app.core.helpers import load_chat_history

            load_chat_history("my-client")
        mock_get.assert_called_once_with("chat/history", extra_headers={"client": "my-client"})


# ---------------------------------------------------------------------------
# enabled_models_lookup
# ---------------------------------------------------------------------------
class TestEnabledModelsLookup:
    """Tests for enabled_models_lookup."""

    def test_correct_type_and_enabled(self):
        """Verify only enabled models of the correct type are returned."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": True, "provider": "openai"},
            {"id": "m2", "type": "embed", "enabled": True, "provider": "oci"},
        ]
        with patch(f"{MODULE}.state", state):
            from client.app.core.helpers import enabled_models_lookup

            result = enabled_models_lookup("ll")
        assert "openai/m1" in result
        assert len(result) == 1

    def test_excludes_disabled(self):
        """Verify disabled models are excluded from results."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "ll", "enabled": False, "provider": "openai"},
        ]
        with patch(f"{MODULE}.state", state):
            from client.app.core.helpers import enabled_models_lookup

            result = enabled_models_lookup("ll")
        assert result == {}

    def test_excludes_wrong_type(self):
        """Verify models of a different type are excluded from results."""
        state = _make_state()
        state["settings"]["model_configs"] = [
            {"id": "m1", "type": "embed", "enabled": True, "provider": "oci"},
        ]
        with patch(f"{MODULE}.state", state):
            from client.app.core.helpers import enabled_models_lookup

            result = enabled_models_lookup("ll")
        assert result == {}

    def test_empty_configs(self):
        """Verify an empty model config list returns an empty dict."""
        state = _make_state()
        state["settings"]["model_configs"] = []
        with patch(f"{MODULE}.state", state):
            from client.app.core.helpers import enabled_models_lookup

            result = enabled_models_lookup("ll")
        assert result == {}


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------
class TestBuildPayload:
    """Tests for build_payload."""

    def test_excludes_none_values(self):
        """Verify None values are excluded from the payload."""
        from client.app.core.helpers import build_payload

        result = build_payload({"a": 1, "b": None, "c": "x"})
        assert result == {"a": 1, "c": "x"}

    def test_all_none(self):
        """Verify an all-None input returns an empty dict."""
        from client.app.core.helpers import build_payload

        assert build_payload({"a": None, "b": None}) == {}

    def test_empty_dict(self):
        """Verify an empty input returns an empty dict."""
        from client.app.core.helpers import build_payload

        assert build_payload({}) == {}

    def test_keeps_falsy_non_none(self):
        """Verify falsy non-None values like 0, empty string, and False are kept."""
        from client.app.core.helpers import build_payload

        result = build_payload({"a": 0, "b": "", "c": False})
        assert result == {"a": 0, "b": "", "c": False}
