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
from client.app.content.local_database_setup import display_local_database_setup
from client.app.core.api import _server_module_available, api_get, get_server_settings, start_server, stop_server
from client.app.core.auth import auth_sidebar, gate_active, is_authenticated
from client.app.core.local_bootstrap import (
    IncompleteLocalCoreEnvironment,
    LocalCoreConfigurationError,
    LocalCoreSource,
    local_core_config_path,
    persist_local_core,
    resolve_local_core,
)
from logging_config import configure_logging

configure_logging()

LOGGER = logging.getLogger(__name__)
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

if "optimizer_client" not in state:
    state.optimizer_client = str(uuid4())

st.set_page_config(
    page_title="Oracle AI Optimizer and Toolkit",
    page_icon=str(ASSETS_DIR / "favicon.png"),
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": "https://oracle.github.io/ai-optimizer/",
        "Report a bug": "https://github.com/oracle/ai-optimizer/issues/new?template=2-bug_report.yml",
        "About": f"Version: v{__version__}\n\nClient: {state.optimizer_client}",
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


def _clear_local_core_secrets() -> None:
    if state.pop("_clear_local_core_secrets", False):
        state.pop("local_core_password", None)
        state.pop("local_core_wallet_password", None)


def _retry_or_edit_local_core(source: LocalCoreSource) -> None:
    st.error("The local server could not start with the configured CORE database. Check the server log and retry.")
    retry_column, edit_column = st.columns(2)
    if retry_column.button("Retry", type="primary"):
        state.pop("_local_core_startup_failed", None)
        st.rerun()
    if source in (LocalCoreSource.MEMORY, LocalCoreSource.SAVED) and edit_column.button("Edit CORE configuration"):
        stop_server()
        state["_local_core_edit"] = True
        state.pop("_local_core_startup_failed", None)
        st.rerun()
    st.stop()


def _start_local_server() -> None:
    try:
        resolved = resolve_local_core(in_memory=state.get("_local_core_config"))
        load_error = None
    except IncompleteLocalCoreEnvironment as exc:
        st.error(str(exc))
        st.info("Complete or remove the CORE database environment variables, then restart the client.")
        st.stop()
    except LocalCoreConfigurationError as exc:
        resolved = None
        load_error = str(exc)

    edit_requested = state.get("_local_core_edit", False)
    if resolved is not None and resolved.config is not None and not edit_requested:
        if state.get("_local_core_startup_failed"):
            _retry_or_edit_local_core(resolved.source)
        with st.spinner("Starting server...", show_time=True):
            started = start_server(resolved.config.child_environment())
        if started:
            state.settings = get_server_settings(client=state.optimizer_client)
            if state.settings is not None:
                return
        state["_local_core_startup_failed"] = True
        _retry_or_edit_local_core(resolved.source)

    current = resolved.config if resolved is not None else None
    candidate = display_local_database_setup(
        current=current,
        error=load_error or state.pop("_local_core_setup_error", None),
    )
    if candidate is None:
        st.stop()

    with st.spinner("Connecting to CORE and starting server...", show_time=True):
        started = start_server(candidate.child_environment())
    state["_clear_local_core_secrets"] = True
    if not started:
        stop_server()
        state["_local_core_edit"] = True
        state["_local_core_setup_error"] = (
            "CORE connection or initialization failed. Check the server log and try again."
        )
        st.rerun()

    state["_local_core_config"] = candidate
    config_path = local_core_config_path()
    if config_path is not None:
        try:
            persist_local_core(candidate, config_path)
        except OSError:
            stop_server()
            state["_local_core_edit"] = True
            state["_local_core_setup_error"] = "CORE connected, but its container configuration could not be saved."
            st.rerun()
    state.pop("_local_core_edit", None)
    state.pop("_local_core_startup_failed", None)
    st.rerun()


_clear_local_core_secrets()

if state.get("settings") is None:
    st.sidebar.space(size="small")
    with st.sidebar.spinner("Connecting to server...", show_time=True):
        state.settings = get_server_settings(client=state.optimizer_client)
    if state.settings is None and _server_module_available():
        _start_local_server()

if state.settings is None:
    st.error("Unable to connect to the server. Please check that the server is running.")
    st.stop()

if "optimizer_help" not in state:
    state.optimizer_help = {item["key"]: item["text"] for item in api_get("help")}

# Left Hand Side - Navigation
chatbot = st.Page("content/chatbot.py", title="ChatBot", icon="💬", default=True)
sidebar_navigation = {
    "": [chatbot],
}
testbed = st.Page("content/testbed.py", title="Testbed", icon="🧪")
sidebar_navigation[""].append(testbed)
api_server = st.Page("content/api_server.py", title="API Server", icon="📡")
sidebar_navigation[""].append(api_server)
tools = st.Page("content/tools/tools.py", title="Tools", icon="🧰")
sidebar_navigation[""].append(tools)
config = st.Page("content/config/config.py", title="Configuration", icon="⚙️")
sidebar_navigation[""].append(config)
if gate_active():
    if is_authenticated():
        sidebar_navigation[""].append(st.Page("content/signout.py", title="Sign-out", icon="🔓"))
    else:
        sidebar_navigation[""].append(st.Page("content/signin.py", title="Sign-in", icon="🔐"))
auth_sidebar()

pg_sidebar = st.navigation(sidebar_navigation, position="sidebar", expanded=False)
pg_sidebar.run()
