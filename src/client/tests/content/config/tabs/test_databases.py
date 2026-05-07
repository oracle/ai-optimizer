"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.config.tabs.databases
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

import httpx

MODULE = "client.app.content.config.tabs.databases"
HELPERS_MODULE = "client.app.core.helpers"


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


class TestBuildPayload:
    """Test build_payload helper (moved to helpers module)."""

    def test_excludes_none_values(self):
        """Keys with None values are omitted from the payload."""
        from client.app.core.helpers import build_payload

        assert build_payload({"username": "admin", "password": None, "dsn": "orcl"}) == {
            "username": "admin",
            "dsn": "orcl",
        }

    def test_empty_dict(self):
        """An empty input returns an empty payload."""
        from client.app.core.helpers import build_payload

        assert build_payload({}) == {}

    def test_all_none(self):
        """When every value is None the payload is empty."""
        from client.app.core.helpers import build_payload

        assert build_payload({"a": None, "b": None}) == {}

    def test_all_present(self):
        """When no values are None the payload is returned unchanged."""
        from client.app.core.helpers import build_payload

        data = {"username": "u", "password": "p", "dsn": "d", "wallet_password": "w"}
        assert build_payload(data) == data


class TestFetchDatabase:
    """Test _fetch_database helper."""

    def test_returns_config_on_success(self):
        """Successful GET returns the full database config dict."""
        from client.app.content.config.tabs.databases import _fetch_database

        expected = {"alias": "MYDB", "username": "admin"}
        with patch(f"{MODULE}.api_get", return_value=expected):
            assert _fetch_database("MYDB") == expected

    def test_returns_none_on_http_error(self):
        """HTTPStatusError (e.g. 404) is caught and None is returned."""
        from client.app.content.config.tabs.databases import _fetch_database

        mock_resp = MagicMock(status_code=404)
        error = httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_resp)
        with patch(f"{MODULE}.api_get", side_effect=error):
            assert _fetch_database("MISSING") is None


# ---------------------------------------------------------------------------
# Create flow
# ---------------------------------------------------------------------------


