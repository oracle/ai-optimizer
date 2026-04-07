"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.tools.tabs.prompt_eng
"""
# spell-checker: disable

import json
from unittest.mock import MagicMock, patch

import pytest

from client.tests.conftest import AttrDict, make_http_error

MODULE = "client.app.content.tools.tabs.prompt_eng"
HELPERS = "client.app.core.helpers"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_state(extra=None):
    """Build a minimal session state for prompt_eng tests."""
    data = AttrDict(
        {
            "settings": {
                "prompt_configs": [
                    {
                        "name": "sys_prompt",
                        "title": "System Prompt",
                        "description": "Main system prompt",
                        "text": "You are helpful.",
                    },
                    {
                        "name": "vs_prompt",
                        "title": "VS Prompt",
                        "description": "Vector search prompt",
                        "text": "Search context.",
                    },
                ],
                "client_settings": {},
            },
            "optimizer_client": "test-client",
            "prompt_eng_selector_index": 0,
            "runtime_prompt_titles": ["System Prompt", "VS Prompt"],
        }
    )
    if extra:
        data.update(extra)
    return data


# ---------------------------------------------------------------------------
# _on_prompt_change
# ---------------------------------------------------------------------------
class TestOnPromptChange:
    """Tests for _on_prompt_change."""

    def test_sets_index(self):
        """Verify selector index updates when prompt selection changes."""
        state = _make_state()
        state["runtime_prompt_eng_selector"] = "VS Prompt"
        with patch(f"{MODULE}.state", state):
            from client.app.content.tools.tabs.prompt_eng import _on_prompt_change

            _on_prompt_change()
        assert state.prompt_eng_selector_index == 1


# ---------------------------------------------------------------------------
# _get_prompt_name
# ---------------------------------------------------------------------------
class TestGetPromptName:
    """Tests for _get_prompt_name."""

    def test_found(self):
        """Return the prompt name when the title matches a known prompt."""
        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.content.tools.tabs.prompt_eng import _get_prompt_name

            result = _get_prompt_name("System Prompt")
        assert result == "sys_prompt"

    def test_not_found(self):
        """Return None when the title does not match any prompt."""
        state = _make_state()
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.content.tools.tabs.prompt_eng import _get_prompt_name

            result = _get_prompt_name("Nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# _save_prompt
# ---------------------------------------------------------------------------
class TestSavePrompt:
    """Tests for _save_prompt."""

    def test_calls_api_put(self, mock_st):
        """Verify api_put is called with correct endpoint and payload."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put") as mock_put,
            patch(f"{MODULE}.helpers.refresh_settings"),
        ):
            from client.app.content.tools.tabs.prompt_eng import _save_prompt

            _save_prompt("sys_prompt", "New text", "Old text")
        mock_put.assert_called_once_with("prompts/sys_prompt", json={"text": "New text"}, toast="Prompt saved.")

    def test_noop_when_unchanged(self, mock_st):
        """Verify no API call is made when prompt text has not changed."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put") as mock_put,
        ):
            from client.app.content.tools.tabs.prompt_eng import _save_prompt

            _save_prompt("sys_prompt", "Same text", "Same text")
        mock_put.assert_not_called()
        mock_st.toast.assert_called_once()

    def test_http_error(self, mock_st):
        """Verify HTTP errors during save are surfaced via st.error."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_put", side_effect=make_http_error(500, "Server error")),
        ):
            from client.app.content.tools.tabs.prompt_eng import _save_prompt

            _save_prompt("sys_prompt", "New", "Old")
        mock_st.error.assert_called_once()


# ---------------------------------------------------------------------------
# _reset_prompt
# ---------------------------------------------------------------------------
class TestResetPrompt:
    """Tests for _reset_prompt."""

    def test_calls_api_post(self, mock_st):
        """Verify api_post is called with the correct reset endpoint."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post") as mock_post,
            patch(f"{MODULE}.helpers.refresh_settings"),
        ):
            from client.app.content.tools.tabs.prompt_eng import _reset_prompt

            _reset_prompt("sys_prompt")
        mock_post.assert_called_once_with("prompts/sys_prompt/reset", toast="Prompt reset to default.")

    def test_http_error(self, mock_st):
        """Verify HTTP errors during reset are surfaced via st.error."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", side_effect=make_http_error(500)),
        ):
            from client.app.content.tools.tabs.prompt_eng import _reset_prompt

            _reset_prompt("sys_prompt")
        mock_st.error.assert_called_once()


