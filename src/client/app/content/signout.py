"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Sign-out navigation entry.
"""
# spell-checker:ignore streamlit

import streamlit as st

from client.app.core.auth import sign_out

sign_out()
st.switch_page("content/chatbot.py")