class TestCreateDatabase:
    """After a successful create the UI should set pending selection, alias, and call api_post with toast."""

    def _run_create(self, make_state, mock_st, form_alias="NEW_DB", api_result=None):
        """Call _handle_form_submit in the create path."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state()
        api_result = api_result or {"alias": form_alias, "usable": True}

        mock_api_post = MagicMock(return_value=api_result)

        form_data = {"username": "user", "password": "pass", "dsn": "orcl", "wallet_password": None}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as mock_helpers,
            patch(f"{MODULE}.api_post", mock_api_post),
        ):
            _handle_form_submit("Add New...", True, form_alias, form_data, {})

        return state, mock_api_post, mock_helpers

    def test_sets_pending_db_select(self, make_state, mock_st):
        """_pending_db_select is set so the selectbox switches on the next rerun."""
        state, _, _ = self._run_create(make_state, mock_st, "MY_DB")
        assert state.get("_pending_db_select") == "MY_DB"

    def test_sets_client_settings_alias(self, make_state, mock_st):
        """sync_client_setting is called with the newly created alias."""
        _, _, mock_helpers = self._run_create(make_state, mock_st, "MY_DB")
        mock_helpers.sync_client_setting.assert_called_with("database", "alias", "MY_DB")

    def test_api_post_called_with_toast(self, make_state, mock_st):
        """api_post is called with a toast message containing the new alias."""
        _, mock_post, _ = self._run_create(make_state, mock_st, "MY_DB")
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs.get("toast") and "MY_DB" in kwargs["toast"]

    def test_strips_alias_whitespace(self, make_state, mock_st):
        """Leading/trailing whitespace is stripped from the alias before use."""
        state, _, mock_helpers = self._run_create(make_state, mock_st, "  SPACED  ")
        assert state.get("_pending_db_select") == "SPACED"
        mock_helpers.sync_client_setting.assert_called_with("database", "alias", "SPACED")

    def test_connection_error_shows_warning(self, make_state, mock_st):
        """When the API returns an error field, st.warning is called."""
        self._run_create(
            make_state,
            mock_st,
            "BAD",
            api_result={"alias": "BAD", "usable": False, "error": "ORA-12541: TNS:no listener"},
        )
        warning_messages = [call.args[0] for call in mock_st.warning.call_args_list]
        assert any("ORA-12541" in m for m in warning_messages)
        assert any("Saved, but connection failed" in m for m in warning_messages)

    def test_no_warning_on_success(self, make_state, mock_st):
        """A successful create with no connection error does not call st.warning."""
        self._run_create(make_state, mock_st, "GOOD")
        # st.warning should not be called for connection errors (may be called by other code)
        warning_messages = [call.args[0] for call in mock_st.warning.call_args_list]
        assert not any("connection failed" in m for m in warning_messages)


# ---------------------------------------------------------------------------
# Pending selection application
# ---------------------------------------------------------------------------


class TestPendingDbSelect:
    """_pending_db_select must be written to the widget key before the selectbox is instantiated."""

    def _run_display(self, mock_st, state):
        """Render display_databases without submitting the form."""
        mock_st.selectbox.return_value = state.get("runtime_database_selector", "CORE")
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        aliases = [c["alias"] for c in state["settings"]["database_configs"]]
        lookup = {a: {"alias": a} for a in aliases}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_get", return_value={"alias": "CORE"}),
        ):
            hlp.state_configs_lookup.return_value = lookup
            hlp.selectbox_index.return_value = 0

            from client.app.content.config.tabs.databases import display_databases

            display_databases()

    def test_pending_applied_to_widget_key(self, make_state, mock_st):
        """When _pending_db_select matches an option, runtime_database_selector is set."""
        state = make_state(["CORE", "NEW_DB"], "CORE", {"_pending_db_select": "NEW_DB"})
        self._run_display(mock_st, state)

        assert "_pending_db_select" not in state
        assert state["runtime_database_selector"] == "NEW_DB"

    def test_pending_ignored_when_not_in_options(self, make_state, mock_st):
        """When _pending_db_select refers to a missing alias, the widget key is not set."""
        state = make_state(["CORE"], "CORE", {"_pending_db_select": "GONE"})
        self._run_display(mock_st, state)

        assert "_pending_db_select" not in state
        assert "runtime_database_selector" not in state

    def test_no_pending_leaves_state_unchanged(self, make_state, mock_st):
        """Without _pending_db_select, runtime_database_selector is not touched."""
        state = make_state(["CORE"], "CORE")
        self._run_display(mock_st, state)

        assert "runtime_database_selector" not in state

    def test_core_fields_disabled_when_core_connected(self, make_state):
        """CORE database shows informational lock message and disables fields when usable."""
        from client.app.content.config.tabs.databases import _render_databases

        state = make_state(["CORE"], "CORE")
        state.settings["database_configs"][0]["usable"] = True

        mock_st = MagicMock()
        mock_st.selectbox.return_value = "CORE"
        mock_st.text_input.side_effect = ["CORE", "user", "pass", "dsn", "wallet"]
        mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
        mock_st.button.return_value = False

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._fetch_database", return_value={"alias": "CORE", "usable": True}),
            patch(f"{MODULE}.api_put"),
        ):
            hlp.selectbox_index.return_value = 0
            selected, is_new = _render_databases({"CORE": {"alias": "CORE", "usable": True}}, ["CORE"], "CORE")

        assert selected == "CORE" and not is_new
        mock_st.info.assert_called_once()
        alias_call = next(call for call in mock_st.text_input.mock_calls if call.kwargs["key"].endswith("alias_CORE"))
        assert alias_call.kwargs.get("disabled") is True

        other_calls = [call for call in mock_st.text_input.mock_calls if not call.kwargs["key"].endswith("alias_CORE")]
        assert all(call.kwargs.get("disabled") is True for call in other_calls)


class TestSelectionSyncsClientSettings:
    """_on_database_change calls sync_client_setting to persist the selection."""

    def test_different_database_syncs(self):
        """Selecting a different database calls sync_client_setting."""
        from client.app.content.config.tabs.databases import _on_database_change

        state = {"runtime_database_selector": "OTHER"}

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            _on_database_change()

        hlp.sync_client_setting.assert_called_once_with("database", "alias", "OTHER")

    def test_add_new_does_not_sync(self):
        """Selecting 'Add New...' does NOT call sync_client_setting."""
        from client.app.content.config.tabs.databases import _on_database_change

        state = {"runtime_database_selector": "Add New..."}

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            _on_database_change()

        hlp.sync_client_setting.assert_not_called()

    def test_clears_runtime_state(self):
        """clear_runtime_state is called and selection is preserved."""
        from client.app.content.config.tabs.databases import _on_database_change

        state = {"runtime_database_selector": "MYDB"}

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            _on_database_change()

        hlp.clear_runtime_state.assert_called_once()
        assert state["runtime_database_selector"] == "MYDB"

    def test_none_selection_does_not_sync_or_restore(self):
        """When runtime_database_selector is absent, nothing is synced or restored."""
        from client.app.content.config.tabs.databases import _on_database_change

        state = {}

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            _on_database_change()

        hlp.clear_runtime_state.assert_called_once()
        hlp.sync_client_setting.assert_not_called()
        assert "runtime_database_selector" not in state


class TestConnectionStatus:
    """Connection status display for non-CORE databases."""

    def _run_render(self, make_state, usable):
        """Render _render_databases for a single database with the given usable flag."""
        from client.app.content.config.tabs.databases import _render_databases

        state = make_state(["MYDB"], "MYDB")
        mock_st = MagicMock()
        mock_st.selectbox.return_value = "MYDB"
        mock_st.text_input.side_effect = ["MYDB", "user", "pass", "dsn", "wallet"]
        mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
        mock_st.button.return_value = False
        mock_st.popover.return_value.__enter__ = MagicMock()
        mock_st.popover.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._fetch_database", return_value={"alias": "MYDB", "usable": usable}),
        ):
            hlp.selectbox_index.return_value = 0
            _render_databases({"MYDB": {"alias": "MYDB", "usable": usable}}, ["MYDB"], "MYDB")

        return mock_st


class TestNoChangeDetection:
    """No-change detection toasts when saving unchanged configs."""

    def test_no_changes_shows_toast(self, make_state, mock_st):
        """Saving unchanged data on update shows 'No changes detected' toast."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state(["MYDB"], "MYDB")
        db_config = {
            "username": "user",
            "password": "pass",
            "dsn": "dsn",
            "wallet_password": None,
            "usable": True,
        }
        form_data = {"username": "user", "password": "pass", "dsn": "dsn", "wallet_password": None}

        with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.state", state), patch(f"{MODULE}.helpers"):
            _handle_form_submit("MYDB", False, "MYDB", form_data, db_config)

        mock_st.toast.assert_called_once()
        assert "No changes" in mock_st.toast.call_args[0][0]

    def test_no_changes_but_disconnected_proceeds_to_api(self, make_state, mock_st):
        """Unchanged form still calls api_put when db is not usable (disconnected retry)."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state(["MYDB"], "MYDB")
        db_config = {
            "username": "user",
            "password": "pass",
            "dsn": "dsn",
            "wallet_password": None,
            "usable": False,
        }
        form_data = {"username": "user", "password": "pass", "dsn": "dsn", "wallet_password": None}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers"),
            patch(f"{MODULE}.api_put", return_value={"alias": "MYDB", "usable": True}) as mock_put,
        ):
            _handle_form_submit("MYDB", False, "MYDB", form_data, db_config)

        mock_put.assert_called_once()
        for call in mock_st.toast.call_args_list:
            assert "No changes" not in call.args[0]

    def test_changes_proceed_to_api(self, make_state, mock_st):
        """When form data differs from db_config, api_put is called."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state(["MYDB"], "MYDB")
        db_config = {"username": "old_user", "password": "pass", "dsn": "dsn", "wallet_password": None}
        form_data = {"username": "new_user", "password": "pass", "dsn": "dsn", "wallet_password": None}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers"),
            patch(f"{MODULE}.api_put", return_value={"alias": "MYDB", "usable": True}) as mock_put,
        ):
            _handle_form_submit("MYDB", False, "MYDB", form_data, db_config)

        mock_put.assert_called_once()

    def test_create_skips_no_change_check(self, make_state, mock_st):
        """Create path (is_new=True) skips the no-change detection."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state()
        form_data = {"username": "user", "password": "pass", "dsn": "dsn", "wallet_password": None}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers"),
            patch(f"{MODULE}.api_post", return_value={"alias": "NEW_DB", "usable": True}) as mock_post,
        ):
            _handle_form_submit("Add New...", True, "NEW_DB", form_data, {})

        mock_post.assert_called_once()


class TestConfirmRemove(TestConnectionStatus):
    """Confirm delete button triggers removal handler."""

    def test_confirm_remove_invokes_helper(self, make_state, mock_st):
        """Clicking confirm-delete calls _remove_database with the alias."""
        from client.app.content.config.tabs.databases import display_databases

        state = make_state(["MYDB"], "MYDB")

        def _capture(widths):
            return [MagicMock() for _ in widths]

        mock_st.selectbox.return_value = "MYDB"
        mock_st.text_input.side_effect = ["MYDB", "user", "pass", "dsn", "wallet"]
        mock_st.columns.side_effect = _capture

        def _button_side_effect(*_, **kwargs):
            return kwargs.get("key") == "confirm_delete_db"

        mock_st.button.side_effect = _button_side_effect

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_get", return_value={"alias": "MYDB"}),
            patch(f"{MODULE}._remove_database") as mock_remove,
        ):
            hlp.state_configs_lookup.return_value = {"MYDB": {"alias": "MYDB", "usable": False}}
            hlp.selectbox_index.return_value = 0

            display_databases()

        mock_remove.assert_called_once_with("MYDB")


class TestFetchFallback:
    """When API fetch fails, fallback data from lookup is used."""

    def test_populates_fields_from_lookup_on_fetch_failure(self, make_state):
        """When _fetch_database returns None, form fields use lookup fallback data."""
        from client.app.content.config.tabs.databases import _render_databases

        state = make_state(["MYDB"], "MYDB")

        mock_st = MagicMock()
        mock_st.selectbox.return_value = "MYDB"
        # alias field disabled (False) because not new; remaining values should mirror fallback data
        mock_st.text_input.side_effect = ["MYDB", "user", "pass", "dsn", "wallet"]
        mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
        mock_st.button.return_value = False
        mock_st.popover.return_value.__enter__.return_value = None
        mock_st.popover.return_value.__exit__.return_value = False

        fallback = {
            "alias": "MYDB",
            "username": "user",
            "password": "pass",
            "dsn": "dsn",
            "wallet_password": "wallet",
            "usable": False,
        }

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}._fetch_database", return_value=None),
            patch(f"{MODULE}.api_delete"),
            patch(f"{MODULE}.api_put"),
        ):
            hlp.selectbox_index.return_value = 0
            _render_databases({"MYDB": fallback}, ["MYDB"], "MYDB")

        # The username field receives fallback value (i.e., text_input called with value="user")
        usernames = [
            call.kwargs.get("value")
            for call in mock_st.text_input.mock_calls
            if call.kwargs.get("key", "").startswith("form_db_username")
        ]
        assert usernames == ["user"]


# ---------------------------------------------------------------------------
# Update flow
# ---------------------------------------------------------------------------


class TestUpdateDatabase:
    """Save on an existing database calls api_put and does NOT set pending selection."""

    def _run_update(self, make_state, mock_st, api_result=None):
        """Call _handle_form_submit in the update path."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state(["MYDB"], "MYDB")
        api_result = api_result or {"alias": "MYDB", "usable": True}

        db_config = {"username": "old", "password": "pass", "dsn": "orcl", "wallet_password": ""}
        form_data = {"username": "new_user", "password": "pass", "dsn": "orcl", "wallet_password": None}

        mock_api_put = MagicMock(return_value=api_result)

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers"),
            patch(f"{MODULE}.api_put", mock_api_put),
        ):
            _handle_form_submit("MYDB", False, "MYDB", form_data, db_config)

        return state, mock_api_put

    def test_calls_api_put(self, make_state, mock_st):
        """api_put is called with the correct databases/{alias} path."""
        _, mock_put = self._run_update(make_state, mock_st)
        mock_put.assert_called_once()
        assert mock_put.call_args.args[0] == "databases/MYDB"

    def test_does_not_set_pending(self, make_state, mock_st):
        """Update flow must not set _pending_db_select (only create does)."""
        state, _ = self._run_update(make_state, mock_st)
        assert "_pending_db_select" not in state

    def test_connection_error_shows_warning(self, make_state, mock_st):
        """Connection errors from the server are surfaced via st.warning."""
        self._run_update(
            make_state,
            mock_st,
            api_result={"alias": "MYDB", "usable": False, "error": "DPY-4026: tnsnames.ora missing"},
        )
        warning_messages = [call.args[0] for call in mock_st.warning.call_args_list]
        assert any("DPY-4026" in m for m in warning_messages)


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------


