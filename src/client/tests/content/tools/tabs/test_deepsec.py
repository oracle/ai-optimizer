"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.tools.tabs.deepsec
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

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

    def test_delete_data_grant_encodes_hash(self, mock_st):
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_delete") as mock_del,
        ):
            from client.app.content.tools.tabs.deepsec import _delete_data_grant

            assert _delete_data_grant("A#B") is True

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
        assert mock_post.call_args[1]["timeout"] == 60
        # No prior override → enabled carried through as the default False (selecting a user does
        # not auto-enable; the sidebar toggle does). It must always be sent so the field-merge can
        # restore it after a stale-reconnect resets it server-side.
        assert mock_upd.call_args[0][0] == {
            "deep_data_security": {
                "enabled": False,
                "end_user": "SCOUT1",
                "alias": "CORE::SCOUT1",
                "base_alias": "CORE",
            }
        }

    def test_set_connect_as_preserves_enabled_across_stale_reconnect(self, mock_st):
        """An already-enabled override must stay enabled after re-establishing the connection.

        The server tears down a stale managed connection (resetting enabled→False) before
        re-registering, so the field-merge must carry the prior enabled flag or chat tools
        silently stop using DDS while the UI reports success.
        """
        resp = {"alias": "CORE::SCOUT1", "base_alias": "CORE", "end_user": "SCOUT1"}
        state = _state()
        state["settings"]["client_settings"]["deep_data_security"] = {
            "enabled": True,
            "end_user": "SCOUT1",
            "alias": "CORE::SCOUT1",
            "base_alias": "CORE",
        }
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_post", return_value=resp),
            patch(f"{MODULE}.helpers.update_client_settings") as mock_upd,
        ):
            from client.app.content.tools.tabs.deepsec import _set_connect_as

            assert _set_connect_as("SCOUT1") is True

        assert mock_upd.call_args[0][0] == {
            "deep_data_security": {
                "enabled": True,
                "end_user": "SCOUT1",
                "alias": "CORE::SCOUT1",
                "base_alias": "CORE",
            }
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

    def test_connect_as_sole_user_auto_establishes_once(self, mock_st):
        """One end user, no saved override → connect-as is *established* (not just shown selected).

        Streamlit never fires on_change for a default index, so the sole-user auto-selection must
        call _set_connect_as itself; otherwise deep_data_security stays unset and the tools keep
        using the base database user while the UI claims they connect as that end user.
        """
        state = _state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._set_connect_as", return_value=True) as mock_set,
        ):
            from client.app.content.tools.tabs.deepsec import _render_connect_as

            _render_connect_as([{"name": "SCOUT1"}], True)

        mock_set.assert_called_once_with("SCOUT1")
        # The sole user is reflected as the selected option (options == ["— none —", "SCOUT1"]).
        assert mock_st.selectbox.call_args.kwargs["index"] == 1

    def test_connect_as_does_not_re_establish_after_clear(self, mock_st):
        """Once auto-defaulted for this database, clearing to '— none —' must not re-establish it."""
        state = _state()
        state["_ds_autodefault_alias"] = "CORE"  # already auto-defaulted this database
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._set_connect_as", return_value=True) as mock_set,
        ):
            from client.app.content.tools.tabs.deepsec import _render_connect_as

            _render_connect_as([{"name": "SCOUT1"}], True)

        mock_set.assert_not_called()
        assert mock_st.selectbox.call_args.kwargs["index"] == 0

    def test_connect_as_multiple_users_no_auto_select(self, mock_st):
        """With more than one end user there is no obvious default — leave it on '— none —'."""
        state = _state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._set_connect_as", return_value=True) as mock_set,
        ):
            from client.app.content.tools.tabs.deepsec import _render_connect_as

            _render_connect_as([{"name": "SCOUT1"}, {"name": "SCOUT2"}], True)

        mock_set.assert_not_called()
        assert mock_st.selectbox.call_args.kwargs["index"] == 0

    def test_connect_as_unauthenticated_does_not_establish(self, mock_st):
        """When the control is disabled (unauthenticated), do not establish a connection."""
        state = _state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._set_connect_as", return_value=True) as mock_set,
        ):
            from client.app.content.tools.tabs.deepsec import _render_connect_as

            _render_connect_as([{"name": "SCOUT1"}], False)

        mock_set.assert_not_called()

    def test_connect_as_reflects_saved_override_for_active_db(self, mock_st):
        """A saved override belonging to the active database is reflected as the selected option."""
        state = _state()
        state["settings"]["client_settings"]["deep_data_security"] = {"end_user": "SCOUT1", "base_alias": "CORE"}
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.tools.tabs.deepsec import _render_connect_as

            _render_connect_as([{"name": "SCOUT1"}, {"name": "SCOUT2"}], True)

        # options == ["— none —", "SCOUT1", "SCOUT2"] → SCOUT1 is index 1
        assert mock_st.selectbox.call_args.kwargs["index"] == 1

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

    @staticmethod
    def _cols_with_dead_buttons(widths, **_kw):
        """st.columns side_effect whose column buttons never fire (Create/Save/Delete/Cancel)."""
        n = widths if isinstance(widths, int) else len(widths)
        out = []
        for _ in range(n):
            col = MagicMock()
            col.button.return_value = False
            out.append(col)
        return out

    def test_grant_dialog_uses_text_input_when_roles_unknown(self, mock_st):
        mock_st.selectbox.return_value = "T1"
        mock_st.button.return_value = False
        mock_st.columns.side_effect = self._cols_with_dead_buttons

        def _api_get(path, **_kwargs):
            return [{"name": "T1", "type": "TABLE"}] if path == "deepsec/objects" else []

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", side_effect=_api_get),
        ):
            from client.app.content.tools.tabs.deepsec import _data_grant_dialog

            # Call the underlying function (skip the @st.dialog decorator)
            getattr(_data_grant_dialog, "__wrapped__")({"manage_data_grants": True}, True, "add", None)

        text_labels = [str(c.args[0]) for c in mock_st.text_input.call_args_list if c.args]
        select_labels = [str(c.args[0]) for c in mock_st.selectbox.call_args_list if c.args]
        assert any("Grant to data role" in lbl for lbl in text_labels)
        assert not any("Grant to data role" in lbl for lbl in select_labels)

    def test_grant_dialog_edit_prefills_and_saves_with_or_replace(self, mock_st):
        """Editing a grant locks the name, pre-selects its fields, and saves via CREATE OR REPLACE."""
        # Fire only the primary "Save" button (column 0); leave Delete/Cancel inert.
        save_col, delete_col, cancel_col = MagicMock(), MagicMock(), MagicMock()
        save_col.button.return_value = True
        delete_col.button.return_value = False
        cancel_col.button.return_value = False
        mock_st.columns.side_effect = [[save_col, delete_col, cancel_col]]
        mock_st.selectbox.side_effect = lambda label, options, **kw: options[kw.get("index", 0)]
        mock_st.radio.side_effect = lambda label, options, **kw: options[kw.get("index", 0)]
        mock_st.multiselect.side_effect = lambda label, options, **kw: kw.get("default", [])

        grant = {
            "name": "G1",
            "grantee": "ANALYST",
            "object": "HR.EMP",
            "object_name": "EMP",
            "privileges": ["SELECT"],
            "columns": ["SALARY"],
            "all_columns_except": True,
            "predicate": "dept = 10",
            "uniform_columns": True,
        }

        def _api_get(path, **_kwargs):
            if path == "deepsec/objects":
                return [{"name": "EMP", "type": "TABLE"}]
            return ["SALARY", "NAME"]  # columns

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", side_effect=_api_get),
            patch(f"{MODULE}.api_post") as mock_post,
        ):
            from client.app.content.tools.tabs.deepsec import _data_grant_dialog

            getattr(_data_grant_dialog, "__wrapped__")(
                {"manage_data_grants": True}, True, "edit", [{"name": "ANALYST"}], grant
            )

        # Name field is rendered read-only with the grant's name.
        name_call = next(c for c in mock_st.text_input.call_args_list if c.args and "name" in str(c.args[0]).lower())
        assert name_call.kwargs.get("value") == "G1"
        assert name_call.kwargs.get("disabled") is True
        # Save issued a CREATE OR REPLACE for the same grant.
        payload = mock_post.call_args.kwargs["json"]
        assert payload["or_replace"] is True
        assert payload["name"] == "G1"
        assert payload["all_columns_except"] is True
        assert payload["object_name"] == "EMP"

    def test_grant_dialog_blocks_edit_of_non_uniform_grant(self, mock_st):
        """A grant whose columns differ per privilege can't be edited without flattening it: the
        builder warns and disables Save (Delete is still allowed) rather than silently rewriting."""
        save_col, delete_col, cancel_col = MagicMock(), MagicMock(), MagicMock()
        for col in (save_col, delete_col, cancel_col):
            col.button.return_value = False
        mock_st.columns.side_effect = [[save_col, delete_col, cancel_col]]
        mock_st.selectbox.side_effect = lambda label, options, **kw: options[kw.get("index", 0)] if options else None
        mock_st.radio.side_effect = lambda label, options, **kw: options[kw.get("index", 0)]
        mock_st.multiselect.side_effect = lambda label, options, **kw: kw.get("default", [])

        grant = {
            "name": "G1",
            "grantee": "ANALYST",
            "object": "HR.EMP",
            "object_name": "EMP",
            "privileges": ["SELECT", "UPDATE"],
            "columns": ["SALARY", "NAME"],
            "all_columns_except": False,
            "predicate": "",
            "uniform_columns": False,  # SELECT(SALARY) + UPDATE(NAME) — not representable in the builder
        }

        def _api_get(path, **_kwargs):
            return [{"name": "EMP", "type": "TABLE"}] if path == "deepsec/objects" else ["SALARY", "NAME"]

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", _state()),
            patch(f"{MODULE}.api_get", side_effect=_api_get),
            patch(f"{MODULE}.api_post") as mock_post,
        ):
            from client.app.content.tools.tabs.deepsec import _data_grant_dialog

            getattr(_data_grant_dialog, "__wrapped__")(
                {"manage_data_grants": True}, True, "edit", [{"name": "ANALYST"}], grant
            )

        mock_st.warning.assert_called_once()
        assert save_col.button.call_args.kwargs.get("disabled") is True
        mock_post.assert_not_called()


