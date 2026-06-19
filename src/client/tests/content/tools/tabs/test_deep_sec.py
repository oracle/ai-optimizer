"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.tools.tabs.deep_sec
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

import pytest

from client.tests.conftest import AttrDict, make_http_error, make_mock_tabs

MODULE = "client.app.content.tools.tabs.deep_sec"

pytestmark = pytest.mark.unit

_AVAILABLE = {
    "available": True,
    "version": "23.26.2.0.0",
    "capabilities": {
        "create_data_role": True,
        "drop_data_role": True,
        "create_end_user": True,
        "drop_end_user": True,
        "manage_data_grants": True,
        "list_data_roles": True,
        "list_end_users": True,
        "list_data_grants": True,
    },
    "missing_privileges": [],
}


def _state():
    return AttrDict({"optimizer_client": "client-1"})


class TestDisplayDeepSec:
    def test_unavailable_shows_warning_and_skips_tabs(self, mock_st):
        status = {"available": False, "version": "23.5.0.0.0", "capabilities": {}, "missing_privileges": []}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", return_value=status),
            patch(f"{MODULE}.is_authenticated", return_value=True),
            patch(f"{MODULE}._render_data_roles") as mock_roles,
        ):
            from client.app.content.tools.tabs.deep_sec import display_deep_sec

            display_deep_sec()

        mock_st.warning.assert_called_once()
        mock_st.tabs.assert_not_called()
        mock_roles.assert_not_called()

    def test_available_renders_three_sections(self, mock_st):
        mock_st.tabs.return_value = make_mock_tabs(3)
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", return_value=_AVAILABLE),
            patch(f"{MODULE}.is_authenticated", return_value=True),
            patch(f"{MODULE}._render_data_roles") as mock_roles,
            patch(f"{MODULE}._render_end_users") as mock_users,
            patch(f"{MODULE}._render_data_grants") as mock_grants,
        ):
            from client.app.content.tools.tabs.deep_sec import display_deep_sec

            display_deep_sec()

        mock_st.tabs.assert_called_once()
        labels = mock_st.tabs.call_args[0][0]
        assert labels == ["Data Roles", "End Users", "Data Grants"]
        mock_roles.assert_called_once()
        mock_users.assert_called_once()
        mock_grants.assert_called_once()

    def test_unauthenticated_shows_locked_notice(self, mock_st):
        mock_st.tabs.return_value = make_mock_tabs(3)
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", return_value=_AVAILABLE),
            patch(f"{MODULE}.is_authenticated", return_value=False),
            patch(f"{MODULE}.locked_notice") as mock_locked,
            patch(f"{MODULE}._render_data_roles"),
            patch(f"{MODULE}._render_end_users"),
            patch(f"{MODULE}._render_data_grants"),
        ):
            from client.app.content.tools.tabs.deep_sec import display_deep_sec

            display_deep_sec()

        mock_locked.assert_called_once()

    def test_status_error_shows_error_and_returns(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", side_effect=make_http_error(503, "Database is not available")),
            patch(f"{MODULE}._render_data_roles") as mock_roles,
        ):
            from client.app.content.tools.tabs.deep_sec import display_deep_sec

            display_deep_sec()

        mock_st.error.assert_called_once()
        mock_roles.assert_not_called()


class TestGrantPreview:
    def test_preview_incomplete(self):
        from client.app.content.tools.tabs.deep_sec import _grant_preview

        assert "complete the fields" in _grant_preview("", [], "", [], "All columns", "", "")

    def test_preview_all_columns_except(self):
        from client.app.content.tools.tabs.deep_sec import _grant_preview

        sql = _grant_preview("G", ["SELECT"], "EMP", ["SALARY"], "All columns except", "", "ANALYST")
        assert "ALL COLUMNS EXCEPT SALARY" in sql
        assert "ON EMP" in sql
        assert "TO ANALYST" in sql

    def test_preview_with_predicate(self):
        from client.app.content.tools.tabs.deep_sec import _grant_preview

        sql = _grant_preview("G", ["SELECT"], "EMP", [], "All columns", "dept = 10", "ANALYST")
        assert "WHERE dept = 10" in sql


class TestPathEncoding:
    """Identifier path segments must be URL-encoded (Oracle names may contain '#')."""

    def test_fetch_columns_encodes_hash(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", return_value=[]) as mock_get,
        ):
            from client.app.content.tools.tabs.deep_sec import _fetch_columns

            _fetch_columns("A#B")

        assert mock_get.call_args[0][0] == "deepsec/objects/A%23B/columns"

    def test_render_delete_encodes_hash(self, mock_st):
        col0, col1 = MagicMock(), MagicMock()
        col0.selectbox.return_value = "A#B"
        col1.button.return_value = True
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = [col0, col1]
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_delete") as mock_del,
        ):
            from client.app.content.tools.tabs.deep_sec import _render_delete

            _render_delete(["A#B"], True, "deepsec/data-roles", "Drop", "dropped", "k")

        assert mock_del.call_args[0][0] == "deepsec/data-roles/A%23B"


class TestCapabilityDrivenListing:
    """Listing must honor the get_status capability flags, not error out."""

    def test_data_roles_skips_fetch_when_listing_unavailable(self, mock_st):
        caps = {"list_data_roles": False, "create_data_role": True, "drop_data_role": True}
        mock_st.form_submit_button.return_value = False
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get") as mock_get,
            patch(f"{MODULE}.is_authenticated", return_value=True),
        ):
            from client.app.content.tools.tabs.deep_sec import _render_data_roles

            result = _render_data_roles(caps, True)

        mock_get.assert_not_called()
        mock_st.info.assert_called()
        assert result is None

    def test_end_users_skips_fetch_when_listing_unavailable(self, mock_st):
        caps = {"list_end_users": False, "create_end_user": True, "drop_end_user": True}
        mock_st.form_submit_button.return_value = False
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get") as mock_get,
            patch(f"{MODULE}.is_authenticated", return_value=True),
        ):
            from client.app.content.tools.tabs.deep_sec import _render_end_users

            _render_end_users(caps, True)

        mock_get.assert_not_called()
        mock_st.info.assert_called()

    def test_grant_builder_uses_text_input_when_roles_unknown(self, mock_st):
        mock_st.selectbox.return_value = "T1"
        mock_st.button.return_value = False
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", return_value=[]),
        ):
            from client.app.content.tools.tabs.deep_sec import _render_grant_builder

            _render_grant_builder([{"name": "T1", "type": "TABLE"}], None, True)

        text_labels = [str(c.args[0]) for c in mock_st.text_input.call_args_list if c.args]
        select_labels = [str(c.args[0]) for c in mock_st.selectbox.call_args_list if c.args]
        assert any("Grant to data role" in lbl for lbl in text_labels)
        assert not any("Grant to data role" in lbl for lbl in select_labels)