class TestHTTPErrorFeedback:
    """HTTPStatusError from the API is surfaced via st.error."""

    def test_create_409_shows_detail(self, make_state, mock_st):
        """A 409 Conflict response surfaces the detail message via st.error."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state()
        mock_resp = MagicMock(status_code=409, content=b'{"detail":"already exists"}')
        mock_resp.json.return_value = {"detail": "Database config already exists: DUP"}
        error = httpx.HTTPStatusError("Conflict", request=MagicMock(), response=mock_resp)

        form_data = {"username": "u", "password": "p", "dsn": "d", "wallet_password": ""}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_post", side_effect=error),
        ):
            from client.app.core.helpers import extract_error_detail

            hlp.extract_error_detail.side_effect = extract_error_detail
            _handle_form_submit("Add New...", True, "DUP", form_data, {})

        error_messages = [call.args[0] for call in mock_st.error.call_args_list]
        assert any("already exists" in m for m in error_messages)


# ---------------------------------------------------------------------------
# Refresh settings helper
# ---------------------------------------------------------------------------


class TestRefreshSettings:
    """Test refresh_settings helper (moved to helpers module)."""

    def test_updates_session_state_when_settings_returned(self, make_state):
        """When get_server_settings returns data, state.settings is replaced."""
        from client.app.core.helpers import refresh_settings

        state = make_state(extra={"optimizer_client": "test-client"})
        new_settings = {"settings": "updated"}

        with (
            patch(f"{HELPERS_MODULE}.state", state),
            patch(f"{HELPERS_MODULE}.get_server_settings", return_value=new_settings),
        ):
            refresh_settings()

        assert state.settings == new_settings

    def test_clears_runtime_state_when_settings_returned(self, make_state):
        """Runtime keys are purged after settings are successfully fetched."""
        from client.app.core.helpers import refresh_settings

        state = make_state(extra={"runtime_foo": "bar", "runtime_baz": 42, "optimizer_client": "test-client"})
        new_settings = {"settings": "updated"}

        with (
            patch(f"{HELPERS_MODULE}.state", state),
            patch(f"{HELPERS_MODULE}.get_server_settings", return_value=new_settings),
        ):
            refresh_settings()

        assert "runtime_foo" not in state
        assert "runtime_baz" not in state

    def test_no_update_when_server_returns_none(self, make_state):
        """state.settings remains unchanged if get_server_settings returns None."""
        from client.app.core.helpers import refresh_settings

        state = make_state(extra={"optimizer_client": "test-client"})
        original_settings = state.settings

        with (
            patch(f"{HELPERS_MODULE}.state", state),
            patch(f"{HELPERS_MODULE}.get_server_settings", return_value=None),
        ):
            refresh_settings()

        assert state.settings is original_settings

    def test_no_clear_runtime_state_when_server_returns_none(self, make_state):
        """Runtime keys are preserved when get_server_settings returns None."""
        from client.app.core.helpers import refresh_settings

        state = make_state(extra={"runtime_foo": "bar", "optimizer_client": "test-client"})

        with (
            patch(f"{HELPERS_MODULE}.state", state),
            patch(f"{HELPERS_MODULE}.get_server_settings", return_value=None),
        ):
            refresh_settings()

        assert state["runtime_foo"] == "bar"


# ---------------------------------------------------------------------------
# Sync client setting helper
# ---------------------------------------------------------------------------


class TestSyncClientSetting:
    """Test sync_client_setting updates state and calls api_put."""

    def test_updates_state_and_calls_api(self, make_state):
        """sync_client_setting writes to session state and calls api_put."""
        from client.app.core.helpers import sync_client_setting

        state = make_state(["CORE"], "CORE", extra={"optimizer_client": "test-client"})
        server_response = {"database": {"alias": "NEW", "extra": "from_server"}, "oci": {}}
        mock_put = MagicMock(return_value=server_response)

        with (
            patch(f"{HELPERS_MODULE}.state", state),
            patch(f"{HELPERS_MODULE}.api_put", mock_put),
        ):
            sync_client_setting("database", "alias", "NEW")

        assert state["settings"]["client_settings"] == server_response
        mock_put.assert_called_once_with(
            "settings", json={"database": {"alias": "NEW"}}, params={"client": "test-client"}
        )

    def test_api_error_still_updates_state(self, make_state):
        """HTTPStatusError from api_put is swallowed; state is still updated."""
        from client.app.core.helpers import sync_client_setting

        state = make_state(["CORE"], "CORE", extra={"optimizer_client": "test-client"})
        mock_resp = MagicMock(status_code=500)
        error = httpx.HTTPStatusError("fail", request=MagicMock(), response=mock_resp)

        with (
            patch(f"{HELPERS_MODULE}.state", state),
            patch(f"{HELPERS_MODULE}.api_put", side_effect=error),
        ):
            sync_client_setting("database", "alias", "NEW")

        assert state["settings"]["client_settings"]["database"]["alias"] == "NEW"


# ---------------------------------------------------------------------------
# Handle form submit edge cases
# ---------------------------------------------------------------------------


class TestHandleFormSubmitValidation:
    """Validation paths for _handle_form_submit."""

    def test_alias_required_shows_error(self, make_state, mock_st):
        """Empty alias during create shows st.error and returns."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state()

        with patch(f"{MODULE}.state", state), patch(f"{MODULE}.st", mock_st):
            _handle_form_submit("Add New...", True, "  ", {}, {})

        mock_st.error.assert_called_once_with("Alias is required.")


