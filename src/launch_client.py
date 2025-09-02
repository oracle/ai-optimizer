"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Session States Set:
- client_settings: Stores all user settings
"""
# spell-checker:ignore streamlit, scriptrunner

import os
from uuid import uuid4

import streamlit as st
from streamlit import session_state as state

from client.utils import api_call
from common.schema import ClientIdType
from common._version import __version__

from common import logging_config

logger = logging_config.logging.getLogger("launch_client")

# Import launch_server if it exists
LAUNCH_SERVER_EXISTS = True
try:
    from launch_server import start_server, get_api_key

    _ = get_api_key()
    logger.debug("Imported API Server.")
except ImportError as ex:
    logger.debug("API Server not present: %s", ex)
    LAUNCH_SERVER_EXISTS = False


#############################################################################
# Functions
#############################################################################
def init_server_state() -> None:
    """initialize Streamlit State server"""
    if "server" not in state:
        logger.info("Initializing state.server")
        state.server = {"url": os.getenv("API_SERVER_URL", "http://localhost")}
        state.server["port"] = int(os.getenv("API_SERVER_PORT", "8000"))
        state.server["key"] = os.getenv("API_SERVER_KEY")
        state.server["remote"] = True
        logger.debug("Server State: %s", state.server)


def init_configs_state(client: ClientIdType) -> None:
    """initialize all Streamlit State *_configs"""
    full_config = api_call.get(
        endpoint="v1/settings",
        params={"client": client, "full_config": True, "incl_sensitive": True, "incl_readonly": True},
        retries=10,
        backoff_factor=1.5,
    )
    for key, value in full_config.items():
        logger.info("Initializing state.%s", key)
        state[key] = value


#############################################################################
# MAIN
#############################################################################
def main() -> None:
    """Streamlit GUI"""
    st.set_page_config(
        page_title="Oracle AI Optimizer and Toolkit",
        page_icon="client/media/favicon.png",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "Get Help": "https://oracle.github.io/ai-optimizer/",
            "Report a bug": "https://github.com/oracle/ai-optimizer/issues/new",
            "About": f"v{__version__}",
        },
    )
    st.html(
        """
        <style>
        img[alt="Logo"] {
            height: auto;
            margin-top: 1.25em;
            width: auto;
        }
        .stSidebar img[alt="Logo"] {
            width: 100%;
        }
        .stAppHeader img[alt="Logo"] {
            width: 50%;
        }
        </style>
        """,
    )
    st.logo("client/media/logo.png")

    # Setup Settings State
    api_down = False
    if "client_settings" not in state:
        try:
            client_id = str(uuid4())
            _ = api_call.post(endpoint="v1/settings", params={"client": client_id})
            init_configs_state(client_id)
        except api_call.ApiError:
            logger.error("Unable to contact API Server; setting as Down!")
            api_down = True
    if not api_down and "server_settings" not in state:
        try:
            logger.info("Initializing state.server_settings")
            state.server_settings = api_call.get(endpoint="v1/settings", params={"client": "server"})
        except api_call.ApiError:
            logger.error("Unable to contact API Server; setting as Down!")
            api_down = True
    if api_down and "client_settings" not in state:
        st.error(
            "Unable to contact the API Server.  Please check that it is running and refresh your browser.",
            icon="🛑",
        )
        st.stop()

    # Enable/Disable Functionality
    state.disabled = {}
    state.disabled["tests"] = os.environ.get("DISABLE_TESTBED", "false").lower() == "true"
    state.disabled["api"] = os.environ.get("DISABLE_API", "false").lower() == "true"
    state.disabled["tools"] = os.environ.get("DISABLE_TOOLS", "false").lower() == "true"

    state.disabled["db_cfg"] = os.environ.get("DISABLE_DB_CFG", "false").lower() == "true"
    state.disabled["model_cfg"] = os.environ.get("DISABLE_MODEL_CFG", "false").lower() == "true"
    state.disabled["oci_cfg"] = os.environ.get("DISABLE_OCI_CFG", "false").lower() == "true"
    state.disabled["settings"] = os.environ.get("DISABLE_SETTINGS", "false").lower() == "true"

    # Left Hand Side - Navigation
    chatbot = st.Page("client/content/chatbot.py", title="ChatBot", icon="💬", default=True)
    sidebar_navigation = {
        "": [chatbot],
    }
    if not state.disabled["tests"]:
        testbed = st.Page("client/content/testbed.py", title="Testbed", icon="🧪")
        sidebar_navigation[""].append(testbed)
    if not state.disabled["api"]:
        api_server = st.Page("client/content/api_server.py", title="API Server", icon="📡")
        sidebar_navigation[""].append(api_server)
    if not state.disabled["tools"]:
        tools = st.Page("client/content/tools/tools.py", title="Tools", icon="🧰")
        sidebar_navigation[""].append(tools)
        config = st.Page("client/content/config/config.py", title="Configuration", icon="⚙️")
        sidebar_navigation[""].append(config)

    pg_sidebar = st.navigation(sidebar_navigation, position="sidebar", expanded=False)
    pg_sidebar.run()


if __name__ == "__main__":
    # Start Server if not running
    init_server_state()
    if LAUNCH_SERVER_EXISTS:
        try:
            logger.debug("Server PID: %i", state.server["pid"])
        except KeyError:
            server_state, pid = start_server(logfile=True)
            state.server["pid"] = pid
            state.server["remote"] = server_state != "started"
    main()
