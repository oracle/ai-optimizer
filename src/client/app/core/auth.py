"""Streamlit authentication and role-aware UI helpers."""

import contextlib

import httpx
import streamlit as st
from streamlit import session_state as state

from client.app.core.api import api_get, api_post
from client.app.core.local_session import browser_token, sync_browser_cookie

_TOKEN_KEY = "auth_token"
_PRINCIPAL_KEY = "auth_principal"
_REDACTED_PLACEHOLDER = "`••••••••`"
_LOCAL_COOKIE_ACTION_KEY = "_local_cookie_action"
_INVALID_LOCAL_COOKIE_KEY = "_invalid_local_cookie"


def is_admin() -> bool:
    """Return whether the current principal is an administrator."""
    principal = state.get(_PRINCIPAL_KEY) or {}
    return "admin" in principal.get("roles", [])


def _set_session(token: str, principal: dict) -> None:
    state[_TOKEN_KEY] = token
    state[_PRINCIPAL_KEY] = principal
    state[_LOCAL_COOKIE_ACTION_KEY] = "set"
    state.pop(_INVALID_LOCAL_COOKIE_KEY, None)


def _clear_session() -> None:
    state.pop(_TOKEN_KEY, None)
    state.pop(_PRINCIPAL_KEY, None)
    state.pop("settings", None)


def _validate_session() -> bool:
    if not state.get(_TOKEN_KEY):
        return False
    try:
        state[_PRINCIPAL_KEY] = api_get("auth/me")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:
            raise
        _clear_session()
        if state.get("auth_mode") == "local_users":
            state[_LOCAL_COOKIE_ACTION_KEY] = "clear"
            state[_INVALID_LOCAL_COOKIE_KEY] = True
        return False
    return True


def _restore_local_session() -> None:
    if state.get(_TOKEN_KEY) or state.get(_INVALID_LOCAL_COOKIE_KEY):
        return
    token = browser_token()
    if token:
        state[_TOKEN_KEY] = token


def _sync_local_cookie() -> None:
    action = state.get(_LOCAL_COOKIE_ACTION_KEY)
    if action not in {"set", "clear"}:
        return
    result = sync_browser_cookie(action, state.get(_TOKEN_KEY) if action == "set" else None)
    if result is True:
        state.pop(_LOCAL_COOKIE_ACTION_KEY, None)
        st.rerun()
    if result is False:
        state.pop(_LOCAL_COOKIE_ACTION_KEY, None)
        st.warning("The browser session could not be saved. Refreshing the page will require signing in again.")


def _local_sign_in() -> None:
    st.title("Sign in")
    st.caption("Authentication: Database")
    with st.form("database-sign-in"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        try:
            response = api_post("auth/login", json={"username": username, "password": password})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                st.error("Credentials are invalid or the account is unavailable.")
            else:
                st.error("Authentication is unavailable.")
        else:
            _set_session(response["access_token"], response["principal"])
            st.rerun()
            return
    st.stop()


def _oidc_sign_in() -> None:
    if getattr(st.user, "is_logged_in", False):
        access_token = st.user.tokens.get("access")
        if not access_token:
            st.error("The identity provider did not return an access token.")
            if st.button("Sign out"):
                st.logout()
            st.stop()
        state[_TOKEN_KEY] = access_token
        try:
            if _validate_session():
                return
        except httpx.HTTPError:
            st.error("Authentication is temporarily unavailable.")
            st.stop()
        st.error("The identity session is invalid or no longer active.")
        if st.button("Sign in again", type="primary"):
            st.logout()
        st.stop()

    st.title("Sign in")
    st.caption("Authentication: OIDC")
    if st.button("Continue with identity provider", type="primary"):
        st.login()
    st.stop()


def require_sign_in(auth_config: dict) -> None:
    """Establish and validate the server credential before protected calls."""
    if auth_config.get("mode") == "local_users":
        _restore_local_session()
    try:
        if _validate_session():
            if auth_config.get("mode") == "local_users":
                _sync_local_cookie()
            return
    except httpx.HTTPError:
        st.error("Authentication is temporarily unavailable.")
        st.stop()
    if auth_config.get("mode") == "oidc":
        _oidc_sign_in()
    _sync_local_cookie()
    _local_sign_in()


def sign_out() -> None:
    mode = state.get("auth_mode")
    if state.get(_TOKEN_KEY):
        with contextlib.suppress(httpx.HTTPError):
            api_post("auth/logout")
    _clear_session()
    if mode == "oidc" and getattr(st.user, "is_logged_in", False):
        st.logout()
    if mode == "local_users":
        state[_INVALID_LOCAL_COOKIE_KEY] = True
        state[_LOCAL_COOKIE_ACTION_KEY] = "clear"
        if sync_browser_cookie("clear") is not True:
            st.stop()
            return
        state.pop(_LOCAL_COOKIE_ACTION_KEY, None)


def redacted_password_input(
    label: str,
    *,
    value: str,
    key: str,
    disabled: bool = False,
    help: str | None = None,
) -> str | None:
    if is_admin():
        return st.text_input(label, value=value, type="password", key=key, disabled=disabled, help=help)
    st.markdown(f"**{label.rstrip(':')}:** {_REDACTED_PLACEHOLDER}")
    return None


def locked_notice() -> None:
    if not is_admin():
        st.caption("Administrator access is required for these controls.")
