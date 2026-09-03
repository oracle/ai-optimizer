"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore streamlit

import logging
from pathlib import Path
from uuid import uuid4

import streamlit as st
from streamlit import session_state as state

from _version import __version__
from client.app.core.api import _server_module_available, api_get, get_server_settings, start_server
from logging_config import configure_logging

configure_logging()

LOGGER = logging.getLogger(__name__)
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

if "optimizer_client" not in state:
    state.optimizer_client = str(uuid4())


def _about_details(session_id: str, email: str | None = None) -> str:
    """Build About text without exposing the opaque session as a client identity."""
    details = [f"Session: {session_id}"]
    if email:
        details.insert(0, f"Signed in as: {email}")
    return "\n\n".join(details)


def _signed_in_email() -> str | None:
    """Return the optional email claim supplied by Streamlit's OIDC integration."""
    try:
        if not st.user.is_logged_in:
            return None
        email = st.user.get("email")
    except (AttributeError, KeyError):
        return None
    return email if isinstance(email, str) and email else None


st.set_page_config(
    page_title="Oracle AI Optimizer and Toolkit",
    page_icon=str(ASSETS_DIR / "favicon.png"),
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": "https://oracle.github.io/ai-optimizer/",
        "Report a bug": "https://github.com/oracle/ai-optimizer/issues/new?template=2-bug_report.yml",
        "About": f"Version: v{__version__}\n\n{_about_details(state.optimizer_client, _signed_in_email())}",
    },
)
st.html(
    """
    <style>
        .stSidebar img[alt="Logo"] {
            height: auto;
            width: 100%;
        }
        [data-testid="stSidebarLogo"] {
            padding-top: 3rem;
        }
        [data-testid="stSidebarNav"] {
            margin-top: 3.5rem;
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
st.logo(str(ASSETS_DIR / "logo.png"))

# Native Streamlit OIDC is opt-in through the deployment's ``[auth]``
# secrets configuration. API calls use the provider-issued access token;
# the ID token remains a Streamlit client credential.
try:
    oidc_configured = "auth" in st.secrets
except FileNotFoundError:
    oidc_configured = False
if oidc_configured and not st.user.is_logged_in:
    if _server_module_available():
        st.sidebar.space(size="small")
        with st.sidebar.spinner("Starting server...", show_time=True):
            start_server()

    st.login()
    st.stop()

if state.get("settings") is None:
    st.sidebar.space(size="small")
    with st.sidebar.spinner("Connecting to server...", show_time=True):
        state.settings = get_server_settings(client=state.optimizer_client)
    if state.settings is None and _server_module_available():
        with st.sidebar.spinner("Starting server...", show_time=True):
            start_server()
            state.settings = get_server_settings(client=state.optimizer_client)

if state.settings is None:
    st.error("Unable to connect to the server. Please check that the server is running.")
    st.stop()

if "optimizer_help" not in state:
    state.optimizer_help = {item["key"]: item["text"] for item in api_get("help")}

# Left Hand Side - Navigation
sidebar_navigation = {"": []}
sidebar_navigation[""].extend(
    [
        st.Page("content/chatbot.py", title="ChatBot", icon="💬", default=True),
        st.Page("content/testbed.py", title="Testbed", icon="🧪"),
        st.Page("content/api_server.py", title="API Server", icon="📡"),
        st.Page("content/tools/tools.py", title="Tools", icon="🧰"),
        st.Page("content/config/config.py", title="Configuration", icon="⚙️"),
    ]
)

if oidc_configured and st.user.is_logged_in:

    def sign_out():
        """End the current Streamlit OIDC session."""
        st.logout()

    sidebar_navigation[""].append(st.Page(sign_out, title="Sign out", icon="🔓"))

pg_sidebar = st.navigation(sidebar_navigation, position="sidebar", expanded=False)
pg_sidebar.run()
