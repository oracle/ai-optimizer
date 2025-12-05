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

    def test_selected_tool_becomes_unavailable_resets_to_llm_only(self, app_server, monkeypatch):
        """Test that when a previously selected tool becomes unavailable, it resets to LLM Only.

        This tests the bug fix where a user selects Vector Search, then the database
        disconnects, and the tool_box no longer contains Vector Search. Without the fix,
        tool_box.index(current_tool) would raise ValueError.
        """
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User had previously selected Vector Search
        state.client_settings = {
            "tools_enabled": ["Vector Search"],
            "database": {"alias": "DEFAULT"},
        }

        # Mock: Database is not configured (makes Vector Search and NL2SQL unavailable)
        monkeypatch.setattr(st_common, "is_db_configured", lambda: False)

        # Mock Streamlit UI components
        mock_warning = MagicMock()
        mock_selectbox = MagicMock()
        mock_sidebar = MagicMock()
        mock_sidebar.selectbox = mock_selectbox

        monkeypatch.setattr(st, "warning", mock_warning)
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar - this should reset to "LLM Only" instead of crashing
        tool_options.tools_sidebar()

        # Verify the settings were reset to LLM Only
        assert state.client_settings["tools_enabled"] == ["LLM Only"]

        # Verify selectbox was called with only LLM Only available
        mock_selectbox.assert_called_once()
        call_args = mock_selectbox.call_args
        tool_box_arg = call_args[0][1]  # Second positional arg is the options list
        assert tool_box_arg == ["LLM Only"]
        assert call_args[1]["index"] == 0

    def test_nl2sql_selected_becomes_unavailable_resets_to_llm_only(self, app_server, monkeypatch):
        """Test that when NL2SQL was selected and database disconnects, it resets to LLM Only."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: User had previously selected NL2SQL
        state.client_settings = {
            "tools_enabled": ["NL2SQL"],
            "database": {"alias": "DEFAULT"},
        }

        # Mock: Database is not configured
        monkeypatch.setattr(st_common, "is_db_configured", lambda: False)

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify the settings were reset to LLM Only
        assert state.client_settings["tools_enabled"] == ["LLM Only"]

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

        # Verify the settings were reset to LLM Only (Vector Search disabled)
        assert state.client_settings["tools_enabled"] == ["LLM Only"]

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

        # Verify the settings were reset to LLM Only
        assert state.client_settings["tools_enabled"] == ["LLM Only"]

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

        # Verify selectbox was called with all tools available
        mock_sidebar.selectbox.assert_called_once()
        call_args = mock_sidebar.selectbox.call_args
        tool_box_arg = call_args[0][1]
        assert "LLM Only" in tool_box_arg
        assert "Vector Search" in tool_box_arg
        assert "NL2SQL" in tool_box_arg

    def test_llm_only_always_available(self, app_server, monkeypatch):
        """Test that LLM Only is always in the tool box regardless of configuration."""
        assert app_server is not None

        from client.utils import st_common, tool_options
        import streamlit as st

        # Setup: LLM Only selected
        state.client_settings = {
            "tools_enabled": ["LLM Only"],
            "database": {"alias": "DEFAULT"},
        }

        # Mock: Database not configured (disables other tools)
        monkeypatch.setattr(st_common, "is_db_configured", lambda: False)

        # Mock Streamlit UI components
        mock_sidebar = MagicMock()
        monkeypatch.setattr(st, "warning", MagicMock())
        monkeypatch.setattr(st, "sidebar", mock_sidebar)

        # Call tools_sidebar
        tool_options.tools_sidebar()

        # Verify LLM Only remains selected (no reset needed)
        assert state.client_settings["tools_enabled"] == ["LLM Only"]

        # Verify selectbox has LLM Only available
        call_args = mock_sidebar.selectbox.call_args
        tool_box_arg = call_args[0][1]
        assert "LLM Only" in tool_box_arg

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

        # Verify the settings were reset to LLM Only
        assert state.client_settings["tools_enabled"] == ["LLM Only"]
