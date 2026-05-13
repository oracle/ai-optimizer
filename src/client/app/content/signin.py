"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Sign-in navigation entry. Calls ``request_signin()`` (which sets a session-
state flag consumed by ``auth_sidebar``) then switches back to ChatBot.
``st.switch_page`` clears query params, so the trigger travels via
session_state which survives navigation.
"""
# spell-checker:ignore streamlit

import streamlit as st

from client.app.core.auth import is_authenticated, request_signin

if not is_authenticated():
    request_signin()
st.switch_page("content/chatbot.py")