class TestGroupGrants:
    """Collapsing USER_DATA_GRANTS rows must flag grants the simplified builder can't edit faithfully."""

    def test_flags_per_privilege_column_difference(self):
        from client.app.content.tools.tabs.deepsec import _group_grants

        rows = [
            {"name": "G", "privilege": "SELECT", "column_name": "SALARY", "object_name": "EMP"},
            {"name": "G", "privilege": "UPDATE", "column_name": "NAME", "object_name": "EMP"},
        ]
        [grouped] = _group_grants(rows)
        assert grouped["uniform_columns"] is False

    def test_uniform_when_privileges_share_columns(self):
        from client.app.content.tools.tabs.deepsec import _group_grants

        rows = [
            {"name": "G", "privilege": "SELECT", "column_name": "SALARY", "object_name": "EMP"},
            {"name": "G", "privilege": "UPDATE", "column_name": "SALARY", "object_name": "EMP"},
        ]
        [grouped] = _group_grants(rows)
        assert grouped["uniform_columns"] is True

    def test_delete_privilege_does_not_break_uniformity(self):
        """DELETE is row-level and carries no columns, so it must not count as a differing column spec."""
        from client.app.content.tools.tabs.deepsec import _group_grants

        rows = [
            {"name": "G", "privilege": "SELECT", "column_name": "SALARY", "object_name": "EMP"},
            {"name": "G", "privilege": "DELETE", "column_name": None, "object_name": "EMP"},
        ]
        [grouped] = _group_grants(rows)
        assert grouped["uniform_columns"] is True


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
