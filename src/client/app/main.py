"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore streamlit

import logging

import streamlit as st
from streamlit import session_state as state

from _version import __version__
from client.app.core.api import get_server_settings, start_server
from logging_config import configure_logging

configure_logging()

LOGGER = logging.getLogger(__name__)

st.set_page_config(
    page_title="Oracle AI Optimizer and Toolkit",
    page_icon="../assets/favicon.png",
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
        margin-top: 2.25rem;
        width: auto;
    }
    .stSidebar img[alt="Logo"] {
        width: 100%;
    }
    .stAppHeader img[alt="Logo"] {
        width: 50%;
    }
    /* Fix emoji rendering in tab labels */
    [data-testid="stMarkdownContainer"] p {
        font-family: "sans-serif-pro" !important;
    }
    </style>
    """,
)
st.logo("../assets/logo.png")

if "settings" not in state:
    with st.spinner("Connecting to server..."):
        state.settings = get_server_settings()
    if state.settings is None:
        with st.spinner("Starting server..."):
            start_server()
            state.settings = get_server_settings(max_retries=3, backoff_delays=[2, 4, 8])

if state.settings is None:
    st.error("Unable to connect to the server. Please check that the server is running.")
    st.stop()

# Left Hand Side - Navigation
chatbot = st.Page("content/chatbot.py", title="ChatBot", icon="💬", default=True)
sidebar_navigation = {
    "": [chatbot],
}
if not state.settings["client_disable_testbed"]:
    testbed = st.Page("content/testbed.py", title="Testbed", icon="🧪")
    sidebar_navigation[""].append(testbed)
if not state.settings["client_disable_api"]:
    api_server = st.Page("content/api_server.py", title="API Server", icon="📡")
    sidebar_navigation[""].append(api_server)
if not state.settings["client_disable_tools"]:
    tools = st.Page("content/tools/tools.py", title="Tools", icon="🧰")
    sidebar_navigation[""].append(tools)
    config = st.Page("content/config/config.py", title="Configuration", icon="⚙️")
    sidebar_navigation[""].append(config)

pg_sidebar = st.navigation(sidebar_navigation, position="sidebar", expanded=False)
pg_sidebar.run()
