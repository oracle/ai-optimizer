"""Authentication member administration UI tests."""

from unittest.mock import patch

import pytest

from client.tests.conftest import make_http_error

MODULE = "client.app.content.config.tabs.users"

pytestmark = pytest.mark.unit


def test_create_member_sends_database_identity_and_profile(mock_st):
    with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.api_post") as post:
        from client.app.content.config.tabs.users import _create_member

        assert _create_member(" APP_MEMBER ", "secret", " Member ", " member@example.com ")

    post.assert_called_once_with(
        "users",
        json={
            "username": "APP_MEMBER",
            "password": "secret",
            "display_name": "Member",
            "email": "member@example.com",
        },
        toast="Member **APP_MEMBER** created.",
    )


def test_update_member_sends_profile_and_lock_state(mock_st):
    with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.api_patch") as api_patch:
        from client.app.content.config.tabs.users import _update_member

        assert _update_member("member-id", "Member", "", True)

    api_patch.assert_called_once_with(
        "users/member-id",
        json={"display_name": "Member", "email": None, "account_locked": True},
        toast="Member updated.",
    )


def test_reset_password_uses_member_endpoint(mock_st):
    with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.api_post") as post:
        from client.app.content.config.tabs.users import _reset_password

        assert _reset_password("member-id", "replacement")

    post.assert_called_once_with(
        "users/member-id/password-reset",
        json={"password": "replacement"},
        toast="Database password reset.",
    )


def test_unavailable_member_administration_is_explained(mock_st):
    error = make_http_error(404, "Local user management is unavailable")
    with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.api_get", side_effect=error):
        from client.app.content.config.tabs.users import display_users

        display_users()

    mock_st.info.assert_called_once_with("Local user management is unavailable")


def test_create_member_requires_matching_passwords(mock_st):
    mock_st.text_input.side_effect = ["APP_MEMBER", "Member", "", "first", "second"]
    mock_st.form_submit_button.return_value = True
    with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}._create_member") as create:
        from client.app.content.config.tabs.users import _render_create_member

        _render_create_member()

    create.assert_not_called()
    mock_st.error.assert_called_once_with("Passwords do not match.")


def test_admin_row_has_no_member_actions(mock_st):
    user = {
        "role": "admin",
        "display_name": "Admin",
        "database_username": "APP_ADMIN",
        "account_status": "OPEN",
    }
    with (
        patch(f"{MODULE}.st", mock_st),
        patch(f"{MODULE}.api_get", return_value=[user]),
        patch(f"{MODULE}._render_admin") as render_admin,
        patch(f"{MODULE}._render_member") as render_member,
        patch(f"{MODULE}._render_create_member"),
    ):
        from client.app.content.config.tabs.users import display_users

        display_users()

    render_admin.assert_called_once_with(user)
    render_member.assert_not_called()
