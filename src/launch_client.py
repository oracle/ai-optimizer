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

from client.utils import st_common, api_call
from client.utils.st_common import set_server_state

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("launch_client")

# Import launch_server if it exists
REMOTE_SERVER = False
try:
    from launch_server import start_server, get_api_key

    _ = get_api_key()
    logger.debug("Imported API Server.")
except ImportError as ex:
    logger.debug("API Server not present: %s", ex)
    REMOTE_SERVER = True


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
            "Get Help": "https://oracle-samples.github.io/ai-optimizer/",
            "Report a bug": "https://github.com/oracle-samples/ai-optimizer/issues/new",
        },
    )
    st.html(
        """
        <style>
        img[data-testid="stLogo"] {
            width: 100%;
            height: auto;
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
            st_common.populate_state(client=client_id, force=True)
        except api_call.ApiError:
            logger.error("Unable to contact API Server; setting as Down!")
            api_down = True
    if not api_down and "server_settings" not in state:
        try:
            logger.info("Update state for: server_settings")
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
    navigation = {
        "": [chatbot],
    }
    if not state.disabled["tests"]:
        testbed = st.Page("client/content/testbed.py", title="Testbed", icon="🧪")
        navigation[""].append(testbed)
    if not state.disabled["api"]:
        api_server = st.Page("client/content/api_server.py", title="API Server", icon="📡")
        navigation[""].append(api_server)

    # Tools
    if not state.disabled["tools"]:
        split_embed = st.Page("client/content/tools/split_embed.py", title="Split/Embed", icon="📚")
        navigation["Tools"] = [split_embed]
        prompt_eng = st.Page("client/content/tools/prompt_eng.py", title="Prompts", icon="🎤")
        navigation["Tools"].append(prompt_eng)

    # Administration
    if not state.disabled["tools"]:
        navigation["Configuration"] = []
        if not state.disabled["db_cfg"]:
            db_config = st.Page("client/content/config/databases.py", title="Databases", icon="🗄️")
            navigation["Configuration"].append(db_config)
        if not state.disabled["model_cfg"]:
            model_config = st.Page("client/content/config/models.py", title="Models", icon="🤖")
            navigation["Configuration"].append(model_config)
        if not state.disabled["oci_cfg"]:
            oci_config = st.Page("client/content/config/oci.py", title="OCI", icon="☁️")
            navigation["Configuration"].append(oci_config)
        if not state.disabled["settings"]:
            settings = st.Page("client/content/config/settings.py", title="Settings", icon="💾")
            navigation["Configuration"].append(settings)
        # When we get here, if there's nothing in "Configuration" delete it
        if not navigation["Configuration"]:
            del navigation["Configuration"]

    pg = st.navigation(navigation, position="sidebar", expanded=False)
    pg.run()


if __name__ == "__main__":
    set_server_state()
    # Start Server if not running
    if not REMOTE_SERVER:
        try:
            logger.debug("Server PID: %i", state.server["pid"])
        except KeyError:
            state.server["pid"] = start_server(logfile=True)
    main()
