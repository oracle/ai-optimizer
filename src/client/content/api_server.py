"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

This page is used when the API Server is hosted with the Client
"""
# spell-checker:ignore streamlit

import os
import asyncio
import inspect
import time

import streamlit as st
from streamlit import session_state as state

import client.utils.client as client
import client.utils.api_call as api_call
from client.utils.st_common import style
from client.utils.st_footer import remove_footer
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("client.content.api_server")

try:
    import launch_server

    REMOTE_SERVER = False
except ImportError:
    REMOTE_SERVER = True


#####################################################
# Functions
#####################################################
def copy_client_settings(new_client: str) -> None:
    """Copy User Setting to a new client (e.g. the Server)"""
    logger.info("Copying user settings to: %s", new_client)
    try:
        state[f"{new_client}_settings"] = api_call.patch(
            endpoint="v1/settings",
            payload={"json": state.client_settings},
            params={"client": new_client},
        )
    except api_call.ApiError as ex:
        st.error(f"Settings for {new_client} - Update Failed", icon="❌")
        logger.error("%s Settings Update failed: %s", new_client, ex)


def server_restart() -> None:
    """Restart the server process when button pressed"""
    logger.info("Restarting the API Server")
    os.environ["API_SERVER_KEY"] = state.user_server_key
    state.server["port"] = state.user_server_port
    state.server["key"] = os.getenv("API_SERVER_KEY")

    launch_server.stop_server(state.server["pid"])
    state.server["pid"] = launch_server.start_server(state.server["port"])
    time.sleep(10)
    state.pop("server_client", None)


#####################################################
# MAIN
#####################################################
async def main() -> None:
    """Streamlit GUI"""
    style()
    remove_footer()
    st.header("API Server")
    st.write("Access with your own client.")
    left, right = st.columns([0.2, 0.8])
    left.number_input(
        "API Server Port:",
        value=int(state.server["port"]),
        key="user_server_port",
        min_value=1,
        max_value=65535,
        disabled=REMOTE_SERVER,
    )
    right.text_input(
        "API Server Key:",
        value=state.server["key"],
        key="user_server_key",
        type="password",
        disabled=REMOTE_SERVER,
    )
    if not REMOTE_SERVER:
        st.button("Restart Server", type="primary", on_click=server_restart)

    st.header("Server Settings", divider="red")
    st.write("""
             The API Server maintains its own settings, independent of the Client.
             You can copy the Client settings to the API Server below.
             """)

    if "server_settings" not in state:
        copy_client_settings(new_client="server")

    st.json(state.server_settings, expanded=False)
    st.button(
        "Copy Client Settings",
        key="copy_client_settings",
        type="primary",
        on_click=copy_client_settings,
        kwargs={"new_client": "server"},
        help="Copy your settings, from the ChatBot, by clicking here.",
    )
    st.header("Server Activity", divider="red")
    if "server_client" not in state:
        state.server_client = client.Client(
            server=state.server,
            settings=state.server_settings,
            timeout=10,
        )
    server_client: client.Client = state.server_client

    auto_refresh = st.toggle("Auto Refresh (every 10sec)", value=False, key="selected_auto_refresh")
    st.button("Manual Refresh", disabled=auto_refresh)
    with st.container():
        history = await server_client.get_history()
        if history is None or len(history) == 1:
            st.write("No Server Activity")
            history = []
        for message in history:
            if message["role"] in ("ai", "assistant"):
                st.chat_message("ai").json(message, expanded=False)
            elif message["role"] in ("human", "user"):
                st.chat_message("human").json(message, expanded=False)
        if auto_refresh:
            time.sleep(10)  # Refresh every 10 seconds
            st.rerun()


if __name__ == "__main__" or "page.py" in inspect.stack()[1].filename:
    asyncio.run(main())