class TestHandleFormSubmitTimeout:
    """Timeout handling in _handle_form_submit."""

    def test_timeout_shows_generic_message(self, make_state, mock_st):
        """TimeoutException without wallet_password shows generic error via st.error."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state(["MYDB"], "MYDB")
        db_config = {"username": "old"}
        form_data = {"username": "user"}

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_put", side_effect=httpx.TimeoutException("timed out")),
        ):
            _handle_form_submit("MYDB", False, "MYDB", form_data, db_config)

        error_messages = [call.args[0] for call in mock_st.error.call_args_list]
        assert any("timed out" in m for m in error_messages)
        assert not any("wallet" in m.lower() for m in error_messages)

    def test_timeout_with_wallet_includes_wallet_hint(self, make_state, mock_st):
        """TimeoutException with wallet_password includes wallet verification hint."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state(["MYDB"], "MYDB")
        db_config = {"username": "old"}
        form_data = {"username": "user", "wallet_password": "secret"}

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_put", side_effect=httpx.TimeoutException("timed out")),
        ):
            _handle_form_submit("MYDB", False, "MYDB", form_data, db_config)

        error_messages = [call.args[0] for call in mock_st.error.call_args_list]
        assert any("wallet" in m.lower() for m in error_messages)

    def test_timeout_uses_45s_on_create(self, make_state, mock_st):
        """api_post is called with timeout=45 during create."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state()
        mock_api_post = MagicMock(return_value={"alias": "NEW_DB", "usable": True})

        form_data = {"username": "user", "password": "pass", "dsn": "orcl", "wallet_password": ""}

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers"),
            patch(f"{MODULE}.api_post", mock_api_post),
        ):
            _handle_form_submit("Add New...", True, "NEW_DB", form_data, {})

        _, kwargs = mock_api_post.call_args
        assert kwargs["timeout"] == 45

    def test_timeout_uses_45s_on_update(self, make_state, mock_st):
        """api_put is called with timeout=45 during update."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state(["MYDB"], "MYDB")
        db_config = {"username": "old"}
        form_data = {"username": "new_user", "password": "pass", "dsn": "orcl", "wallet_password": ""}
        mock_api_put = MagicMock(return_value={"alias": "MYDB", "usable": True})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers"),
            patch(f"{MODULE}.api_put", mock_api_put),
        ):
            _handle_form_submit("MYDB", False, "MYDB", form_data, db_config)

        _, kwargs = mock_api_put.call_args
        assert kwargs["timeout"] == 45


