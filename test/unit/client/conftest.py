# pylint: disable=import-error,redefined-outer-name,unused-import
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit test fixtures for client tests. Unit tests mock dependencies rather than
requiring a real server, but some fixtures help establish Streamlit session state.
"""
# spell-checker: disable

import os
import sys

# Re-export shared vector store fixtures for pytest discovery
from test.shared_fixtures import (  # noqa: F401
    sample_vector_store_data,
    sample_vector_store_data_alt,
    sample_vector_stores_list,
)

import pytest
from streamlit import session_state as state

# Add src to path for client imports
SRC_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)


@pytest.fixture(scope="session")
def app_server():
    """
    Minimal fixture for unit tests that just need session state initialized.

    Unlike integration tests, this doesn't actually start a server.
    It just ensures Streamlit session state is available for testing.
    """
    # Initialize basic state required by client modules
    if not hasattr(state, "server"):
        state.server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
    if not hasattr(state, "client_settings"):
        state.client_settings = {"client": "test-client", "ll_model": {}}

    yield True  # Just return True to indicate fixture is available
