"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore streamlit

import logging

import streamlit as st
from streamlit import session_state as state

LOGGER = logging.getLogger("content.chatbot")

LOGGER.info("Chatbot page loaded")
st.write(state)