class TestHandleFormSubmitErrors:
    """Error handling scenarios for _handle_form_submit."""

    def test_update_http_error_shows_st_error(self, make_state, mock_st):
        """HTTPStatusError during update surfaces detail via st.error."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state(["MYDB"], "MYDB")
        error_detail = "Vector config locked"
        db_config = {"username": "old"}
        form_data = {"username": "user"}

        mock_resp = MagicMock(status_code=500, content=b'{"detail":"Vector config locked"}')
        mock_resp.json.return_value = {"detail": error_detail}
        error = httpx.HTTPStatusError("Server error", request=MagicMock(), response=mock_resp)

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_put", side_effect=error),
        ):
            _handle_form_submit("MYDB", False, "MYDB", form_data, db_config)

        error_messages = [call.args[0] for call in mock_st.error.call_args_list]
        assert any("Vector config locked" in m for m in error_messages)

    def test_empty_response_content_falls_back_to_str(self, make_state, mock_st):
        """When exc.response.content is empty, falls back to str(exc)."""
        from client.app.content.config.tabs.databases import _handle_form_submit

        state = make_state(["MYDB"], "MYDB")
        db_config = {"username": "old"}
        form_data = {"username": "user"}

        mock_resp = MagicMock(status_code=500, content=b"")
        error = httpx.HTTPStatusError("raw error text", request=MagicMock(), response=mock_resp)

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_put", side_effect=error),
        ):
            _handle_form_submit("MYDB", False, "MYDB", form_data, db_config)

        error_messages = [call.args[0] for call in mock_st.error.call_args_list]
        assert any("raw error text" in m for m in error_messages)


# ---------------------------------------------------------------------------
# Remove database helper
# ---------------------------------------------------------------------------


class TestRemoveDatabase:
    """Test _remove_database helper."""

    def test_success_drops_database(self, make_state, mock_st):
        """Successful remove calls API and refreshes settings."""
        from client.app.content.config.tabs.databases import _remove_database

        state = make_state(["MYDB"], "MYDB")
        mock_delete = MagicMock()
        mock_refresh = MagicMock()

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_delete", mock_delete),
            patch(f"{HELPERS_MODULE}.refresh_settings", mock_refresh),
        ):
            _remove_database("MYDB")

        mock_delete.assert_called_once_with("databases/MYDB")
        mock_refresh.assert_called_once()

    def test_http_error_shows_st_error(self, make_state, mock_st):
        """HTTP errors during remove are surfaced via st.error."""
        from client.app.content.config.tabs.databases import _remove_database

        state = make_state(["MYDB"], "MYDB")

        mock_resp = MagicMock(status_code=403, content=b'{"detail":"forbidden"}')
        mock_resp.json.return_value = {"detail": "Forbidden"}
        error = httpx.HTTPStatusError("Forbidden", request=MagicMock(), response=mock_resp)

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_delete", side_effect=error),
            patch(f"{HELPERS_MODULE}.refresh_settings") as mock_refresh,
        ):
            _remove_database("MYDB")

        error_messages = [call.args[0] for call in mock_st.error.call_args_list]
        assert any("Remove failed" in m and "Forbidden" in m for m in error_messages)
        mock_refresh.assert_not_called()


# ---------------------------------------------------------------------------
# Drop vector store callback
# ---------------------------------------------------------------------------


class TestDropVectorStore:
    """Test _drop_vector_store callback."""

    def test_calls_api_delete_with_correct_path(self, make_state):
        """api_delete is called with databases/{alias}/vector-stores/{table} and a toast."""
        from client.app.content.config.tabs.databases import _drop_vector_store

        mock_delete = MagicMock()
        with (
            patch(f"{MODULE}.api_delete", mock_delete),
            patch(f"{HELPERS_MODULE}.refresh_settings"),
            patch(f"{MODULE}.state", make_state()),
        ):
            _drop_vector_store("MYDB", "VS_TABLE")

        mock_delete.assert_called_once_with(
            "databases/MYDB/vector-stores/VS_TABLE",
            toast="Vector store **VS_TABLE** dropped.",
        )

    def test_refreshes_settings_on_success(self, make_state):
        """helpers.refresh_settings is called after a successful drop."""
        from client.app.content.config.tabs.databases import _drop_vector_store

        mock_refresh = MagicMock()
        with (
            patch(f"{MODULE}.api_delete"),
            patch(f"{HELPERS_MODULE}.refresh_settings", mock_refresh),
            patch(f"{MODULE}.state", make_state()),
        ):
            _drop_vector_store("MYDB", "VS_TABLE")

        mock_refresh.assert_called_once()

    def test_http_error_shows_st_error(self, make_state, mock_st):
        """HTTPStatusError from api_delete is surfaced via st.error."""
        from client.app.content.config.tabs.databases import _drop_vector_store

        mock_resp = MagicMock(status_code=404, content=b'{"detail":"not found"}')
        mock_resp.json.return_value = {"detail": "Vector store not found"}
        error = httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_resp)

        state = make_state()
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.api_delete", side_effect=error),
            patch(f"{HELPERS_MODULE}.refresh_settings"),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
        ):
            from client.app.core.helpers import extract_error_detail

            hlp.extract_error_detail.side_effect = extract_error_detail
            _drop_vector_store("MYDB", "MISSING")

        error_messages = [call.args[0] for call in mock_st.error.call_args_list]
        assert any("Drop failed" in m for m in error_messages)


# ---------------------------------------------------------------------------
# Vector Stores display
# ---------------------------------------------------------------------------


class TestVectorStoresDisplay:
    """Test vector stores section in display_databases."""

    _VS = {
        "vector_store": "VS_TABLE_1",
        "alias": "my_vs",
        "embedding_model": {"provider": "cohere", "id": "embed-v3"},
        "chunk_size": 512,
        "chunk_overlap": 50,
        "distance_strategy": "COSINE",
        "index_type": "HNSW",
    }

    def _run_display(self, mock_st, state, lookup, selected="MYDB"):
        """Render display_databases without submitting the form."""
        mock_st.selectbox.return_value = selected
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False
        mock_st.columns.side_effect = lambda widths: [MagicMock() for _ in widths]

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_get", return_value=lookup.get(selected, {})),
        ):
            hlp.state_configs_lookup.return_value = lookup
            hlp.selectbox_index.return_value = 0

            from client.app.content.config.tabs.databases import display_databases

            display_databases()

    def test_subheader_shown_when_vector_stores_exist(self, make_state, mock_st):
        """'Vector Stores' subheader is rendered when the database has vector stores."""
        state = make_state(["MYDB"], "MYDB")
        lookup = {"MYDB": {"alias": "MYDB", "vector_stores": [self._VS]}}
        self._run_display(mock_st, state, lookup)

        subheader_args = [c.args[0] for c in mock_st.subheader.call_args_list if c.args]
        assert "Vector Storage" in subheader_args

    def test_columns_rendered_per_vector_store(self, make_state, mock_st):
        """One header row + one row per vector store are created via st.columns."""
        vs2 = {**self._VS, "vector_store": "VS_TABLE_2", "alias": "my_vs_2"}
        state = make_state(["MYDB"], "MYDB")
        lookup = {"MYDB": {"alias": "MYDB", "vector_stores": [self._VS, vs2]}}
        self._run_display(mock_st, state, lookup)

        # 1 action-buttons + 1 header + 2 vector-store rows = 4
        assert mock_st.columns.call_count == 4

    def test_delete_button_wired_to_callback(self, make_state, mock_st):
        """Delete button on_click is _drop_vector_store with [alias, table_name]."""
        state = make_state(["MYDB"], "MYDB")
        lookup = {"MYDB": {"alias": "MYDB", "vector_stores": [self._VS]}}

        created_cols = []

        def _capture(widths):
            cols = [MagicMock() for _ in widths]
            created_cols.append(cols)
            return cols

        mock_st.selectbox.return_value = "MYDB"
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False
        mock_st.columns.side_effect = _capture

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_get", return_value={"alias": "MYDB"}),
        ):
            hlp.state_configs_lookup.return_value = lookup
            hlp.selectbox_index.return_value = 0

            from client.app.content.config.tabs.databases import _drop_vector_store, display_databases

            display_databases()

        # created_cols: [0]=action_buttons(3), [1]=header(7), [2]=vs_row(7)
        vs_row = created_cols[2]
        vs_row[0].button.assert_called_once()
        _, kwargs = vs_row[0].button.call_args
        assert kwargs["on_click"] is _drop_vector_store
        assert kwargs["args"] == ["MYDB", "VS_TABLE_1"]

    def test_no_vector_stores_shows_message(self, make_state, mock_st):
        """'No Vector Stores Found' is shown when vector_stores list is empty."""
        state = make_state(["MYDB"], "MYDB")
        lookup = {"MYDB": {"alias": "MYDB", "vector_stores": []}}
        self._run_display(mock_st, state, lookup)

        write_args = [c.args[0] for c in mock_st.write.call_args_list if c.args]
        assert "No Vector Stores Found" in write_args

    def test_not_shown_for_new_database(self, make_state, mock_st):
        """Neither subheader nor fallback message appears for 'Add New...'."""
        state = make_state()
        self._run_display(mock_st, state, {}, selected="Add New...")

        subheader_args = [c.args[0] for c in mock_st.subheader.call_args_list if c.args]
        assert "Vector Stores" not in subheader_args
        write_args = [c.args[0] for c in mock_st.write.call_args_list if c.args]
        assert "No Vector Stores Found" not in write_args

    def test_embedding_model_none_displays_empty(self, make_state, mock_st):
        """embedding_model=None renders as empty string."""
        vs = {**self._VS, "embedding_model": None}
        state = make_state(["MYDB"], "MYDB")
        lookup = {"MYDB": {"alias": "MYDB", "vector_stores": [vs]}}

        created_cols = []

        def _capture(widths):
            cols = [MagicMock() for _ in widths]
            created_cols.append(cols)
            return cols

        mock_st.selectbox.return_value = "MYDB"
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False
        mock_st.columns.side_effect = _capture

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_get", return_value={"alias": "MYDB"}),
        ):
            hlp.state_configs_lookup.return_value = lookup
            hlp.selectbox_index.return_value = 0

            from client.app.content.config.tabs.databases import display_databases

            display_databases()

        # vs row is created_cols[2] (after action buttons and header)
        vs_row = created_cols[2]
        model_call = next(c for c in vs_row[2].text_input.call_args_list if c.kwargs.get("key", "").endswith("_model"))
        assert model_call.kwargs["value"] == ""

    def test_embedding_model_string_displays_string(self, make_state, mock_st):
        """embedding_model as a plain string renders via str()."""
        vs = {**self._VS, "embedding_model": "cohere/embed-v3"}
        state = make_state(["MYDB"], "MYDB")
        lookup = {"MYDB": {"alias": "MYDB", "vector_stores": [vs]}}

        created_cols = []

        def _capture(widths):
            cols = [MagicMock() for _ in widths]
            created_cols.append(cols)
            return cols

        mock_st.selectbox.return_value = "MYDB"
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False
        mock_st.columns.side_effect = _capture

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_get", return_value={"alias": "MYDB"}),
        ):
            hlp.state_configs_lookup.return_value = lookup
            hlp.selectbox_index.return_value = 0

            from client.app.content.config.tabs.databases import display_databases

            display_databases()

        vs_row = created_cols[2]
        model_call = next(c for c in vs_row[2].text_input.call_args_list if c.kwargs.get("key", "").endswith("_model"))
        assert model_call.kwargs["value"] == "cohere/embed-v3"


class TestActiveEmbedJobsPanelWiring:
    """The database tab must show the active-embed-jobs panel with
    refresh_on_idle=True so a freshly-completed vector store appears
    without forcing a manual page refresh.

    Placement contract: rendered AFTER ``_render_vector_stores`` so
    the panel appears below the Vector Storage section.
    """

    def test_render_active_embed_jobs_invoked_with_refresh_on_idle(self, make_state, mock_st):
        """display_databases delegates to render_active_embed_jobs(refresh_on_idle=True)."""
        state = make_state(["CORE"], "CORE")
        mock_st.selectbox.return_value = "CORE"
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_get", return_value={"alias": "CORE"}),
            patch(f"{MODULE}.render_active_embed_jobs") as mock_render,
        ):
            hlp.state_configs_lookup.return_value = {"CORE": {"alias": "CORE"}}
            hlp.selectbox_index.return_value = 0

            from client.app.content.config.tabs.databases import display_databases

            display_databases()
        mock_render.assert_called_once_with(refresh_on_idle=True)

    def test_panel_renders_after_vector_storage_section(self, make_state, mock_st):
        """The panel must follow ``_render_vector_stores`` so users see
        it below the Vector Storage table.
        """
        state = make_state(["CORE"], "CORE")
        mock_st.selectbox.return_value = "CORE"
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        call_order: list[str] = []

        def _record(name):
            def _inner(*args, **kwargs):  # noqa: ARG001
                call_order.append(name)

            return _inner

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(f"{MODULE}.api_get", return_value={"alias": "CORE"}),
            patch(
                f"{MODULE}._render_databases",
                side_effect=lambda *a, **k: (call_order.append("databases") or ("CORE", False)),
            ),
            patch(
                f"{MODULE}._render_vector_stores",
                side_effect=_record("vector_stores"),
            ),
            patch(
                f"{MODULE}.render_active_embed_jobs",
                side_effect=_record("panel"),
            ),
        ):
            hlp.state_configs_lookup.return_value = {"CORE": {"alias": "CORE"}}
            hlp.selectbox_index.return_value = 0

            from client.app.content.config.tabs.databases import display_databases

            display_databases()
        assert call_order == ["databases", "vector_stores", "panel"], (
            f"panel must follow Vector Storage section; got {call_order}"
        )

    def test_panel_renders_when_adding_new_database(self, make_state, mock_st):
        """When the user is on Add New (no Vector Storage section),
        the panel still renders so an in-flight job stays visible.
        """
        state = make_state(["CORE"], "CORE")
        mock_st.selectbox.return_value = "Add New..."
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        call_order: list[str] = []

        def _record(name):
            def _inner(*args, **kwargs):  # noqa: ARG001
                call_order.append(name)

            return _inner

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.helpers") as hlp,
            patch(
                f"{MODULE}._render_databases",
                side_effect=lambda *a, **k: (call_order.append("databases") or ("Add New...", True)),
            ),
            patch(
                f"{MODULE}._render_vector_stores",
                side_effect=_record("vector_stores"),
            ),
            patch(
                f"{MODULE}.render_active_embed_jobs",
                side_effect=_record("panel"),
            ),
        ):
            hlp.state_configs_lookup.return_value = {"CORE": {"alias": "CORE"}}
            hlp.selectbox_index.return_value = 0

            from client.app.content.config.tabs.databases import display_databases

            display_databases()
        # On Add New, vector_stores is skipped but the panel still renders.
        assert "vector_stores" not in call_order
        assert call_order == ["databases", "panel"]