# ---------------------------------------------------------------------------
# _export_prompts
# ---------------------------------------------------------------------------
class TestExportPrompts:
    """Tests for _export_prompts."""

    def test_json_string(self, mock_st):
        """Verify export returns valid JSON containing prompt configs and timestamp."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.tools.tabs.prompt_eng import _export_prompts

            result = _export_prompts()
        data = json.loads(result)
        assert "export_timestamp" in data
        assert "prompt_configs" in data
        assert len(data["prompt_configs"]) == 2

    def test_warns_empty(self, mock_st):
        """Verify a warning is shown when there are no prompts to export."""
        state = _make_state()
        state["settings"]["prompt_configs"] = []
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.tools.tabs.prompt_eng import _export_prompts

            result = _export_prompts()
        assert result == ""
        mock_st.warning.assert_called_once()


# ---------------------------------------------------------------------------
# _import_prompts
# ---------------------------------------------------------------------------
class TestImportPrompts:
    """Tests for _import_prompts."""

    def _make_file(self, data):
        """Create a mock uploaded file object."""
        m = MagicMock()
        m.read.return_value = json.dumps(data).encode()
        return m

    def test_success(self, mock_st):
        """Verify successful import shows a toast with the imported count."""
        state = _make_state()
        uploaded = self._make_file({"prompt_configs": [{"name": "sys_prompt", "text": "new"}]})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", return_value={"prompt_configs": {"updated": 1, "skipped": 0}}),
            patch(f"{MODULE}.helpers.refresh_settings"),
        ):
            from client.app.content.tools.tabs.prompt_eng import _import_prompts

            _import_prompts(uploaded)
        mock_st.toast.assert_called_once()
        assert "Imported" in mock_st.toast.call_args[0][0]

    def test_skipped(self, mock_st):
        """Verify skipped prompts are reported in the toast message."""
        state = _make_state()
        uploaded = self._make_file({"prompt_configs": [{"name": "sys_prompt", "text": "same"}]})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", return_value={"prompt_configs": {"updated": 0, "skipped": 1}}),
        ):
            from client.app.content.tools.tabs.prompt_eng import _import_prompts

            _import_prompts(uploaded)
        mock_st.toast.assert_called_once()
        assert "skipped" in mock_st.toast.call_args[0][0]

    def test_no_prompts_in_file(self, mock_st):
        """Verify a toast is shown when the uploaded file contains no prompts."""
        state = _make_state()
        uploaded = self._make_file({"prompt_configs": []})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.tools.tabs.prompt_eng import _import_prompts

            _import_prompts(uploaded)
        mock_st.toast.assert_called_once()

    def test_json_error(self, mock_st):
        """Verify invalid JSON in the uploaded file triggers an error toast."""
        state = _make_state()
        uploaded = MagicMock()
        uploaded.read.return_value = b"not json"
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.tools.tabs.prompt_eng import _import_prompts

            _import_prompts(uploaded)
        mock_st.toast.assert_called_once()
        assert "Invalid JSON" in mock_st.toast.call_args[0][0]

    def test_http_error(self, mock_st):
        """Verify HTTP errors during import are surfaced via a toast."""
        state = _make_state()
        uploaded = self._make_file({"prompt_configs": [{"name": "p1", "text": "t"}]})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", side_effect=make_http_error(500, "Server fail")),
        ):
            from client.app.content.tools.tabs.prompt_eng import _import_prompts

            _import_prompts(uploaded)
        mock_st.toast.assert_called_once()
        assert "Failed" in mock_st.toast.call_args[0][0]


# ---------------------------------------------------------------------------
# _reset_all_prompts
# ---------------------------------------------------------------------------
class TestResetAllPrompts:
    """Tests for _reset_all_prompts."""

    def test_calls_api_post(self, mock_st):
        """Verify api_post is called with the bulk reset endpoint."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post") as mock_post,
            patch(f"{MODULE}.helpers.refresh_settings"),
        ):
            from client.app.content.tools.tabs.prompt_eng import _reset_all_prompts

            _reset_all_prompts()
        mock_post.assert_called_once_with("prompts/reset", toast="All prompts reset to defaults.")

    def test_http_error(self, mock_st):
        """Verify HTTP errors during bulk reset are surfaced via st.error."""
        state = _make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", side_effect=make_http_error(500)),
        ):
            from client.app.content.tools.tabs.prompt_eng import _reset_all_prompts

            _reset_all_prompts()
        mock_st.error.assert_called_once()


# ---------------------------------------------------------------------------
# display_prompt_eng
# ---------------------------------------------------------------------------
class TestDisplayPromptEng:
    """Tests for display_prompt_eng."""

    def _setup_columns(self, mock_st, toggle_value=False):
        """Configure columns mock so col_left.toggle returns a controlled value."""
        col_left = MagicMock()
        col_right = MagicMock()
        # First columns call is save/reset [2,3,5], second is bulk [7,3]
        call_count = 0

        def _columns(widths, **_kw):
            nonlocal call_count
            call_count += 1
            n = widths if isinstance(widths, int) else len(widths)
            if call_count == 2:
                return [col_left, col_right]
            return [MagicMock() for _ in range(n)]

        mock_st.columns.side_effect = _columns
        col_left.toggle.return_value = toggle_value
        return col_left, col_right

    def test_renders_header_and_selectbox(self, mock_st):
        """Verify the page header and prompt selectbox are rendered."""
        state = _make_state()
        mock_st.selectbox.return_value = "System Prompt"
        mock_st.text_area.side_effect = [None, "You are helpful."]
        self._setup_columns(mock_st, toggle_value=False)
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
            patch(f"{MODULE}._export_prompts", return_value="{}"),
        ):
            from client.app.content.tools.tabs.prompt_eng import display_prompt_eng

            display_prompt_eng()
        mock_st.header.assert_any_call("Prompt Engineering")
        mock_st.selectbox.assert_called_once()

    def test_renders_upload_mode(self, mock_st):
        """Verify the file uploader is rendered when bulk import is toggled on."""
        state = _make_state()
        mock_st.selectbox.return_value = "System Prompt"
        mock_st.text_area.side_effect = [None, "text"]
        mock_st.file_uploader.return_value = None
        self._setup_columns(mock_st, toggle_value=True)
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{HELPERS}.state", state),
        ):
            from client.app.content.tools.tabs.prompt_eng import display_prompt_eng

            display_prompt_eng()
        mock_st.file_uploader.assert_called_once()
