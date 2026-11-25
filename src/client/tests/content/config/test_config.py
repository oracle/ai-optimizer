"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.config.config
"""
# spell-checker: disable

from unittest.mock import patch

import pytest

from client.tests.conftest import AttrDict, make_mock_tabs

MODULE = "client.app.content.config.config"

pytestmark = pytest.mark.unit


class TestConfigMain:
    """Tests for config.main()."""

    def test_local_admin_users_tab_follows_settings(self, mock_st):
        mock_st.tabs.return_value = make_mock_tabs(7)
        state = AttrDict({"auth_mode": "local_users"})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.is_admin", return_value=True),
            patch(f"{MODULE}.display_settings") as mock_settings,
            patch(f"{MODULE}.display_users") as mock_users,
            patch(f"{MODULE}.display_databases") as mock_db,
            patch(f"{MODULE}.display_models") as mock_models,
            patch(f"{MODULE}.display_oci") as mock_oci,
            patch(f"{MODULE}.display_mcp") as mock_mcp,
            patch(f"{MODULE}.display_agentspec") as mock_agentspec,
        ):
            from client.app.content.config.config import main

            main()

        mock_st.tabs.assert_called_once()
        labels = mock_st.tabs.call_args.args[0]
        assert len(labels) == 7
        assert "Settings" in labels[0]
        assert "Users" in labels[1]
        assert "Databases" in labels[2]
        mock_settings.assert_called_once()
        for inactive in (mock_users, mock_db, mock_models, mock_oci, mock_mcp, mock_agentspec):
            inactive.assert_not_called()

    def test_only_active_users_tab_is_rendered(self, mock_st):
        mock_st.tabs.return_value = make_mock_tabs(7)
        state = AttrDict(
            {
                "auth_mode": "local_users",
                "config_active_tab": "👥 Users",
                "config_tabs": "👥 Users",
            }
        )

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.is_admin", return_value=True),
            patch(f"{MODULE}.display_settings") as settings,
            patch(f"{MODULE}.display_users") as users,
            patch(f"{MODULE}.display_databases") as databases,
            patch(f"{MODULE}.display_models"),
            patch(f"{MODULE}.display_oci"),
            patch(f"{MODULE}.display_mcp"),
            patch(f"{MODULE}.display_agentspec"),
        ):
            from client.app.content.config.config import main

            main()

        users.assert_called_once()
        settings.assert_not_called()
        databases.assert_not_called()

    @pytest.mark.parametrize(("admin", "mode"), [(False, "local_users"), (True, "oidc")])
    def test_users_tab_is_local_admin_only(self, mock_st, admin, mode):
        mock_st.tabs.return_value = make_mock_tabs(6)
        state = AttrDict({"auth_mode": mode})

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.is_admin", return_value=admin),
            patch(f"{MODULE}.display_settings"),
            patch(f"{MODULE}.display_users") as mock_users,
            patch(f"{MODULE}.display_databases"),
            patch(f"{MODULE}.display_models"),
            patch(f"{MODULE}.display_oci"),
            patch(f"{MODULE}.display_mcp"),
            patch(f"{MODULE}.display_agentspec"),
        ):
            from client.app.content.config.config import main

            main()

        assert all("Users" not in label for label in mock_st.tabs.call_args.args[0])
        mock_users.assert_not_called()
