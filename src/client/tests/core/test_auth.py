"""Tests for server-backed Streamlit authentication."""

from unittest.mock import patch

import httpx
import pytest

from client.tests.conftest import AttrDict

MODULE = "client.app.core.auth"
pytestmark = pytest.mark.unit


def test_admin_role_enables_administrator_controls():
    from client.app.core import auth

    state = AttrDict({"auth_principal": {"roles": ["admin"]}})
    with patch(f"{MODULE}.state", state):
        assert auth.is_admin() is True


def test_member_role_disables_administrator_controls():
    from client.app.core import auth

    state = AttrDict({"auth_principal": {"roles": ["member"]}})
    with patch(f"{MODULE}.state", state):
        assert auth.is_admin() is False


def test_valid_session_refreshes_server_principal():
    from client.app.core import auth

    state = AttrDict({"auth_token": "token"})
    principal = {"roles": ["member"], "username": "Member"}
    with patch(f"{MODULE}.state", state), patch(f"{MODULE}.api_get", return_value=principal):
        assert auth._validate_session() is True
    assert state["auth_principal"] == principal


def test_invalid_session_is_cleared():
    from client.app.core import auth

    request = httpx.Request("GET", "https://example.test/v1/auth/me")
    response = httpx.Response(401, request=request)
    state = AttrDict({"auth_token": "token", "auth_principal": {"roles": ["admin"]}, "settings": {}})
    with (
        patch(f"{MODULE}.state", state),
        patch(
            f"{MODULE}.api_get", side_effect=httpx.HTTPStatusError("unauthorized", request=request, response=response)
        ),
    ):
        assert auth._validate_session() is False
    assert "auth_token" not in state
    assert "auth_principal" not in state
    assert "settings" not in state


def test_invalid_local_session_clears_browser_cookie():
    from client.app.core import auth

    request = httpx.Request("GET", "https://example.test/v1/auth/me")
    response = httpx.Response(401, request=request)
    state = AttrDict({"auth_mode": "local_users", "auth_token": "token"})
    with (
        patch(f"{MODULE}.state", state),
        patch(
            f"{MODULE}.api_get", side_effect=httpx.HTTPStatusError("unauthorized", request=request, response=response)
        ),
    ):
        assert auth._validate_session() is False
    assert state["_local_cookie_action"] == "clear"


def test_authority_outage_preserves_session():
    from client.app.core import auth

    request = httpx.Request("GET", "https://example.test/v1/auth/me")
    response = httpx.Response(503, request=request)
    state = AttrDict({"auth_token": "token", "auth_principal": {"roles": ["admin"]}})
    with (
        patch(f"{MODULE}.state", state),
        patch(
            f"{MODULE}.api_get", side_effect=httpx.HTTPStatusError("unavailable", request=request, response=response)
        ),
        pytest.raises(httpx.HTTPStatusError),
    ):
        auth._validate_session()
    assert state["auth_token"] == "token"
    assert state["auth_principal"]["roles"] == ["admin"]


def test_local_login_stores_token_and_principal(mock_st):
    from client.app.core import auth

    state = AttrDict({})
    mock_st.form.return_value.__enter__.return_value = mock_st
    mock_st.form_submit_button.return_value = True
    mock_st.text_input.side_effect = ["APP_USER", "secret"]
    response = {"access_token": "opaque", "principal": {"roles": ["member"]}}
    with (
        patch(f"{MODULE}.state", state),
        patch(f"{MODULE}.st", mock_st),
        patch(f"{MODULE}.api_post", return_value=response),
    ):
        auth._local_sign_in()
    assert state["auth_token"] == "opaque"
    assert state["auth_principal"] == response["principal"]
    assert state["_local_cookie_action"] == "set"
    assert [call.args[0] for call in mock_st.text_input.call_args_list] == ["Username", "Password"]
    mock_st.caption.assert_called_once_with("Authentication: Database")
    mock_st.rerun.assert_called_once()


def test_local_session_is_restored_from_browser_cookie():
    from client.app.core import auth

    state = AttrDict({})
    with patch(f"{MODULE}.state", state), patch(f"{MODULE}.browser_token", return_value="opaque"):
        auth._restore_local_session()
    assert state["auth_token"] == "opaque"


def test_local_session_cookie_is_persisted_after_login(mock_st):
    from client.app.core import auth

    state = AttrDict({"auth_token": "opaque", "_local_cookie_action": "set"})
    with (
        patch(f"{MODULE}.state", state),
        patch(f"{MODULE}.st", mock_st),
        patch(f"{MODULE}.sync_browser_cookie", return_value=True) as sync_cookie,
    ):
        auth._sync_local_cookie()
    sync_cookie.assert_called_once_with("set", "opaque")
    assert "_local_cookie_action" not in state
    mock_st.rerun.assert_called_once()


def test_local_sign_out_revokes_server_session_and_clears_cookie(mock_st):
    from client.app.core import auth

    state = AttrDict({"auth_mode": "local_users", "auth_token": "opaque"})
    with (
        patch(f"{MODULE}.state", state),
        patch(f"{MODULE}.st", mock_st),
        patch(f"{MODULE}.api_post") as api_post,
        patch(f"{MODULE}.sync_browser_cookie", return_value=True) as sync_cookie,
    ):
        auth.sign_out()
    api_post.assert_called_once_with("auth/logout")
    sync_cookie.assert_called_once_with("clear")
    assert "auth_token" not in state
    assert "_local_cookie_action" not in state


def test_oidc_sign_in_identifies_authentication_authority(mock_st):
    from client.app.core import auth

    state = AttrDict({})
    mock_st.user.is_logged_in = False
    mock_st.button.return_value = False
    with patch(f"{MODULE}.state", state), patch(f"{MODULE}.st", mock_st):
        auth._oidc_sign_in()
    mock_st.caption.assert_called_once_with("Authentication: OIDC")


def test_oidc_login_forwards_exposed_access_token(mock_st):
    from client.app.core import auth

    state = AttrDict({})
    mock_st.user.is_logged_in = True
    mock_st.user.tokens = {"access": "jwt-access-token"}
    with (
        patch(f"{MODULE}.state", state),
        patch(f"{MODULE}.st", mock_st),
        patch(f"{MODULE}._validate_session", return_value=True),
    ):
        auth._oidc_sign_in()
    assert state["auth_token"] == "jwt-access-token"


def test_member_secret_field_is_redacted(mock_st):
    from client.app.core import auth

    with patch(f"{MODULE}.st", mock_st), patch(f"{MODULE}.is_admin", return_value=False):
        result = auth.redacted_password_input("API Key:", value="secret", key="api-key")
    assert result is None
    assert "secret" not in mock_st.markdown.call_args.args[0]
