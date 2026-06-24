"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.tools.tabs.deepsec
"""
# spell-checker: disable

from unittest.mock import patch

import pytest

from client.tests.conftest import AttrDict, make_http_error

MODULE = "client.app.content.tools.tabs.deepsec"

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
        "grant_data_roles": True,
        "list_data_roles": True,
        "list_end_users": True,
        "list_data_grants": True,
        "list_data_role_grants": True,
    },
}


def _state():
    return AttrDict(
        {
            "optimizer_client": "client-1",
            "settings": {
                "database_configs": [{"alias": "CORE", "username": "ACADEMY"}],
                "client_settings": {"database": {"alias": "CORE"}},
            },
        }
    )


class TestDisplayDeepSec:
    def test_unavailable_shows_warning_and_skips_sections(self, mock_st):
        status = {"available": False, "version": "23.5.0.0.0", "capabilities": {}}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", return_value=status),
            patch(f"{MODULE}.is_authenticated", return_value=True),
            patch(f"{MODULE}._render_data_roles") as mock_roles,
        ):
            from client.app.content.tools.tabs.deepsec import display_deepsec

            display_deepsec()

        mock_st.warning.assert_called_once()
        mock_roles.assert_not_called()

    def test_available_renders_three_sections(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", return_value=_AVAILABLE),
            patch(f"{MODULE}.is_authenticated", return_value=True),
            patch(f"{MODULE}._render_data_roles") as mock_roles,
            patch(f"{MODULE}._render_end_users") as mock_users,
            patch(f"{MODULE}._render_data_grants") as mock_grants,
        ):
            from client.app.content.tools.tabs.deepsec import display_deepsec

            display_deepsec()

        mock_roles.assert_called_once()
        mock_users.assert_called_once()
        mock_grants.assert_called_once()
        # Roles fetched by the data-roles section flow through to the grant builder.
        assert mock_grants.call_args[0][2] is mock_roles.return_value

    def test_unauthenticated_shows_locked_notice(self, mock_st):
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
            from client.app.content.tools.tabs.deepsec import display_deepsec

            display_deepsec()

        mock_locked.assert_called_once()

    def test_status_error_shows_error_and_returns(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", side_effect=make_http_error(503, "Database is not available")),
            patch(f"{MODULE}._render_data_roles") as mock_roles,
        ):
            from client.app.content.tools.tabs.deepsec import display_deepsec

            display_deepsec()

        mock_st.error.assert_called_once()
        mock_roles.assert_not_called()


class TestGrantPreview:
    def test_preview_incomplete(self):
        from client.app.content.tools.tabs.deepsec import _grant_preview

        assert "complete the fields" in _grant_preview("", [], "", [], "All columns", "", "")

    def test_preview_all_columns_except(self):
        from client.app.content.tools.tabs.deepsec import _grant_preview

        sql = _grant_preview("G", ["SELECT"], "EMP", ["SALARY"], "All columns except", "", "ANALYST")
        assert "ALL COLUMNS EXCEPT SALARY" in sql
        assert "ON EMP" in sql
        assert "TO ANALYST" in sql

    def test_preview_with_predicate(self):
        from client.app.content.tools.tabs.deepsec import _grant_preview

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
            from client.app.content.tools.tabs.deepsec import _fetch_columns

            _fetch_columns("A#B")

        assert mock_get.call_args[0][0] == "deepsec/objects/A%23B/columns"

    def test_delete_data_role_encodes_hash(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_delete") as mock_del,
        ):
            from client.app.content.tools.tabs.deepsec import _delete_data_role

            assert _delete_data_role("A#B") is True

        assert mock_del.call_args[0][0] == "deepsec/data-roles/A%23B"

    def test_delete_end_user_encodes_hash(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_delete") as mock_del,
        ):
            from client.app.content.tools.tabs.deepsec import _delete_end_user

            assert _delete_end_user("A#B") is True

        assert mock_del.call_args[0][0] == "deepsec/end-users/A%23B"

    def test_drop_data_grant_encodes_hash(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_delete") as mock_del,
        ):
            from client.app.content.tools.tabs.deepsec import _drop_data_grant

            _drop_data_grant("A#B")

        assert mock_del.call_args[0][0] == "deepsec/data-grants/A%23B"

    def test_revoke_role_encodes_both_segments(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_delete") as mock_del,
        ):
            from client.app.content.tools.tabs.deepsec import _revoke_role

            assert _revoke_role("A#B", "R#1") is True

        assert mock_del.call_args[0][0] == "deepsec/data-role-grants/A%23B/R%231"

    def test_grant_roles_posts_payload(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_post") as mock_post,
        ):
            from client.app.content.tools.tabs.deepsec import _grant_roles

            assert _grant_roles("EMMA", ["R1", "R2"]) is True

        assert mock_post.call_args[0][0] == "deepsec/data-role-grants"
        assert mock_post.call_args[1]["json"] == {"grantee": "EMMA", "roles": ["R1", "R2"]}


class TestConnectAs:
    """The 'Connect tools as' control posts to the server and updates in-memory settings."""

    def test_set_connect_as_posts_and_updates_in_memory(self, mock_st):
        resp = {"alias": "CORE::SCOUT1", "base_alias": "CORE", "end_user": "SCOUT1"}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_post", return_value=resp) as mock_post,
            patch(f"{MODULE}.helpers.update_client_settings") as mock_upd,
        ):
            from client.app.content.tools.tabs.deepsec import _set_connect_as

            assert _set_connect_as("SCOUT1") is True

        assert mock_post.call_args[0][0] == "deepsec/connect-as"
        assert mock_post.call_args[1]["json"] == {"end_user": "SCOUT1"}
        assert mock_upd.call_args[0][0] == {
            "deep_data_security": {"end_user": "SCOUT1", "alias": "CORE::SCOUT1", "base_alias": "CORE"}
        }

    def test_set_connect_as_failure_resyncs_and_does_not_update(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_post", side_effect=make_http_error(400, "bad creds")),
            patch(f"{MODULE}.helpers.update_client_settings") as mock_upd,
            patch(f"{MODULE}.helpers.refresh_settings") as mock_refresh,
        ):
            from client.app.content.tools.tabs.deepsec import _set_connect_as

            assert _set_connect_as("SCOUT1") is False

        mock_upd.assert_not_called()
        # Re-sync so a server-side stale teardown can't leave the sidebar showing a gone alias.
        mock_refresh.assert_called_once_with(clear_runtime=False)

    def test_clear_connect_as_deletes_and_resets(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_delete") as mock_del,
            patch(f"{MODULE}.helpers.update_client_settings") as mock_upd,
        ):
            from client.app.content.tools.tabs.deepsec import _clear_connect_as

            _clear_connect_as()

        assert mock_del.call_args[0][0] == "deepsec/connect-as"
        assert mock_upd.call_args[0][0] == {
            "deep_data_security": {"enabled": False, "end_user": None, "alias": None, "base_alias": None}
        }


class TestCapabilityDrivenListing:
    """Listing must honor the get_status capability flags, not error out."""

    def test_data_roles_skips_fetch_when_listing_unavailable(self, mock_st):
        caps = {"list_data_roles": False, "create_data_role": True, "drop_data_role": True}
        mock_st.button.return_value = False  # don't trigger the "Create Data Role" dialog
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get") as mock_get,
            patch(f"{MODULE}.is_authenticated", return_value=True),
            patch(f"{MODULE}.helpers.state_configs_lookup", return_value={"CORE": {"username": "ACADEMY"}}),
        ):
            from client.app.content.tools.tabs.deepsec import _render_data_roles

            result = _render_data_roles(caps, True)

        mock_get.assert_not_called()
        mock_st.info.assert_called()
        assert result is None

    def test_end_users_skips_fetch_when_listing_unavailable(self, mock_st):
        caps = {"list_end_users": False, "create_end_user": True, "drop_end_user": True}
        mock_st.button.return_value = False  # don't trigger the "Create End User" dialog
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get") as mock_get,
            patch(f"{MODULE}.is_authenticated", return_value=True),
            patch(f"{MODULE}.helpers.state_configs_lookup", return_value={"CORE": {"username": "ACADEMY"}}),
        ):
            from client.app.content.tools.tabs.deepsec import _render_end_users

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
            from client.app.content.tools.tabs.deepsec import _render_grant_builder

            _render_grant_builder([{"name": "T1", "type": "TABLE"}], None, True)

        text_labels = [str(c.args[0]) for c in mock_st.text_input.call_args_list if c.args]
        select_labels = [str(c.args[0]) for c in mock_st.selectbox.call_args_list if c.args]
        assert any("Grant to data role" in lbl for lbl in text_labels)
        assert not any("Grant to data role" in lbl for lbl in select_labels)


class TestRoleAssignment:
    """Assignment helpers that the create/edit dialogs build on."""

    def test_local_role_names_excludes_mapped(self, mock_st):
        roles = [{"name": "R1", "mapped_to": None}, {"name": "R2", "mapped_to": "AZURE_ROLE=x"}]
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", return_value=roles),
        ):
            from client.app.content.tools.tabs.deepsec import _local_role_names

            assert _local_role_names({"list_data_roles": True}) == ["R1"]

    def test_apply_grant_diff_by_user_grants_added_revokes_removed(self):
        from client.app.content.tools.tabs.deepsec import _apply_grant_diff

        with (
            patch(f"{MODULE}._grant_roles", return_value=True) as grant,
            patch(f"{MODULE}._revoke_role", return_value=True) as revoke,
        ):
            ok = _apply_grant_diff("EMMA", {"R1", "R2"}, {"R2", "R3"}, by_user=True)

        assert ok is True
        grant.assert_called_once_with("EMMA", ["R3"])
        revoke.assert_called_once_with("EMMA", "R1")

    def test_apply_grant_diff_by_role_grants_each_added_user(self):
        from client.app.content.tools.tabs.deepsec import _apply_grant_diff

        with (
            patch(f"{MODULE}._grant_roles", return_value=True) as grant,
            patch(f"{MODULE}._revoke_role", return_value=True) as revoke,
        ):
            ok = _apply_grant_diff("EMPLOYEE_ROLE", {"U1"}, {"U2"}, by_user=False)

        assert ok is True
        grant.assert_called_once_with("U2", ["EMPLOYEE_ROLE"])
        revoke.assert_called_once_with("U1", "EMPLOYEE_ROLE")

    def test_apply_grant_diff_noop_when_unchanged(self):
        from client.app.content.tools.tabs.deepsec import _apply_grant_diff

        with (
            patch(f"{MODULE}._grant_roles", return_value=True) as grant,
            patch(f"{MODULE}._revoke_role", return_value=True) as revoke,
        ):
            ok = _apply_grant_diff("EMMA", {"R1"}, {"R1"}, by_user=True)

        assert ok is True
        grant.assert_not_called()
        revoke.assert_not_called()

    def test_data_roles_table_renders_and_returns_roles(self, mock_st):
        """The roles table renders without error and returns the fetched roles for the grant builder."""
        roles = [{"name": "R1", "mapped_to": None, "enabled_by_default": True}]
        caps = {"list_data_roles": True, "create_data_role": True}
        mock_st.button.return_value = False
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", return_value=roles) as mock_get,
            patch(f"{MODULE}.is_authenticated", return_value=True),
        ):
            from client.app.content.tools.tabs.deepsec import _render_data_roles

            result = _render_data_roles(caps, True)

        assert result == roles
        assert mock_get.call_args_list[0][0][0] == "deepsec/data-roles"
