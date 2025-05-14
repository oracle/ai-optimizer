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

import client.utils.st_common as st_common
import client.utils.client as client
import client.utils.api_call as api_call
import common.logging_config as logging_config
from common.schema import ClientIdType

logger = logging_config.logging.getLogger("client.content.api_server")

try:
    import launch_server

    REMOTE_SERVER = False
except ImportError:
    REMOTE_SERVER = True


#####################################################
# Functions
#####################################################
def copy_user_settings(new_client: ClientIdType) -> None:
    """Copy User Setting to a new client (e.g. the Server)"""
    logger.info("Copying user settings to: %s", new_client)
    try:
        _ = api_call.patch(
            endpoint="v1/settings",
            payload={"json": state.user_settings},
            params={"client": new_client},
        )
        st_common.clear_state_key(f"{new_client}_settings")
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
    state.pop("sever_client", None)


#####################################################
# MAIN
#####################################################
async def main() -> None:
    """Streamlit GUI"""
    st_common.set_server_state()
    st.header("API Server")
    st.write("Access with your own client.")
    left, right = st.columns([0.2, 0.8])
    left.number_input(
        "API Server Port:",
        value=state.server["port"],
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
    st.json(state.server_settings, expanded=False)
    st.button(
        "Copy Client Settings",
        type="primary",
        on_click=copy_user_settings,
        kwargs={"new_client": "server"},
        help="Copy your settings, from the ChatBot, by clicking here.",
    )

    st.header("Server Activity", divider="red")
    if "server_client" not in state:
        state.server_client = client.Client(
            server=state.server,
            settings=state["server_settings"],
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

