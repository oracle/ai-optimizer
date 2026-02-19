"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore streamlit

import logging

import streamlit as st
from streamlit import session_state as state

from _version import __version__
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

st.write(state)
