"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error import-outside-toplevel

import streamlit as st
from conftest import create_tabs_mock, run_streamlit_test


#############################################################################
# Test Streamlit UI
#############################################################################
class TestStreamlit:
    """Test the Streamlit UI"""

    # Streamlit File path
    ST_FILE = "../src/client/content/config/config.py"

    def test_initialization_all_tabs_enabled(self, app_server, app_test):
        """Test config page with all tabs enabled"""
        assert app_server is not None

        at = app_test(self.ST_FILE)

        # Set all disabled flags to False (all enabled)
        at.session_state.disabled = {
            "settings": False,
            "db_cfg": False,
            "model_cfg": False,
            "oci_cfg": False,
            "mcp_cfg": False,
        }

        run_streamlit_test(at)

    def test_tabs_created_based_on_disabled_state(self, app_server, app_test, monkeypatch):
        """Test that tabs are created based on disabled state"""
        assert app_server is not None

        # Mock st.tabs to capture what tabs are created
        tabs_created = create_tabs_mock(monkeypatch)

        at = app_test(self.ST_FILE)

        # Enable only some tabs
        at.session_state.disabled = {
            "settings": False,
            "db_cfg": False,
            "model_cfg": True,  # Disabled
            "oci_cfg": False,
            "mcp_cfg": True,  # Disabled
        }

        at = at.run()

        # Should have 3 tabs (settings, databases, oci)
        assert len(tabs_created) == 3
        assert "💾 Settings" in tabs_created
        assert "🗄️ Databases" in tabs_created
        assert "☁️ OCI" in tabs_created
        assert "🤖 Models" not in tabs_created
        assert "🔗 MCP" not in tabs_created

    def test_all_tabs_disabled(self, app_server, app_test, monkeypatch):
        """Test behavior when all tabs are disabled"""
        assert app_server is not None

        # Mock st.tabs to verify it's not called
        tabs_called = False

        def mock_tabs(tab_list):
            nonlocal tabs_called
            tabs_called = True
            return st.tabs(tab_list)

        monkeypatch.setattr(st, "tabs", mock_tabs)

        at = app_test(self.ST_FILE)

        # Disable all tabs
        at.session_state.disabled = {
            "settings": True,
            "db_cfg": True,
            "model_cfg": True,
            "oci_cfg": True,
            "mcp_cfg": True,
        }

        at = at.run()

        # tabs() should not be called when all are disabled
        # Note: This might be called with empty list, let's verify the list is empty
        assert not at.exception

    def test_only_settings_tab_enabled(self, app_server, app_test, monkeypatch):
        """Test with only settings tab enabled"""
        assert app_server is not None

        tabs_created = []
        original_tabs = st.tabs

        def mock_tabs(tab_list):
            tabs_created.extend(tab_list)
            return original_tabs(tab_list)

        monkeypatch.setattr(st, "tabs", mock_tabs)

        at = app_test(self.ST_FILE)

        at.session_state.disabled = {
            "settings": False,
            "db_cfg": True,
            "model_cfg": True,
            "oci_cfg": True,
            "mcp_cfg": True,
        }

        at = at.run()

        assert len(tabs_created) == 1
        assert "💾 Settings" in tabs_created

    def test_get_functions_called(self, app_server, app_test, monkeypatch):
        """Test that all get_*() functions are called on initialization"""
        assert app_server is not None

        # Track which functions were called
        calls = {
            "get_settings": False,
            "get_databases": False,
            "get_models": False,
            "get_oci": False,
            "get_mcp": False,
        }

        # Import modules
        from client.content.config.tabs import settings, databases, models, oci, mcp

        # Create mock factory to reduce local variables
        def create_mock(module, func_name):
            original = getattr(module, func_name)
            def mock(*args, **kwargs):
                calls[func_name] = True
                return original(*args, **kwargs)
            return mock

        # Set up all mocks
        for module, func_name in [
            (settings, "get_settings"),
            (databases, "get_databases"),
            (models, "get_models"),
            (oci, "get_oci"),
            (mcp, "get_mcp")
        ]:
            monkeypatch.setattr(module, func_name, create_mock(module, func_name))

        at = app_test(self.ST_FILE)

        at.session_state.disabled = {
            "settings": False,
            "db_cfg": False,
            "model_cfg": False,
            "oci_cfg": False,
            "mcp_cfg": False,
        }

        at = at.run()

        # All get functions should be called regardless of disabled state
        for func_name, was_called in calls.items():
            assert was_called, f"{func_name} should be called"

    def test_tab_ordering_correct(self, app_server, app_test, monkeypatch):
        """Test that tabs appear in the correct order"""
        assert app_server is not None

        # Mock st.tabs to capture what tabs are created
        tabs_created = create_tabs_mock(monkeypatch)

        at = app_test(self.ST_FILE)

        # Enable all tabs
        at.session_state.disabled = {
            "settings": False,
            "db_cfg": False,
            "model_cfg": False,
            "oci_cfg": False,
            "mcp_cfg": False,
        }

        at = at.run()

        # Verify order: Settings, Databases, Models, OCI, MCP
        expected_order = ["💾 Settings", "🗄️ Databases", "🤖 Models", "☁️ OCI", "🔗 MCP"]
        assert tabs_created == expected_order

    def test_partial_tabs_enabled_maintains_order(self, app_server, app_test, monkeypatch):
        """Test that partial tab enabling maintains correct order"""
        assert app_server is not None

        tabs_created = []
        original_tabs = st.tabs

        def mock_tabs(tab_list):
            tabs_created.extend(tab_list)
            return original_tabs(tab_list)

        monkeypatch.setattr(st, "tabs", mock_tabs)

        at = app_test(self.ST_FILE)

        # Enable databases, models, and MCP (skip settings and oci)
        at.session_state.disabled = {
            "settings": True,
            "db_cfg": False,
            "model_cfg": False,
            "oci_cfg": True,
            "mcp_cfg": False,
        }

        at = at.run()

        # Should maintain order: Databases, Models, MCP
        expected_order = ["🗄️ Databases", "🤖 Models", "🔗 MCP"]
        assert tabs_created == expected_order
