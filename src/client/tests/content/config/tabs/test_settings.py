"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.config.tabs.settings
"""
# spell-checker: disable

import io
import json
import zipfile
from unittest.mock import MagicMock, patch

import httpx
import pytest

from client.tests.conftest import AttrDict, Rerun

MODULE = "client.app.content.config.tabs.settings"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings_state(extra=None):
    """Build a minimal session state dict for settings tests."""
    data = {
        "settings": {
            "log_level": "INFO",
            "database_configs": [],
            "model_configs": [],
            "oci_configs": [],
            "prompt_configs": [],
            "client_settings": {"database": {}},
        },
    }
    if extra:
        data.update(extra)
    return data


# ---------------------------------------------------------------------------
# _fetch_settings
# ---------------------------------------------------------------------------


class TestFetchSettings:
    """Tests for the _fetch_settings function."""

    def test_returns_api_result_when_available(self, mock_st):
        """When the API returns data, _fetch_settings returns that data."""
        api_data = {"log_level": "DEBUG"}
        state = AttrDict(
            {"settings": {"log_level": "INFO"}, "runtime_sensitive_settings": False, "optimizer_client": "test-client"}
        )

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_server_settings", return_value=api_data) as mock_get,
        ):
            from client.app.content.config.tabs.settings import _fetch_settings

            result = _fetch_settings()

        assert result == api_data
        mock_get.assert_called_once_with(client="test-client", include_sensitive=False)

    def test_falls_back_to_state_when_api_returns_none(self, mock_st):
        """When the API returns None, falls back to state.settings."""
        fallback = {"log_level": "INFO"}
        state = AttrDict({"settings": fallback, "optimizer_client": "test-client"})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_server_settings", return_value=None),
        ):
            from client.app.content.config.tabs.settings import _fetch_settings

            result = _fetch_settings()

        assert result is fallback

    def test_include_sensitive_defaults_false(self, mock_st):
        """When runtime_sensitive_settings is absent, include_sensitive defaults to False."""
        state = AttrDict({"settings": {}, "optimizer_client": "test-client"})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_server_settings", return_value={}) as mock_get,
        ):
            from client.app.content.config.tabs.settings import _fetch_settings

            _fetch_settings()

        mock_get.assert_called_once_with(client="test-client", include_sensitive=False)

    def test_include_sensitive_true_when_set(self, mock_st):
        """When runtime_sensitive_settings is True, include_sensitive=True."""
        state = AttrDict({"settings": {}, "runtime_sensitive_settings": True, "optimizer_client": "test-client"})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_server_settings", return_value={}) as mock_get,
        ):
            from client.app.content.config.tabs.settings import _fetch_settings

            _fetch_settings()

        mock_get.assert_called_once_with(client="test-client", include_sensitive=True)


# ---------------------------------------------------------------------------
# _get_settings_data
# ---------------------------------------------------------------------------


class TestGetSettingsData:
    """Tests for the _get_settings_data function."""

    def test_returns_valid_json_string(self, mock_st):
        """Returns a JSON string that can be parsed back to the original data."""
        api_data = {"log_level": "DEBUG", "items": [1, 2]}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._fetch_settings", return_value=api_data),
        ):
            from client.app.content.config.tabs.settings import _get_settings_data

            result = _get_settings_data()

        assert json.loads(result) == api_data

    def test_json_is_indented(self, mock_st):
        """The returned JSON uses indent=2."""
        api_data = {"a": 1}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._fetch_settings", return_value=api_data),
        ):
            from client.app.content.config.tabs.settings import _get_settings_data

            result = _get_settings_data()

        assert result == json.dumps(api_data, indent=2)


# ---------------------------------------------------------------------------
# _compare_prompt_configs  (pure function)
# ---------------------------------------------------------------------------


class TestComparePromptConfigs:
    """Tests for the _compare_prompt_configs function."""

    def test_identical_prompts_returns_empty(self):
        """Identical prompt lists produce an empty result."""
        from client.app.content.config.tabs.settings import _compare_prompt_configs

        prompts = [{"name": "p1", "text": "Hello"}]
        assert not _compare_prompt_configs(prompts, list(prompts))

    def test_text_differs(self):
        """Different text values produce a 'Text differs' status."""
        from client.app.content.config.tabs.settings import _compare_prompt_configs

        current = [{"name": "p1", "text": "A"}]
        uploaded = [{"name": "p1", "text": "B"}]
        result = _compare_prompt_configs(current, uploaded)

        assert "p1" in result
        assert result["p1"]["status"] == "Text differs"
        assert result["p1"]["current"] == current[0]
        assert result["p1"]["uploaded"] == uploaded[0]

    def test_missing_in_current(self):
        """A prompt only in uploaded produces 'Missing in Current'."""
        from client.app.content.config.tabs.settings import _compare_prompt_configs

        result = _compare_prompt_configs([], [{"name": "p2", "text": "X"}])

        assert result["p2"]["status"] == "Missing in Current"
        assert result["p2"]["uploaded"] == {"name": "p2", "text": "X"}

    def test_missing_in_uploaded(self):
        """A prompt only in current produces 'Missing in Uploaded'."""
        from client.app.content.config.tabs.settings import _compare_prompt_configs

        result = _compare_prompt_configs([{"name": "p3", "text": "Y"}], [])

        assert result["p3"]["status"] == "Missing in Uploaded"
        assert result["p3"]["current"] == {"name": "p3", "text": "Y"}

    def test_items_without_name_key_skipped(self):
        """Items missing the 'name' key are ignored."""
        from client.app.content.config.tabs.settings import _compare_prompt_configs

        result = _compare_prompt_configs([{"text": "no name"}], [{"text": "no name"}])
        assert not result

    def test_mixed_differences(self):
        """All three categories can appear in a single comparison."""
        from client.app.content.config.tabs.settings import _compare_prompt_configs

        current = [
            {"name": "same", "text": "ok"},
            {"name": "changed", "text": "A"},
            {"name": "only_current", "text": "C"},
        ]
        uploaded = [
            {"name": "same", "text": "ok"},
            {"name": "changed", "text": "B"},
            {"name": "only_uploaded", "text": "U"},
        ]
        result = _compare_prompt_configs(current, uploaded)

        assert "same" not in result
        assert result["changed"]["status"] == "Text differs"
        assert result["only_current"]["status"] == "Missing in Uploaded"
        assert result["only_uploaded"]["status"] == "Missing in Current"


# ---------------------------------------------------------------------------
# _compare_keyed_configs
# ---------------------------------------------------------------------------


class TestCompareKeyedConfigs:
    """Tests for the _compare_keyed_configs function."""

    def test_matching_keys_calls_compute_diff(self):
        """When both sides have the same key, _compute_diff is called."""
        from client.app.content.config.tabs.settings import _compare_keyed_configs

        diffs = {"Value Mismatch": {}, "Missing in Uploaded": {}, "Missing in Current": {}}
        current = [{"alias": "db1", "user": "a"}]
        uploaded = [{"alias": "db1", "user": "b"}]

        with patch(f"{MODULE}._compute_diff") as mock_diff:
            _compare_keyed_configs(current, uploaded, "database_configs", diffs, lambda i: i["alias"])

        mock_diff.assert_called_once_with(current[0], uploaded[0], "database_configs.db1", diffs)

    def test_only_in_current(self):
        """A key only in current is reported as Missing in Uploaded."""
        from client.app.content.config.tabs.settings import _compare_keyed_configs

        diffs = {"Value Mismatch": {}, "Missing in Uploaded": {}, "Missing in Current": {}}
        _compare_keyed_configs([{"alias": "db1"}], [], "db", diffs, lambda i: i["alias"])

        assert "db.db1" in diffs["Missing in Uploaded"]

    def test_only_in_uploaded(self):
        """A key only in uploaded is reported as Missing in Current."""
        from client.app.content.config.tabs.settings import _compare_keyed_configs

        diffs = {"Value Mismatch": {}, "Missing in Uploaded": {}, "Missing in Current": {}}
        _compare_keyed_configs([], [{"alias": "db2"}], "db", diffs, lambda i: i["alias"])

        assert "db.db2" in diffs["Missing in Current"]

    def test_string_key_function_label(self):
        """A string key produces a simple path label."""
        from client.app.content.config.tabs.settings import _compare_keyed_configs

        diffs = {"Value Mismatch": {}, "Missing in Uploaded": {}, "Missing in Current": {}}
        _compare_keyed_configs([], [{"alias": "mydb"}], "root", diffs, lambda i: i["alias"])

        assert "root.mydb" in diffs["Missing in Current"]

    def test_tuple_key_function_label(self):
        """A tuple key produces a dot-joined path label (model_configs pattern)."""
        from client.app.content.config.tabs.settings import _compare_keyed_configs

        diffs = {"Value Mismatch": {}, "Missing in Uploaded": {}, "Missing in Current": {}}
        item = {"id": "gpt4", "provider": "openai"}
        _compare_keyed_configs([], [item], "model_configs", diffs, lambda i: (i["id"], i["provider"]))

        assert "model_configs.gpt4.openai" in diffs["Missing in Current"]

    def test_tolerates_missing_alias_in_uploaded(self):
        """Legacy/hand-edited entries missing the identity field bucket as unkeyed, no crash."""
        from client.app.content.config.tabs.settings import _compare_keyed_configs

        diffs = {"Value Mismatch": {}, "Missing in Uploaded": {}, "Missing in Current": {}}
        # Legacy v2.0.3 shape — `name`/`user` instead of `alias`/`username`.
        legacy = [{"name": "DEFAULT", "user": "admin"}]

        _compare_keyed_configs([], legacy, "database_configs", diffs, lambda i: i["alias"])

        assert "database_configs.<unkeyed#0>" in diffs["Missing in Current"]
        assert diffs["Missing in Current"]["database_configs.<unkeyed#0>"] == legacy[0]

    def test_tolerates_missing_alias_in_current(self):
        """Unkeyed current-side entries bucket to Missing in Uploaded."""
        from client.app.content.config.tabs.settings import _compare_keyed_configs

        diffs = {"Value Mismatch": {}, "Missing in Uploaded": {}, "Missing in Current": {}}
        legacy = [{"name": "OLD"}]

        _compare_keyed_configs(legacy, [], "database_configs", diffs, lambda i: i["alias"])

        assert "database_configs.<unkeyed#0>" in diffs["Missing in Uploaded"]

    def test_upload_legacy_config_does_not_crash(self):
        """Full _compute_diff pipeline survives a v2.0.3-shaped database_configs list."""
        from client.app.content.config.tabs.settings import _compute_diff

        current = _make_settings_state()["settings"]
        uploaded = {
            "log_level": "INFO",
            "database_configs": [{"name": "DEFAULT", "user": "admin", "dsn": "//host/svc"}],
            "model_configs": [],
            "oci_configs": [],
            "prompt_configs": [],
            "client_settings": {"database": {}},
        }

        # Must not raise KeyError: 'alias'
        result = _compute_diff(current, uploaded)

        assert isinstance(result, dict)
        assert "Missing in Current" in result
        assert any("database_configs" in k for k in result["Missing in Current"])


# ---------------------------------------------------------------------------
# _compare_dicts
# ---------------------------------------------------------------------------


class TestCompareDicts:
    """Tests for the _compare_dicts function."""

    def test_skips_client_settings_client_path(self):
        """The 'client_settings.client' path is excluded from comparisons."""
        from client.app.content.config.tabs.settings import _compute_diff

        current = {"client_settings": {"client": "A"}}
        uploaded = {"client_settings": {"client": "B"}}
        result = _compute_diff(current, uploaded)

        assert not result["Value Mismatch"]

    def test_skips_fields_ending_with_created(self):
        """Fields ending with '.created' are excluded."""
        from client.app.content.config.tabs.settings import _compute_diff

        current = {"item": {"created": "2024-01-01"}}
        uploaded = {"item": {"created": "2025-01-01"}}
        result = _compute_diff(current, uploaded)

        assert not result["Value Mismatch"]

    def test_skips_fields_ending_with_usable(self):
        """Fields ending with '.usable' are excluded."""
        from client.app.content.config.tabs.settings import _compute_diff

        current = {"item": {"usable": True}}
        uploaded = {"item": {"usable": False}}
        result = _compute_diff(current, uploaded)

        assert not result["Value Mismatch"]

    def test_skips_fields_ending_with_status(self):
        """model 'status' is runtime-only (export omits it), so a round-trip shows no false diff."""
        from client.app.content.config.tabs.settings import _compute_diff

        # Mirrors re-uploading an export: current carries runtime status; the upload omits it.
        current = {"item": {"status": "available"}}
        uploaded = {"item": {}}
        result = _compute_diff(current, uploaded)

        assert not result["Missing in Uploaded"]

    def test_prompt_configs_text_differs_maps_to_value_mismatch(self):
        """prompt_configs 'Text differs' maps to Value Mismatch category."""
        from client.app.content.config.tabs.settings import _compute_diff

        current = {"prompt_configs": [{"name": "p1", "text": "A"}]}
        uploaded = {"prompt_configs": [{"name": "p1", "text": "B"}]}
        result = _compute_diff(current, uploaded)

        assert "prompt_configs.p1" in result["Value Mismatch"]

    def test_prompt_configs_missing_in_current(self):
        """prompt_configs 'Missing in Current' maps to Missing in Current category."""
        from client.app.content.config.tabs.settings import _compute_diff

        current = {"prompt_configs": []}
        uploaded = {"prompt_configs": [{"name": "p1", "text": "X"}]}
        result = _compute_diff(current, uploaded)

        assert "prompt_configs.p1" in result["Missing in Current"]

    @pytest.mark.parametrize("config_key", ["model_configs", "database_configs", "oci_configs"])
    def test_keyed_configs_dispatched(self, config_key):
        """Keyed config lists are dispatched to _compare_keyed_configs."""
        from client.app.content.config.tabs.settings import _compute_diff

        if config_key == "model_configs":
            item_current = {"id": "m1", "provider": "openai", "val": "A"}
            item_uploaded = {"id": "m1", "provider": "openai", "val": "B"}
        elif config_key == "database_configs":
            item_current = {"alias": "db1", "val": "A"}
            item_uploaded = {"alias": "db1", "val": "B"}
        else:
            item_current = {"auth_profile": "oci1", "val": "A"}
            item_uploaded = {"auth_profile": "oci1", "val": "B"}

        current = {config_key: [item_current]}
        uploaded = {config_key: [item_uploaded]}
        result = _compute_diff(current, uploaded)

        # Should detect the value mismatch within the keyed config
        matching_keys = [k for k in result["Value Mismatch"] if k.startswith(config_key)]
        assert matching_keys

    def test_prompt_configs_missing_in_uploaded(self):
        """prompt_configs 'Missing in Uploaded' maps to Missing in Uploaded category."""
        from client.app.content.config.tabs.settings import _compute_diff

        current = {"prompt_configs": [{"name": "p1", "text": "X"}]}
        uploaded = {"prompt_configs": []}
        result = _compute_diff(current, uploaded)

        assert "prompt_configs.p1" in result["Missing in Uploaded"]

    def test_non_empty_current_key_missing_from_uploaded(self):
        """A key with a real value in current but absent from uploaded is reported."""
        from client.app.content.config.tabs.settings import _compute_diff

        current = {"log_level": "INFO", "extra": "value"}
        uploaded = {"log_level": "INFO"}
        result = _compute_diff(current, uploaded)

        assert "extra" in result["Missing in Uploaded"]

    def test_key_missing_from_current_reported(self):
        """A key in uploaded but absent from current is reported as Missing in Current."""
        from client.app.content.config.tabs.settings import _compute_diff

        current = {"log_level": "INFO"}
        uploaded = {"log_level": "INFO", "extra": "new_val"}
        result = _compute_diff(current, uploaded)

        assert "extra" in result["Missing in Current"]

    @pytest.mark.parametrize("empty_value", [None, ""])
    def test_null_or_empty_current_key_not_reported_as_missing(self, empty_value):
        """A key with None or '' in current but absent from uploaded is not a diff."""
        from client.app.content.config.tabs.settings import _compute_diff

        current = {"log_level": "INFO", "optional_key": empty_value}
        uploaded = {"log_level": "INFO"}
        result = _compute_diff(current, uploaded)

        assert "optional_key" not in result["Missing in Uploaded"]


# ---------------------------------------------------------------------------
# _compare_lists
# ---------------------------------------------------------------------------


class TestCompareLists:
    """Tests for the _compare_lists function."""

    def test_equal_lists_no_diff(self):
        """Equal lists produce no differences."""
        from client.app.content.config.tabs.settings import _compute_diff

        result = _compute_diff([1, 2, 3], [1, 2, 3])
        assert not any(result[k] for k in result)

    def test_pairwise_value_mismatch(self):
        """Pairwise mismatches are detected."""
        from client.app.content.config.tabs.settings import _compute_diff

        result = _compute_diff([1, "a"], [1, "b"])
        assert "[1]" in result["Value Mismatch"]

    def test_extra_items_in_current(self):
        """Extra items in current reported as Missing in Uploaded."""
        from client.app.content.config.tabs.settings import _compute_diff

        result = _compute_diff([1, 2, 3], [1])
        assert "[1]" in result["Missing in Uploaded"]
        assert "[2]" in result["Missing in Uploaded"]

    def test_extra_items_in_uploaded(self):
        """Extra items in uploaded reported as Missing in Current."""
        from client.app.content.config.tabs.settings import _compute_diff

        result = _compute_diff([1], [1, 2, 3])
        assert "[1]" in result["Missing in Current"]
        assert "[2]" in result["Missing in Current"]


# ---------------------------------------------------------------------------
# _compute_diff
# ---------------------------------------------------------------------------


class TestComputeDiff:
    """Tests for the _compute_diff function."""

    def test_root_call_initializes_categories(self):
        """Root call creates a dict with all three categories."""
        from client.app.content.config.tabs.settings import _compute_diff

        result = _compute_diff({}, {})
        assert set(result.keys()) == {"Value Mismatch", "Missing in Uploaded", "Missing in Current"}

    def test_dict_vs_dict_dispatches(self):
        """Dicts are compared recursively via _compare_dicts."""
        from client.app.content.config.tabs.settings import _compute_diff

        result = _compute_diff({"a": 1}, {"a": 2})
        assert "a" in result["Value Mismatch"]

    def test_list_vs_list_dispatches(self):
        """Lists are compared via _compare_lists."""
        from client.app.content.config.tabs.settings import _compute_diff

        result = _compute_diff(["x"], ["y"])
        assert "[0]" in result["Value Mismatch"]

    def test_primitive_mismatch_detected(self):
        """Primitive value mismatches are detected."""
        from client.app.content.config.tabs.settings import _compute_diff

        result = _compute_diff(42, 99, path="val")
        assert "val" in result["Value Mismatch"]
        assert result["Value Mismatch"]["val"] == {"current": 42, "uploaded": 99}

    def test_equal_primitives_no_diff(self):
        """Equal primitives produce no differences."""
        from client.app.content.config.tabs.settings import _compute_diff

        result = _compute_diff("same", "same", path="val")
        assert not any(result[k] for k in result)

    def test_non_root_reuses_existing_differences(self):
        """Non-root call reuses and populates the provided differences dict."""
        from client.app.content.config.tabs.settings import _compute_diff

        diffs = {"Value Mismatch": {}, "Missing in Uploaded": {}, "Missing in Current": {}}
        _compute_diff(1, 2, path="x", differences=diffs)

        assert "x" in diffs["Value Mismatch"]


# ---------------------------------------------------------------------------
# _apply_uploaded_settings
# ---------------------------------------------------------------------------


class TestApplyUploadedSettings:
    """Tests for the _apply_uploaded_settings function."""

    def test_apply_legacy_config_posts_raw_body(self, mock_st):
        """Legacy v2.0.3-shaped payloads are POSTed as-is — server performs migration."""
        state = _make_settings_state()
        legacy = {"database_configs": [{"name": "DEFAULT", "user": "admin"}]}
        mock_api_post = MagicMock(return_value={})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", mock_api_post),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.refresh_settings = MagicMock()
            from client.app.content.config.tabs.settings import _apply_uploaded_settings

            _apply_uploaded_settings(legacy)

        # Client does not migrate; server is the single source of truth for migration.
        mock_api_post.assert_called_once_with("settings/import", json=legacy, toast="Settings imported.")

    def test_apply_calls_import_endpoint(self, mock_st):
        """Verify api_post is called with 'settings/import'."""
        state = _make_settings_state()
        uploaded = {"log_level": "DEBUG"}
        mock_api_post = MagicMock(return_value={})
        mock_refresh = MagicMock()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", mock_api_post),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.refresh_settings = mock_refresh
            from client.app.content.config.tabs.settings import _apply_uploaded_settings

            _apply_uploaded_settings(uploaded)

        mock_api_post.assert_called_once_with("settings/import", json=uploaded, toast="Settings imported.")

    def test_apply_refreshes_settings(self, mock_st):
        """helpers.refresh_settings() is called on success."""
        state = _make_settings_state()
        uploaded = {"log_level": "DEBUG"}
        mock_api_post = MagicMock(return_value={})
        mock_refresh = MagicMock()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", mock_api_post),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.refresh_settings = mock_refresh
            from client.app.content.config.tabs.settings import _apply_uploaded_settings

            _apply_uploaded_settings(uploaded)

        mock_refresh.assert_called_once()

    def test_apply_shows_error_on_failure(self, mock_st):
        """st.error() is called on HTTPStatusError."""
        state = _make_settings_state()
        uploaded = {"log_level": "DEBUG"}

        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.content = b'{"detail":"bad"}'
        mock_response.json.return_value = {"detail": "bad"}
        exc = httpx.HTTPStatusError("err", request=MagicMock(), response=mock_response)

        mock_api_post = MagicMock(side_effect=exc)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", mock_api_post),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.extract_error_detail.return_value = "bad"
            from client.app.content.config.tabs.settings import _apply_uploaded_settings

            _apply_uploaded_settings(uploaded)

        mock_st.error.assert_called_once()
        assert "bad" in mock_st.error.call_args[0][0]


class TestApplyButtonVisibility:
    """Tests for Apply button visibility in the upload section."""

    def test_apply_button_hidden_when_no_diff(self, mock_st):
        """No button rendered when settings match."""
        current_settings = {"log_level": "INFO", "database_configs": []}
        state = AttrDict({"settings": current_settings})

        # Simulate uploaded file with identical content
        uploaded_bytes = json.dumps(current_settings).encode()
        mock_file = MagicMock()
        mock_file.read.return_value = uploaded_bytes
        mock_st.file_uploader.return_value = mock_file

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.config.tabs.settings import _render_upload_settings_section

            _render_upload_settings_section()

        # st.info should be called with "match" message, button should NOT appear
        mock_st.info.assert_called_once()
        assert "match" in mock_st.info.call_args[0][0].lower()
        mock_st.button.assert_not_called()

    def test_apply_button_shown_when_diff_exists(self, mock_st):
        """Apply button rendered when differences are found."""
        current_settings = {"log_level": "INFO"}
        uploaded_settings = {"log_level": "DEBUG"}
        state = AttrDict({"settings": current_settings})

        uploaded_bytes = json.dumps(uploaded_settings).encode()
        mock_file = MagicMock()
        mock_file.read.return_value = uploaded_bytes
        mock_st.file_uploader.return_value = mock_file
        mock_st.button.return_value = False  # Button shown but not clicked

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.config.tabs.settings import _render_upload_settings_section

            _render_upload_settings_section()

        mock_st.button.assert_called_once()
        assert "Apply" in mock_st.button.call_args[0][0]


# ---------------------------------------------------------------------------
# _render_upload_settings_section — additional coverage
# ---------------------------------------------------------------------------


class TestRenderUploadSettingsSection:
    """Additional tests for _render_upload_settings_section."""

    def test_no_file_uploaded_nothing_rendered(self, mock_st):
        """When no file is uploaded, no error/info/button is rendered."""
        mock_st.file_uploader.return_value = None
        state = AttrDict({"settings": {}})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.config.tabs.settings import _render_upload_settings_section

            _render_upload_settings_section()

        mock_st.error.assert_not_called()
        mock_st.info.assert_not_called()
        mock_st.button.assert_not_called()

    def test_invalid_json_shows_error(self, mock_st):
        """Invalid JSON triggers st.error('Invalid JSON file.')."""
        mock_file = MagicMock()
        mock_file.read.return_value = b"not-json{{"
        mock_st.file_uploader.return_value = mock_file
        state = AttrDict({"settings": {}})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.config.tabs.settings import _render_upload_settings_section

            _render_upload_settings_section()

        mock_st.error.assert_called_once_with("Invalid JSON file.")

    def test_unicode_decode_error_shows_error(self, mock_st):
        """UnicodeDecodeError triggers st.error('Invalid JSON file.')."""
        mock_file = MagicMock()
        mock_file.read.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "bad")
        mock_st.file_uploader.return_value = mock_file
        state = AttrDict({"settings": {}})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.config.tabs.settings import _render_upload_settings_section

            _render_upload_settings_section()

        mock_st.error.assert_called_once_with("Invalid JSON file.")

    def test_button_click_applies_settings_and_reruns(self, mock_st):
        """Clicking Apply calls _apply_uploaded_settings, sleeps, and reruns."""
        current_settings = {"log_level": "INFO"}
        uploaded_settings = {"log_level": "DEBUG"}
        state = AttrDict({"settings": current_settings})

        uploaded_bytes = json.dumps(uploaded_settings).encode()
        mock_file = MagicMock()
        mock_file.read.return_value = uploaded_bytes
        mock_st.file_uploader.return_value = mock_file
        mock_st.button.return_value = True
        mock_st.rerun.side_effect = Rerun()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._apply_uploaded_settings") as mock_apply,
            patch(f"{MODULE}.time") as mock_time,
        ):
            from client.app.content.config.tabs.settings import _render_upload_settings_section

            with pytest.raises(Rerun):
                _render_upload_settings_section()

        mock_apply.assert_called_once_with(uploaded_settings)
        mock_time.sleep.assert_called_once_with(2)
        mock_st.rerun.assert_called_once()


# ---------------------------------------------------------------------------
# _render_download_settings_section
# ---------------------------------------------------------------------------


class TestRenderDownloadSettingsSection:
    """Tests for the _render_download_settings_section function."""

    def test_creates_two_column_layout(self, mock_st):
        """Columns are created with widths [2, 3, 5]."""
        cols = [MagicMock(), MagicMock(), MagicMock()]
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = cols
        mock_st.button.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._get_settings_data", return_value="{}"),
            patch(f"{MODULE}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value.strftime.return_value = "20260101_120000"
            from client.app.content.config.tabs.settings import _render_download_settings_section

            _render_download_settings_section()

        mock_st.columns.assert_called_once_with([3, 3, 4])

    def test_download_button_with_timestamped_filename(self, mock_st):
        """Download button uses a timestamped filename."""
        cols = [MagicMock(), MagicMock(), MagicMock()]
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = cols
        mock_st.button.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._get_settings_data", return_value="{}"),
            patch(f"{MODULE}.datetime") as mock_dt,
        ):
            mock_dt.now.return_value.strftime.return_value = "20260227_143000"
            from client.app.content.config.tabs.settings import _render_download_settings_section

            _render_download_settings_section()

        cols[0].download_button.assert_called_once()
        assert cols[0].download_button.call_args.kwargs["file_name"] == "optimizer_settings_20260227_143000.json"


# ---------------------------------------------------------------------------
# _spring_ai_obaas
# ---------------------------------------------------------------------------


class TestSpringAiObaas:
    """Tests for the _spring_ai_obaas function."""

    def _make_state_for_obaas(self, tools_enabled=None, prompt_configs=None):
        """Build state dict for _spring_ai_obaas tests."""
        return AttrDict(
            {
                "settings": {
                    "client_settings": {
                        "tools_enabled": tools_enabled or [],
                        "database": {"alias": "mydb"},
                    },
                    "prompt_configs": prompt_configs or [],
                },
            }
        )

    def _make_src_dir(self, _file_name, template_content):
        """Build a mock src_dir with a templates sub-path."""
        mock_template_file = MagicMock()
        mock_template_file.read_text.return_value = template_content
        mock_templates_dir = MagicMock()
        mock_templates_dir.__truediv__ = MagicMock(return_value=mock_template_file)
        mock_src = MagicMock()
        mock_src.__truediv__ = MagicMock(return_value=mock_templates_dir)
        return mock_src

    def test_vector_search_selects_vs_tools_prompt(self, mock_st):
        """'Vector Search' in tools selects optimizer_vs-tools-default prompt."""
        prompts = [{"name": "optimizer_vs-tools-default", "text": "VS prompt"}]
        state = self._make_state_for_obaas(tools_enabled=["Vector Search"], prompt_configs=prompts)
        src_dir = self._make_src_dir("start.sh", "{sys_prompt}{provider}{ll_model}{vector_search}{database_config}")

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.state_configs_lookup.return_value = {"mydb": {"user": "admin"}}
            from client.app.content.config.tabs.settings import _spring_ai_obaas

            result = _spring_ai_obaas(src_dir, "start.sh", "openai", {}, {})

        assert "VS prompt" in result

    def test_no_vector_search_selects_basic_prompt(self, mock_st):
        """No 'Vector Search' selects optimizer_basic-default prompt."""
        prompts = [{"name": "optimizer_basic-default", "text": "Basic prompt"}]
        state = self._make_state_for_obaas(tools_enabled=[], prompt_configs=prompts)
        src_dir = self._make_src_dir("start.sh", "{sys_prompt}{provider}{ll_model}{vector_search}{database_config}")

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.state_configs_lookup.return_value = {"mydb": {"user": "admin"}}
            from client.app.content.config.tabs.settings import _spring_ai_obaas

            result = _spring_ai_obaas(src_dir, "start.sh", "openai", {}, {})

        assert "Basic prompt" in result

    def test_prompt_not_found_uses_fallback(self, mock_st):
        """When prompt is not found, uses fallback 'You are a helpful assistant.'"""
        state = self._make_state_for_obaas(tools_enabled=[], prompt_configs=[])
        src_dir = self._make_src_dir("start.sh", "{sys_prompt}{provider}{ll_model}{vector_search}{database_config}")

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.state_configs_lookup.return_value = {"mydb": {"user": "admin"}}
            from client.app.content.config.tabs.settings import _spring_ai_obaas

            result = _spring_ai_obaas(src_dir, "start.sh", "openai", {}, {})

        assert "You are a helpful assistant." in result

    def test_non_yaml_file_uses_raw_prompt(self, mock_st):
        """Non-YAML file uses the raw prompt text without yaml.dump."""
        prompts = [{"name": "optimizer_basic-default", "text": "Raw prompt text"}]
        state = self._make_state_for_obaas(prompt_configs=prompts)
        src_dir = self._make_src_dir("start.sh", "prompt={sys_prompt}")

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.state_configs_lookup.return_value = {"mydb": {"user": "admin"}}
            from client.app.content.config.tabs.settings import _spring_ai_obaas

            result = _spring_ai_obaas(src_dir, "start.sh", "openai", {}, {})

        assert "Raw prompt text" in result

    def test_yaml_file_formats_prompt_via_yaml_dump(self, mock_st):
        """YAML file formats the prompt via yaml.dump."""
        import yaml

        prompts = [{"name": "optimizer_basic-default", "text": "YAML prompt"}]
        state = self._make_state_for_obaas(prompt_configs=prompts)

        # Build a template that produces valid YAML when formatted
        yaml_template = "spring:\n  ai:\n    sys_prompt: {sys_prompt}\n"
        src_dir = self._make_src_dir("obaas.yaml", yaml_template)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.state_configs_lookup.return_value = {"mydb": {"user": "admin"}}
            from client.app.content.config.tabs.settings import _spring_ai_obaas

            result = _spring_ai_obaas(src_dir, "obaas.yaml", "ollama", {}, {})

        # Result should be valid YAML
        parsed = yaml.safe_load(result)
        assert parsed is not None

    def test_yaml_ollama_adds_openai_placeholder(self, mock_st):
        """YAML + ollama provider adds openai placeholder stanza."""
        import yaml

        prompts = [{"name": "optimizer_basic-default", "text": "test"}]
        state = self._make_state_for_obaas(prompt_configs=prompts)

        yaml_template = "spring:\n  ai:\n    sys_prompt: {sys_prompt}\n"
        src_dir = self._make_src_dir("obaas.yaml", yaml_template)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.state_configs_lookup.return_value = {"mydb": {"user": "admin"}}
            from client.app.content.config.tabs.settings import _spring_ai_obaas

            result = _spring_ai_obaas(src_dir, "obaas.yaml", "ollama", {}, {})

        parsed = yaml.safe_load(result)
        assert parsed["spring"]["ai"]["openai"] == {"chat": {"options": {"model": "_"}}}

    def test_yaml_openai_adds_ollama_placeholder(self, mock_st):
        """YAML + openai provider adds ollama placeholder stanza."""
        import yaml

        prompts = [{"name": "optimizer_basic-default", "text": "test"}]
        state = self._make_state_for_obaas(prompt_configs=prompts)

        yaml_template = (
            "spring:\n  ai:\n    openai:\n      base-url: https://custom.host.com\n    sys_prompt: {sys_prompt}\n"
        )
        src_dir = self._make_src_dir("obaas.yaml", yaml_template)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.state_configs_lookup.return_value = {"mydb": {"user": "admin"}}
            from client.app.content.config.tabs.settings import _spring_ai_obaas

            result = _spring_ai_obaas(src_dir, "obaas.yaml", "openai", {}, {})

        parsed = yaml.safe_load(result)
        assert parsed["spring"]["ai"]["ollama"] == {"chat": {"options": {"model": "_"}}}

    def test_yaml_openai_obaas_fixes_base_url(self, mock_st):
        """YAML + openai + obaas file + api.openai.com in base-url fixes base-url."""
        import yaml

        prompts = [{"name": "optimizer_basic-default", "text": "test"}]
        state = self._make_state_for_obaas(prompt_configs=prompts)

        yaml_template = (
            "spring:\n"
            "  ai:\n"
            "    openai:\n"
            "      base-url: https://api.openai.com/v1/chat\n"
            "    sys_prompt: {sys_prompt}\n"
        )
        src_dir = self._make_src_dir("obaas.yaml", yaml_template)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.state_configs_lookup.return_value = {"mydb": {"user": "admin"}}
            from client.app.content.config.tabs.settings import _spring_ai_obaas

            result = _spring_ai_obaas(src_dir, "obaas.yaml", "openai", {}, {})

        parsed = yaml.safe_load(result)
        assert parsed["spring"]["ai"]["openai"]["base-url"] == "https://api.openai.com"


# ---------------------------------------------------------------------------
# _zip_directory
# ---------------------------------------------------------------------------


class TestZipDirectory:
    """Tests for the _zip_directory function."""

    def test_returns_bytesio_with_valid_zip(self, tmp_path):
        """Returns a BytesIO object containing a valid zip."""
        from client.app.content.config.tabs.settings import _zip_directory

        (tmp_path / "file.txt").write_text("hello")
        buf = _zip_directory(tmp_path)

        assert isinstance(buf, io.BytesIO)
        with zipfile.ZipFile(buf) as zf:
            assert zf.namelist() == ["file.txt"]

    def test_zips_files_recursively_with_correct_paths(self, tmp_path):
        """Recursively zips files with correct relative paths."""
        from client.app.content.config.tabs.settings import _zip_directory

        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "root.txt").write_text("r")
        (sub / "nested.txt").write_text("n")

        buf = _zip_directory(tmp_path)
        with zipfile.ZipFile(buf) as zf:
            names = sorted(zf.namelist())
            assert "root.txt" in names
            assert "sub/nested.txt" in names

    def test_empty_directory_returns_empty_zip(self, tmp_path):
        """An empty directory produces a valid but empty zip."""
        from client.app.content.config.tabs.settings import _zip_directory

        buf = _zip_directory(tmp_path)
        with zipfile.ZipFile(buf) as zf:
            assert zf.namelist() == []


# ---------------------------------------------------------------------------
# _spring_ai_zip
# ---------------------------------------------------------------------------


class TestSpringAiZip:
    """Tests for the _spring_ai_zip function."""

    def test_copies_src_dir_and_static_files(self, mock_st):
        """Copies 'src' dir and 4 static files."""
        mock_zip_buf = io.BytesIO()

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.Path") as mock_path_cls,
            patch(f"{MODULE}.tempfile.TemporaryDirectory") as mock_tmpdir,
            patch(f"{MODULE}.shutil") as mock_shutil,
            patch(f"{MODULE}._zip_directory", return_value=mock_zip_buf),
            patch(f"{MODULE}._spring_ai_obaas", return_value="content"),
        ):
            mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/tmp/test")
            mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
            mock_path_cls.return_value.resolve.return_value.parents.__getitem__ = MagicMock()
            mock_path_cls.side_effect = lambda x: MagicMock(__truediv__=lambda s, o: MagicMock())

            from client.app.content.config.tabs.settings import _spring_ai_zip

            _spring_ai_zip("openai", {}, {})

        assert mock_shutil.copytree.called
        assert mock_shutil.copy.call_count == 4

    def test_appends_start_sh_and_application_yaml(self, mock_st):
        """Appends start.sh and application-obaas.yml to the zip."""
        mock_zip_buf = io.BytesIO()
        # Create a valid zip so ZipFile("a") works
        with zipfile.ZipFile(mock_zip_buf, "w") as zf:
            zf.writestr("dummy.txt", "d")
        mock_zip_buf.seek(0)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.Path"),
            patch(f"{MODULE}.tempfile.TemporaryDirectory") as mock_tmpdir,
            patch(f"{MODULE}.shutil"),
            patch(f"{MODULE}._zip_directory", return_value=mock_zip_buf),
            patch(f"{MODULE}._spring_ai_obaas", return_value="content"),
        ):
            mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/tmp/test")
            mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
            from client.app.content.config.tabs.settings import _spring_ai_zip

            result = _spring_ai_zip("openai", {}, {})

        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert "start.sh" in names
            assert "src/main/resources/application-obaas.yml" in names

    def test_calls_spring_ai_obaas_twice(self, mock_st):
        """Calls _spring_ai_obaas twice (once per template)."""
        mock_zip_buf = io.BytesIO()
        with zipfile.ZipFile(mock_zip_buf, "w") as zf:
            zf.writestr("dummy.txt", "d")
        mock_zip_buf.seek(0)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.Path"),
            patch(f"{MODULE}.tempfile.TemporaryDirectory") as mock_tmpdir,
            patch(f"{MODULE}.shutil"),
            patch(f"{MODULE}._zip_directory", return_value=mock_zip_buf),
            patch(f"{MODULE}._spring_ai_obaas", return_value="content") as mock_obaas,
        ):
            mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/tmp/test")
            mock_tmpdir.return_value.__exit__ = MagicMock(return_value=False)
            from client.app.content.config.tabs.settings import _spring_ai_zip

            _spring_ai_zip("openai", {}, {})

        assert mock_obaas.call_count == 2


# ---------------------------------------------------------------------------
# _spring_ai_conf_check  (pure function)
# ---------------------------------------------------------------------------


class TestSpringAiConfCheck:
    """Tests for the _spring_ai_conf_check function."""

    def test_empty_ll_model_returns_hybrid(self):
        """Empty ll_model returns 'hybrid'."""
        from client.app.content.config.tabs.settings import _spring_ai_conf_check

        assert _spring_ai_conf_check({}, {"provider": "openai"}) == "hybrid"

    def test_empty_embed_model_returns_hybrid(self):
        """Empty embed_model returns 'hybrid'."""
        from client.app.content.config.tabs.settings import _spring_ai_conf_check

        assert _spring_ai_conf_check({"provider": "openai"}, {}) == "hybrid"

    @pytest.mark.parametrize(
        "provider,expected",
        [
            ("hosted_vllm", "hosted_vllm"),
            ("openai", "openai"),
            ("ollama", "ollama"),
        ],
    )
    def test_matching_providers(self, provider, expected):
        """Both providers matching returns the matching type."""
        from client.app.content.config.tabs.settings import _spring_ai_conf_check

        assert _spring_ai_conf_check({"provider": provider}, {"provider": provider}) == expected

    def test_mixed_providers_returns_hybrid(self):
        """Mixed providers returns 'hybrid'."""
        from client.app.content.config.tabs.settings import _spring_ai_conf_check

        assert _spring_ai_conf_check({"provider": "openai"}, {"provider": "ollama"}) == "hybrid"


# ---------------------------------------------------------------------------
# _get_model_configs
# ---------------------------------------------------------------------------


class TestGetModelConfigs:
    """Tests for the _get_model_configs function."""

    def test_both_lookups_succeed(self, mock_st):
        """When both lookups succeed, returns merged configs."""
        state = AttrDict(
            {
                "settings": {
                    "client_settings": {
                        "ll_model": {"provider": "openai", "id": "gpt4"},
                        "vector_search": {"provider": "openai", "id": "embed1"},
                    },
                },
            }
        )

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):

            def lookup_side_effect(model_type):
                if model_type == "ll":
                    return {"openai/gpt4": {"provider": "openai", "id": "gpt4"}}
                return {"openai/embed1": {"provider": "openai", "id": "embed1"}}

            mock_helpers.enabled_models_lookup.side_effect = lookup_side_effect

            from client.app.content.config.tabs.settings import _get_model_configs

            ll_config, embed_config, spring_ai_conf = _get_model_configs()

        assert ll_config["provider"] == "openai"
        assert embed_config["provider"] == "openai"
        assert spring_ai_conf == "openai"

    def test_ll_model_key_error_returns_empty(self, mock_st):
        """KeyError on ll model lookup returns empty ll_config."""
        state = AttrDict(
            {
                "settings": {
                    "client_settings": {
                        "ll_model": {"model": "missing"},
                        "vector_search": {"model": "embed1"},
                    },
                },
            }
        )

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):

            def lookup_side_effect(model_type):
                if model_type == "ll":
                    raise KeyError("missing")
                return {"embed1": {"provider": "openai", "id": "embed1"}}

            mock_helpers.enabled_models_lookup.side_effect = lookup_side_effect
            from client.app.content.config.tabs.settings import _get_model_configs

            ll_config, _embed_config, spring_ai_conf = _get_model_configs()

        assert ll_config == {}
        assert spring_ai_conf == "hybrid"

    def test_embed_model_key_error_returns_empty(self, mock_st):
        """KeyError on embed model lookup returns empty embed_config."""
        state = AttrDict(
            {
                "settings": {
                    "client_settings": {
                        "ll_model": {"model": "gpt4"},
                        "vector_search": {"model": "missing"},
                    },
                },
            }
        )

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):

            def lookup_side_effect(model_type):
                if model_type == "ll":
                    return {"gpt4": {"provider": "openai", "id": "gpt4"}}
                raise KeyError("missing")

            mock_helpers.enabled_models_lookup.side_effect = lookup_side_effect
            from client.app.content.config.tabs.settings import _get_model_configs

            _ll_config, embed_config, spring_ai_conf = _get_model_configs()

        assert embed_config == {}
        assert spring_ai_conf == "hybrid"

    def test_both_key_error_returns_all_empty(self, mock_st):
        """Both KeyError returns ({}, {}, 'hybrid')."""
        state = AttrDict(
            {
                "settings": {
                    "client_settings": {
                        "ll_model": {"model": "missing1"},
                        "vector_search": {"model": "missing2"},
                    },
                },
            }
        )

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
        ):
            mock_helpers.enabled_models_lookup.side_effect = KeyError("missing")
            from client.app.content.config.tabs.settings import _get_model_configs

            ll_config, embed_config, spring_ai_conf = _get_model_configs()

        assert ll_config == {}
        assert embed_config == {}
        assert spring_ai_conf == "hybrid"


# ---------------------------------------------------------------------------
# _render_source_code_templates_section
# ---------------------------------------------------------------------------


class TestRenderSourceCodeTemplatesSection:
    """Tests for the _render_source_code_templates_section function."""

    def test_renders_header_with_red_divider(self, mock_st):
        """Renders header with divider='red'."""
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._get_model_configs", return_value=({}, {}, "hybrid")),
        ):
            from client.app.content.config.tabs.settings import _render_source_code_templates_section

            _render_source_code_templates_section()

        mock_st.header.assert_called_once_with("Source Code Templates", divider="red")

    def test_unset_models_show_select_message(self, mock_st):
        """Unset models show a 'select a model' markdown, no download buttons."""
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}._get_model_configs", return_value=({}, {}, "hybrid")),
        ):
            from client.app.content.config.tabs.settings import _render_source_code_templates_section

            _render_source_code_templates_section()

        mock_st.markdown.assert_called_once()
        assert "Select" in mock_st.markdown.call_args[0][0]
        mock_st.columns.assert_not_called()

    def test_hybrid_config_hides_template_downloads(self, mock_st):
        """A mixed-provider config does not offer source templates."""
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(
                f"{MODULE}._get_model_configs",
                return_value=({"provider": "openai"}, {"provider": "ollama"}, "hybrid"),
            ),
            patch(f"{MODULE}._spring_ai_zip", return_value=io.BytesIO()) as mock_spring_zip,
        ):
            from client.app.content.config.tabs.settings import _render_source_code_templates_section

            _render_source_code_templates_section()

        mock_st.markdown.assert_called_once()
        mock_st.columns.assert_not_called()
        mock_spring_zip.assert_not_called()

    def test_non_hybrid_shows_spring_ai_download(self, mock_st):
        """Non-hybrid config shows SpringAI download button."""
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(
                f"{MODULE}._get_model_configs", return_value=({"provider": "openai"}, {"provider": "openai"}, "openai")
            ),
            patch(f"{MODULE}.get_server_settings", return_value={"settings": {}}),
            patch(f"{MODULE}._spring_ai_zip", return_value=io.BytesIO()) as mock_spring_zip,
            patch(f"{MODULE}.state", AttrDict({"settings": {}, "optimizer_client": "test-client"})),
        ):
            from client.app.content.config.tabs.settings import _render_source_code_templates_section

            _render_source_code_templates_section()

        mock_spring_zip.assert_called_once()
        mock_st.download_button.assert_called()

    def test_hosted_vllm_hides_spring_ai_button(self, mock_st):
        """hosted_vllm config hides SpringAI."""
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(
                f"{MODULE}._get_model_configs",
                return_value=({"provider": "hosted_vllm"}, {"provider": "hosted_vllm"}, "hosted_vllm"),
            ),
            patch(f"{MODULE}._spring_ai_zip", return_value=io.BytesIO()) as mock_spring_zip,
        ):
            from client.app.content.config.tabs.settings import _render_source_code_templates_section

            _render_source_code_templates_section()

        mock_st.markdown.assert_called_once()
        mock_st.columns.assert_not_called()
        mock_spring_zip.assert_not_called()

    @pytest.mark.parametrize("conf_type", ["openai", "ollama"])
    def test_openai_ollama_shows_spring_ai_download_button(self, mock_st, conf_type):
        """openai/ollama configs show the SpringAI download button."""
        cols = [MagicMock(), MagicMock(), MagicMock()]
        mock_st.columns.return_value = cols

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(
                f"{MODULE}._get_model_configs",
                return_value=({"provider": conf_type}, {"provider": conf_type}, conf_type),
            ),
            patch(f"{MODULE}.get_server_settings", return_value={"settings": {}}),
            patch(f"{MODULE}._spring_ai_zip", return_value=io.BytesIO()) as mock_spring_zip,
            patch(f"{MODULE}.state", AttrDict({"settings": {}, "optimizer_client": "test-client"})),
        ):
            from client.app.content.config.tabs.settings import _render_source_code_templates_section

            _render_source_code_templates_section()

        mock_spring_zip.assert_called_once()

    def test_repeated_renders_reuse_cached_export(self, mock_st):
        """The export projection is fetched once per session and reused on
        subsequent reruns until invalidated by ``helpers.refresh_settings``.
        """
        state = AttrDict({"settings": {}, "optimizer_client": "test-client"})
        cols = [MagicMock(), MagicMock(), MagicMock()]
        mock_st.columns.return_value = cols
        configs_return = ({"provider": "openai"}, {"provider": "openai"}, "openai")
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._get_model_configs", return_value=configs_return),
            patch(f"{MODULE}.get_server_settings", return_value={"settings": {}}) as mock_get,
            patch(f"{MODULE}._spring_ai_zip", return_value=io.BytesIO()),
        ):
            from client.app.content.config.tabs.settings import _render_source_code_templates_section

            _render_source_code_templates_section()
            _render_source_code_templates_section()
            _render_source_code_templates_section()

        assert mock_get.call_count == 1

    def test_renders_with_initially_masked_state_without_persisting_reveal(self, mock_st, tmp_path):
        """The renderer obtains the reveal projection for template generation
        but must restore ``state['settings']`` afterwards so the reveal data
        is not visible to other UI panels that read session state.
        """
        masked_db = {"alias": "TEST", "username": "u", "dsn": "//h:1521/s"}
        masked_model = {"id": "gpt-5-mini", "type": "ll", "provider": "openai", "enabled": True, "usable": True}
        masked_state = AttrDict(
            {
                "settings": {
                    "database_configs": [masked_db],
                    "model_configs": [masked_model],
                    "prompt_configs": [{"name": "optimizer_basic-default", "text": "p"}],
                    "client_settings": {
                        "database": {"alias": "TEST"},
                        "ll_model": {"provider": "openai", "id": "gpt-5-mini"},
                        "vector_search": {},
                        "tools_enabled": [],
                    },
                },
                "optimizer_client": "test",
            }
        )
        reveal_payload = {
            "database_configs": [
                {"alias": "TEST", "username": "u", "password": "the-db-password", "dsn": "//h:1521/s"},
            ],
            "model_configs": [
                {
                    "id": "gpt-5-mini",
                    "type": "ll",
                    "provider": "openai",
                    "api_key": "sk-the-key",
                    "enabled": True,
                    "usable": True,
                },
            ],
            "prompt_configs": [{"name": "optimizer_basic-default", "text": "p"}],
            "client_settings": masked_state["settings"]["client_settings"],
        }

        ll_config = {"provider": "openai", "id": "gpt-5-mini"}
        embed_config = {"provider": "openai", "id": "text-embed", "alias": ""}
        del tmp_path  # template files not exercised; renderers are mocked

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", masked_state),
            patch(f"{MODULE}.get_server_settings", return_value=reveal_payload),
            patch(f"{MODULE}._get_model_configs", return_value=(ll_config, embed_config, "openai")),
            patch(f"{MODULE}._spring_ai_zip", return_value=io.BytesIO()) as mock_spring_zip,
        ):
            from client.app.content.config.tabs.settings import _render_source_code_templates_section

            _render_source_code_templates_section()

        # Render produced the SpringAI download payload.
        mock_spring_zip.assert_called_once()

        # state.settings is back to the masked dict — the reveal projection
        # did not persist where other UI paths can read it.
        post_db = masked_state["settings"]["database_configs"][0]
        post_model = masked_state["settings"]["model_configs"][0]
        assert "password" not in post_db
        assert "api_key" not in post_model


# ---------------------------------------------------------------------------
# display_settings
# ---------------------------------------------------------------------------


class TestDisplaySettings:
    """Tests for the display_settings function."""

    def _setup_display_st(self, mock_st, toggle_value=False):
        """Configure mock_st.columns to return a col_left with a toggle."""
        col_left = MagicMock()
        col_left.toggle.return_value = toggle_value
        mock_st.columns.side_effect = lambda widths: [col_left] + [MagicMock() for _ in widths[1:]]

    def test_renders_header(self, mock_st):
        """Renders 'Optimizer Settings' header."""
        self._setup_display_st(mock_st)
        state = AttrDict({"runtime_upload_toggle": False, "settings": {}})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_settings", return_value={}),
            patch(f"{MODULE}._render_download_settings_section"),
            patch(f"{MODULE}._render_upload_settings_section"),
            patch(f"{MODULE}._render_source_code_templates_section"),
        ):
            from client.app.content.config.tabs.settings import display_settings

            display_settings()

        mock_st.header.assert_any_call("Optimizer Settings", divider="red")

    def test_initializes_runtime_upload_toggle_if_missing(self, mock_st):
        """Initializes runtime_upload_toggle to False if missing from state."""
        self._setup_display_st(mock_st)
        state = AttrDict({"settings": {}})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_settings", return_value={}),
            patch(f"{MODULE}._render_download_settings_section"),
            patch(f"{MODULE}._render_upload_settings_section"),
            patch(f"{MODULE}._render_source_code_templates_section"),
        ):
            from client.app.content.config.tabs.settings import display_settings

            display_settings()

        assert state["runtime_settings_upload_toggle"] is False

    def test_toggle_off_shows_json_and_download(self, mock_st):
        """Toggle off shows JSON and download section, not upload."""
        self._setup_display_st(mock_st)
        state = AttrDict({"runtime_upload_toggle": False, "settings": {}})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_settings", return_value={"data": 1}),
            patch(f"{MODULE}._render_download_settings_section") as mock_download,
            patch(f"{MODULE}._render_upload_settings_section") as mock_upload,
            patch(f"{MODULE}._render_source_code_templates_section"),
        ):
            from client.app.content.config.tabs.settings import display_settings

            display_settings()

        mock_st.json.assert_called_once_with({"data": 1}, expanded=False)
        mock_download.assert_called_once()
        mock_upload.assert_not_called()

    def test_toggle_on_shows_upload(self, mock_st):
        """Toggle on shows upload section, not download."""
        self._setup_display_st(mock_st, toggle_value=True)
        state = AttrDict({"runtime_upload_toggle": False, "settings": {}})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_settings", return_value={}),
            patch(f"{MODULE}._render_download_settings_section") as mock_download,
            patch(f"{MODULE}._render_upload_settings_section") as mock_upload,
            patch(f"{MODULE}._render_source_code_templates_section"),
        ):
            from client.app.content.config.tabs.settings import display_settings

            display_settings()

        mock_upload.assert_called_once()
        mock_download.assert_not_called()

    def test_source_code_templates_always_rendered(self, mock_st):
        """Source code templates section is always rendered regardless of toggle."""
        self._setup_display_st(mock_st)
        state = AttrDict({"runtime_upload_toggle": False, "settings": {}})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_settings", return_value={}),
            patch(f"{MODULE}._render_download_settings_section"),
            patch(f"{MODULE}._render_upload_settings_section"),
            patch(f"{MODULE}._render_source_code_templates_section") as mock_src,
        ):
            from client.app.content.config.tabs.settings import display_settings

            display_settings()

        mock_src.assert_called_once()

    def test_unauthenticated_returns_early(self, mock_st):
        """When unauthenticated, display_settings renders locked notice and skips body."""
        self._setup_display_st(mock_st)
        state = AttrDict({"settings": {}})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._fetch_settings") as mock_fetch,
            patch(f"{MODULE}._render_download_settings_section") as mock_download,
            patch(f"{MODULE}._render_upload_settings_section") as mock_upload,
            patch(f"{MODULE}._render_source_code_templates_section") as mock_src,
            patch(f"{MODULE}.is_authenticated", return_value=False),
            patch(f"{MODULE}.locked_notice") as mock_notice,
        ):
            from client.app.content.config.tabs.settings import display_settings

            display_settings()

        mock_notice.assert_called_once()
        mock_fetch.assert_not_called()
        mock_download.assert_not_called()
        mock_upload.assert_not_called()
        mock_src.assert_not_called()
