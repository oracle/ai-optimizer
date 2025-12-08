# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import MagicMock

from streamlit import session_state as state


#############################################################################
# Test tools_sidebar Function
#############################################################################
class TestToolsSidebar:
    """Test tools_sidebar function"""

    def test_selected_tool_becomes_unavailable_resets_to_empty(self, app_server, monkeypatch):
        """Test that when a previously selected tool becomes unavailable, it resets to empty list.

        This tests the bug fix where a user selects Vector Search, then the database
        disconnects, and the tool_box no longer contains Vector Search. Without the fix,
        the multiselect default would contain invalid options.
        """
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User had previously selected Vector Search
        state.client_settings = {
            "tools_enabled": ["Vector Search"],
            "database": {"alias": "DEFAULT"},
        }
        # Mock the state that multiselect widget would set (empty since no tools available)
        state.selected_tools = []

        # Mock: Database is not configured (makes Vector Search and NL2SQL unavailable)
        monkeypatch.setattr(st_common, "is_db_configured", lambda: False)

        # Mock Streamlit UI components
        mock_warning = MagicMock()
        mock_multiselect = MagicMock()
        mock_sidebar = MagicMock()
        mock_sidebar.multiselect = mock_multiselect

        monkeypatch.setattr(st, "warning", mock_warning)
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar - this should reset to empty list instead of crashing
        tool_options.tools_sidebar()

        # Verify the settings were reset to empty (LLM only)
        assert state.client_settings["tools_enabled"] == []

        # Verify multiselect was called with empty options (no tools available)
        mock_multiselect.assert_called_once()
        call_args = mock_multiselect.call_args
        tool_box_arg = call_args[1]["options"]
        assert tool_box_arg == []

    def test_nl2sql_selected_becomes_unavailable_resets_to_empty(self, app_server, monkeypatch):
        """Test that when NL2SQL was selected and database disconnects, it resets to empty list."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User had previously selected NL2SQL
        state.client_settings = {
            "tools_enabled": ["NL2SQL"],
            "database": {"alias": "DEFAULT"},
        }
        # Mock the state that multiselect widget would set (empty since no tools available)
        state.selected_tools = []

        # Mock: Database is not configured
        monkeypatch.setattr(st_common, "is_db_configured", lambda: False)

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify the settings were reset to empty (LLM only)
        assert state.client_settings["tools_enabled"] == []

    def test_vector_search_disabled_no_embedding_models(self, app_server, monkeypatch):
        """Test Vector Search is disabled when no embedding models are configured."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User selected Vector Search, but embedding models are disabled
        state.client_settings = {
            "tools_enabled": ["Vector Search"],
            "database": {"alias": "DEFAULT"},
        }
        state.database_configs = [{"name": "DEFAULT", "vector_stores": [{"model": "embed-model"}]}]
        # Mock the state that multiselect widget would set (empty since VS not selected after reset)
        state.selected_tools = []

        # Mock: Database is configured but no embedding models enabled
        monkeypatch.setattr(st_common, "is_db_configured", lambda: True)
        monkeypatch.setattr(st_common, "enabled_models_lookup", lambda x: {})
        monkeypatch.setattr(st_common, "state_configs_lookup", lambda *args: {
            "DEFAULT": {"vector_stores": [{"model": "embed-model"}]}
        })

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify the settings were reset to empty (Vector Search disabled, only NL2SQL available)
        assert state.client_settings["tools_enabled"] == []

    def test_vector_search_disabled_no_matching_vector_stores(self, app_server, monkeypatch):
        """Test Vector Search is disabled when vector stores don't match enabled embedding models."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User selected Vector Search
        state.client_settings = {
            "tools_enabled": ["Vector Search"],
            "database": {"alias": "DEFAULT"},
        }
        # Mock the state that multiselect widget would set (empty since VS not selected after reset)
        state.selected_tools = []

        # Mock: Database has vector stores but they use a different embedding model
        monkeypatch.setattr(st_common, "is_db_configured", lambda: True)
        monkeypatch.setattr(st_common, "enabled_models_lookup", lambda x: {"openai/text-embed-3": {}})
        monkeypatch.setattr(st_common, "state_configs_lookup", lambda *args: {
            "DEFAULT": {"vector_stores": [{"model": "cohere/embed-v3"}]}  # Different model
        })

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify the settings were reset to empty (Vector Search disabled, only NL2SQL available)
        assert state.client_settings["tools_enabled"] == []

    def test_all_tools_enabled_when_configured(self, app_server, monkeypatch):
        """Test all tools remain enabled when properly configured."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User has Vector Search selected
        state.client_settings = {
            "tools_enabled": ["Vector Search"],
            "database": {"alias": "DEFAULT"},
            "vector_search": {
                "discovery": True,
                "rephrase": True,
                "grade": True,
            },
        }
        # Mock the state that multiselect widget would set
        state.selected_tools = ["Vector Search"]

        # Mock: Everything is properly configured
        monkeypatch.setattr(st_common, "is_db_configured", lambda: True)
        monkeypatch.setattr(st_common, "enabled_models_lookup", lambda x: {"openai/text-embed-3": {}})
        monkeypatch.setattr(st_common, "state_configs_lookup", lambda *args: {
            "DEFAULT": {"vector_stores": [{"model": "openai/text-embed-3"}]}
        })

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify the settings remain as Vector Search (not reset)
        assert state.client_settings["tools_enabled"] == ["Vector Search"]

        # Verify multiselect was called with all tools available
        mock_sidebar.multiselect.assert_called_once()
        call_args = mock_sidebar.multiselect.call_args
        tool_box_arg = call_args[1]["options"]
        assert "Vector Search" in tool_box_arg
        assert "NL2SQL" in tool_box_arg

    def test_empty_tools_enabled_means_llm_only(self, app_server, monkeypatch):
        """Test that an empty tools_enabled list means LLM only mode."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: Empty tools_enabled (LLM only mode)
        state.client_settings = {
            "tools_enabled": [],
            "database": {"alias": "DEFAULT"},
        }
        # Mock the state that multiselect widget would set
        state.selected_tools = []

        # Mock: Database not configured (no tools available)
        monkeypatch.setattr(st_common, "is_db_configured", lambda: False)

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify tools_enabled remains empty (LLM only)
        assert state.client_settings["tools_enabled"] == []

        # Verify multiselect has no options available (all tools disabled)
        call_args = mock_sidebar.multiselect.call_args
        tool_box_arg = call_args[1]["options"]
        assert tool_box_arg == []

    def test_vector_search_disabled_no_vector_stores(self, app_server, monkeypatch):
        """Test Vector Search is disabled when database has no vector stores."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User selected Vector Search
        state.client_settings = {
            "tools_enabled": ["Vector Search"],
            "database": {"alias": "DEFAULT"},
        }
        # Mock the state that multiselect widget would set (empty since VS not selected after reset)
        state.selected_tools = []

        # Mock: Database configured but has no vector stores
        monkeypatch.setattr(st_common, "is_db_configured", lambda: True)
        monkeypatch.setattr(st_common, "enabled_models_lookup", lambda x: {"openai/text-embed-3": {}})
        monkeypatch.setattr(st_common, "state_configs_lookup", lambda *args: {
            "DEFAULT": {"vector_stores": []}  # Empty vector stores
        })

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify the settings were reset to empty (Vector Search disabled, only NL2SQL available)
        assert state.client_settings["tools_enabled"] == []

    def test_multiple_tools_one_becomes_unavailable(self, app_server, monkeypatch):
        """Test that when multiple tools are selected and one becomes unavailable, only that one is removed."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User had both Vector Search and NL2SQL selected
        state.client_settings = {
            "tools_enabled": ["Vector Search", "NL2SQL"],
            "database": {"alias": "DEFAULT"},
        }
        # Mock the state that multiselect widget would set (NL2SQL remains)
        state.selected_tools = ["NL2SQL"]

        # Mock: Database configured but no embedding models (disables Vector Search only)
        monkeypatch.setattr(st_common, "is_db_configured", lambda: True)
        monkeypatch.setattr(st_common, "enabled_models_lookup", lambda x: {})
        monkeypatch.setattr(st_common, "state_configs_lookup", lambda *args: {
            "DEFAULT": {"vector_stores": [{"model": "embed-model"}]}
        })

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify Vector Search was removed but NL2SQL remains
        assert state.client_settings["tools_enabled"] == ["NL2SQL"]

        # Verify multiselect was called with only NL2SQL available
        call_args = mock_sidebar.multiselect.call_args
        tool_box_arg = call_args[1]["options"]
        assert "NL2SQL" in tool_box_arg
        assert "Vector Search" not in tool_box_arg

    def test_multiple_tools_all_become_unavailable(self, app_server, monkeypatch):
        """Test that when multiple tools are selected and all become unavailable, list becomes empty."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User had both Vector Search and NL2SQL selected
        state.client_settings = {
            "tools_enabled": ["Vector Search", "NL2SQL"],
            "database": {"alias": "DEFAULT"},
        }
        # Mock the state that multiselect widget would set (empty since no tools available)
        state.selected_tools = []

        # Mock: Database is not configured (disables both tools)
        monkeypatch.setattr(st_common, "is_db_configured", lambda: False)

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify both tools were removed
        assert state.client_settings["tools_enabled"] == []

        # Verify multiselect was called with no options
        call_args = mock_sidebar.multiselect.call_args
        tool_box_arg = call_args[1]["options"]
        assert tool_box_arg == []

    def test_invalid_tool_in_tools_enabled_gets_filtered(self, app_server, monkeypatch):
        """Test that unknown/stale tools in tools_enabled are filtered out."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User has a valid tool and an invalid/stale tool
        state.client_settings = {
            "tools_enabled": ["Vector Search", "SomeOldTool", "AnotherInvalidTool"],
            "database": {"alias": "DEFAULT"},
            "vector_search": {
                "discovery": True,
                "rephrase": True,
                "grade": True,
            },
        }
        # Mock the state that multiselect widget would set
        state.selected_tools = ["Vector Search"]

        # Mock: Everything properly configured for Vector Search
        monkeypatch.setattr(st_common, "is_db_configured", lambda: True)
        monkeypatch.setattr(st_common, "enabled_models_lookup", lambda x: {"openai/text-embed-3": {}})
        monkeypatch.setattr(st_common, "state_configs_lookup", lambda *args: {
            "DEFAULT": {"vector_stores": [{"model": "openai/text-embed-3"}]}
        })

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify invalid tools were filtered out, only Vector Search remains
        assert state.client_settings["tools_enabled"] == ["Vector Search"]

    def test_nl2sql_remains_when_only_vector_search_disabled(self, app_server, monkeypatch):
        """Test that NL2SQL stays available when only Vector Search is disabled."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User has NL2SQL selected
        state.client_settings = {
            "tools_enabled": ["NL2SQL"],
            "database": {"alias": "DEFAULT"},
        }
        # Mock the state that multiselect widget would set
        state.selected_tools = ["NL2SQL"]

        # Mock: Database configured but Vector Search disabled (no embedding models)
        monkeypatch.setattr(st_common, "is_db_configured", lambda: True)
        monkeypatch.setattr(st_common, "enabled_models_lookup", lambda x: {})
        monkeypatch.setattr(st_common, "state_configs_lookup", lambda *args: {
            "DEFAULT": {"vector_stores": []}
        })

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify NL2SQL remains selected
        assert state.client_settings["tools_enabled"] == ["NL2SQL"]

        # Verify multiselect was called with NL2SQL available but not Vector Search
        call_args = mock_sidebar.multiselect.call_args
        tool_box_arg = call_args[1]["options"]
        assert "NL2SQL" in tool_box_arg
        assert "Vector Search" not in tool_box_arg
