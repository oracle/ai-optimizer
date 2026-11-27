"""Local authentication member administration."""

import httpx
import streamlit as st

from client.app.core import helpers
from client.app.core.api import api_get, api_patch, api_post


def _show_error(exc: httpx.HTTPStatusError, context: str) -> None:
    st.error(helpers.format_error(exc, context=context), icon="🚨")


def _create_member(username: str, password: str, display_name: str, email: str) -> bool:
    try:
        api_post(
            "users",
            json={
                "username": username.strip(),
                "password": password,
                "display_name": display_name.strip() or None,
                "email": email.strip() or None,
            },
            toast=f"Member **{username.strip()}** created.",
        )
    except httpx.HTTPStatusError as exc:
        _show_error(exc, "Create failed")
        return False
    return True


def _update_member(user_id: str, display_name: str, email: str, account_locked: bool) -> bool:
    try:
        api_patch(
            f"users/{user_id}",
            json={
                "display_name": display_name.strip() or None,
                "email": email.strip() or None,
                "account_locked": account_locked,
            },
            toast="Member updated.",
        )
    except httpx.HTTPStatusError as exc:
        _show_error(exc, "Update failed")
        return False
    return True


def _reset_password(user_id: str, password: str) -> bool:
    try:
        api_post(
            f"users/{user_id}/password-reset",
            json={"password": password},
            toast="Database password reset.",
        )
    except httpx.HTTPStatusError as exc:
        _show_error(exc, "Password reset failed")
        return False
    return True


def _render_create_member() -> None:
    with st.expander("Create member"):
        with st.form("create-auth-member", clear_on_submit=True):
            username = st.text_input("Database username", key="auth_member_username")
            display_name = st.text_input("Display name", key="auth_member_display_name")
            email = st.text_input("Email", key="auth_member_email")
            password = st.text_input("Password", type="password", key="auth_member_password")
            confirmation = st.text_input(
                "Confirm password",
                type="password",
                key="auth_member_password_confirmation",
            )
            submitted = st.form_submit_button("Create", type="primary")
        if submitted:
            if not username.strip() or not password:
                st.error("Database username and password are required.")
            elif password != confirmation:
                st.error("Passwords do not match.")
            elif _create_member(username, password, display_name, email):
                st.rerun()


def _render_admin(user: dict) -> None:
    label = user.get("display_name") or user.get("username") or "Admin"
    with st.container(border=True):
        st.subheader(label)
        st.caption("Reserved Admin")
        st.write(f"Database username: `{user.get('database_username', '')}`")
        st.write(f"Account status: `{user.get('account_status', '')}`")


def _render_member(user: dict) -> None:
    user_id = str(user["user_id"])
    label = user.get("display_name") or user.get("username") or user.get("database_username")
    account_status = str(user.get("account_status") or "")
    with st.expander(f"{label} · {user.get('database_username', '')} · {account_status}"):
        with st.form(f"edit-auth-member-{user_id}"):
            display_name = st.text_input(
                "Display name",
                value=user.get("display_name") or "",
                key=f"auth_member_display_name_{user_id}",
            )
            email = st.text_input(
                "Email",
                value=user.get("email") or "",
                key=f"auth_member_email_{user_id}",
            )
            account_locked = st.checkbox(
                "Account locked",
                value="LOCKED" in account_status.upper(),
                key=f"auth_member_locked_{user_id}",
            )
            save = st.form_submit_button("Save")
        if save and _update_member(user_id, display_name, email, account_locked):
            st.rerun()

        st.markdown("**Reset password**")
        with st.form(f"reset-auth-member-password-{user_id}", clear_on_submit=True):
            password = st.text_input("New password", type="password", key=f"auth_member_password_{user_id}")
            confirmation = st.text_input(
                "Confirm new password",
                type="password",
                key=f"auth_member_password_confirmation_{user_id}",
            )
            reset = st.form_submit_button("Reset password")
        if reset:
            if not password:
                st.error("A new password is required.")
            elif password != confirmation:
                st.error("Passwords do not match.")
            elif _reset_password(user_id, password):
                st.rerun()


def display_users() -> None:
    """Render local member administration for the reserved Admin."""
    st.header("Users", divider="red")
    st.write("Create and manage database-authenticated AI Optimizer members.")
    try:
        users = api_get("users")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            st.info(str(helpers.extract_error_detail(exc)))
        else:
            _show_error(exc, "Unable to load users")
        return

    _render_create_member()
    st.subheader("Existing users")
    if not users:
        st.info("No users defined.")
        return
    for user in users:
        if user.get("role") == "admin":
            _render_admin(user)
        else:
            _render_member(user)
