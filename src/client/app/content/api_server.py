"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This page is used when the API Server is hosted with the Client
"""
# spell-checker:ignore streamlit

import logging

import streamlit as st
from streamlit import session_state as state

from client.app.core.api import _base_url, api_post, get_server_settings
from client.app.core.auth import is_authenticated, locked_notice, redacted_password_input
from client.app.core.helpers import load_chat_history
from client.app.core.secrets import reveal
from client.app.core.settings import settings as client_settings

LOGGER = logging.getLogger("client.content.api_server")


def _copy_to_server() -> None:
    """Copy the current client's settings to the server client."""
    try:
        api_post(f"settings/server/copy?client={state.optimizer_client}")
    except Exception:
        LOGGER.exception("Failed to copy client settings to server")
        st.error("Failed to copy settings to server.")


#####################################################
# MAIN
#####################################################
authenticated = is_authenticated()

st.header("API Server")
st.write("Access the AI Optimizer and Toolkit with your own client.")
st.text_input(
    "API Server:",
    value=_base_url(),
    disabled=True,
)
redacted_password_input(
    "API Server Key:",
    value=reveal(client_settings.api_key) or "",
    key="api_server_key",
    disabled=True,
)

locked_notice()

st.header("Server Settings", divider="red")
st.write("""
         The API Server maintains its own settings, independent of your isolated client.
         You can experiment with settings, then persist them for external clients to use.
        """)

if authenticated:
    server_settings = get_server_settings(client="server", include_sensitive=False)
    if server_settings:
        st.subheader("Current 'server' settings:")
        st.json(server_settings.get("client_settings", {}), expanded=False)
    else:
        st.warning("Unable to fetch server settings.")

    st.button(
        "Copy Client Settings",
        key="copy_client_settings",
        type="primary",
        on_click=_copy_to_server,
        help="Copy your settings, from the ChatBot, by clicking here.",
    )
    st.write("After 'Copy Client Settings', point the external application to the 'server' client.")

    st.header("Server Activity", divider="red")
    auto_refresh = st.toggle("Auto Refresh (every 10sec)", value=False, key="selected_auto_refresh")
    st.button("Manual Refresh", disabled=auto_refresh)

    @st.fragment(run_every=10 if auto_refresh else None)
    def _server_activity():
        history = load_chat_history("server")
        if not history:
            st.write("No Server Activity")
        for message in history:
            if message["role"] in ("ai", "assistant"):
                st.chat_message("ai").json(message, expanded=False)
            elif message["role"] in ("human", "user"):
                st.chat_message("human").json(message, expanded=False)

    _server_activity()
