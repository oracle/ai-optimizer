"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import streamlit as st
from streamlit import session_state as state


def display_mcp() -> None:
    """Streamlit GUI"""
    st.header("Model Context Protocol", divider="red")
