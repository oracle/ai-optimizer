"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error import-outside-toplevel

from client.utils import api_call


#############################################################################
# Test MCP Functions (Unit Tests)
#############################################################################
class TestMCPFunctions:
    """Test MCP utility functions (unit tests without AppTest)"""

    def test_get_mcp_status_success(self, app_server, monkeypatch):
        """Test get_mcp_status when API call succeeds"""
        assert app_server is not None

        # Mock api_call.get to return a status
        def mock_get(endpoint):
            if endpoint == "v1/mcp/healthz":
                return {"status": "ready", "name": "FastMCP", "version": "1.0.0"}
            return {}

        monkeypatch.setattr(api_call, "get", mock_get)

        from client.content.config.tabs.mcp import get_mcp_status

        status = get_mcp_status()

        assert status["status"] == "ready"
        assert status["name"] == "FastMCP"
        assert status["version"] == "1.0.0"

    def test_get_mcp_status_api_error(self, app_server, monkeypatch):
        """Test get_mcp_status when API call fails"""
        assert app_server is not None

        # Mock api_call.get to raise ApiError
        def mock_get(endpoint):
            raise api_call.ApiError("Connection failed")

        monkeypatch.setattr(api_call, "get", mock_get)

        from client.content.config.tabs.mcp import get_mcp_status

        status = get_mcp_status()

        # Should return empty dict on error
        assert status == {}

    def test_get_mcp_client_api_error(self, app_server, monkeypatch):
        """Test get_mcp_client when API call fails"""
        assert app_server is not None

        # Mock api_call.get to raise ApiError
        def mock_get(endpoint, params=None):
            raise api_call.ApiError("Connection failed")

        monkeypatch.setattr(api_call, "get", mock_get)

        from client.content.config.tabs.mcp import get_mcp_client
        from streamlit import session_state as state

        state.server = {"url": "http://localhost", "port": 8000}

        client_config = get_mcp_client()

        # Should return empty JSON string on error
        assert client_config == "{}"

    def test_get_mcp_force_refresh(self, app_server, monkeypatch):
        """Test get_mcp with force refresh"""
        assert app_server is not None

        # Track API calls
        api_calls = []

        def mock_get(endpoint):
            api_calls.append(endpoint)
            return []

        monkeypatch.setattr(api_call, "get", mock_get)

        from client.content.config.tabs.mcp import get_mcp
        from streamlit import session_state as state

        # Set existing mcp_configs
        state.mcp_configs = {"tools": [], "prompts": [], "resources": []}

        # Call with force=False (should not refresh)
        api_calls.clear()
        get_mcp(force=False)
        assert len(api_calls) == 0  # Should not call API

        # Call with force=True (should refresh)
        api_calls.clear()
        get_mcp(force=True)
        assert len(api_calls) == 3  # Should call API for tools, prompts, resources

    def test_get_mcp_initial_load(self, app_server, monkeypatch):
        """Test get_mcp on initial load (no mcp_configs in state)"""
        assert app_server is not None

        # Track API calls
        api_calls = []

        def mock_get(endpoint):
            api_calls.append(endpoint)
            if endpoint == "v1/mcp/tools":
                return [{"name": "optimizer_test"}]
            if endpoint == "v1/mcp/prompts":
                return [{"name": "optimizer_prompt"}]
            if endpoint == "v1/mcp/resources":
                return [{"name": "optimizer_resource"}]
            return []

        monkeypatch.setattr(api_call, "get", mock_get)

        from client.content.config.tabs.mcp import get_mcp
        from streamlit import session_state as state

        # Clear mcp_configs
        if hasattr(state, "mcp_configs"):
            delattr(state, "mcp_configs")

        # Call get_mcp
        get_mcp()

        # Should call all three endpoints
        assert len(api_calls) == 3
        assert "v1/mcp/tools" in api_calls
        assert "v1/mcp/prompts" in api_calls
        assert "v1/mcp/resources" in api_calls

        # Should set state.mcp_configs
        assert hasattr(state, "mcp_configs")
        assert "tools" in state.mcp_configs
        assert "prompts" in state.mcp_configs
        assert "resources" in state.mcp_configs

    def test_get_mcp_partial_api_failure(self, app_server, monkeypatch):
        """Test get_mcp when some API calls fail"""
        assert app_server is not None

        # Mock API calls where tools fails but others succeed
        def mock_get(endpoint):
            if endpoint == "v1/mcp/tools":
                raise api_call.ApiError("Tools endpoint failed")
            if endpoint == "v1/mcp/prompts":
                return [{"name": "optimizer_prompt"}]
            if endpoint == "v1/mcp/resources":
                return [{"name": "optimizer_resource"}]
            return []

        monkeypatch.setattr(api_call, "get", mock_get)

        from client.content.config.tabs.mcp import get_mcp
        from streamlit import session_state as state

        # Clear mcp_configs
        if hasattr(state, "mcp_configs"):
            delattr(state, "mcp_configs")

        # Call get_mcp
        get_mcp()

        # Should set state.mcp_configs even with partial failure
        assert hasattr(state, "mcp_configs")
        assert state.mcp_configs["tools"] == {}  # Failed endpoint returns empty dict
        assert len(state.mcp_configs["prompts"]) == 1
        assert len(state.mcp_configs["resources"]) == 1

    def test_extract_servers_single_server(self, app_server):
        """Test extracting MCP servers from configs"""
        assert app_server is not None

        from streamlit import session_state as state
        from client.content.config.tabs.mcp import extract_servers

        # Set mcp_configs in module state
        state.mcp_configs = {
            "tools": [
                {"name": "optimizer_tool1", "description": "Tool 1"},
                {"name": "optimizer_tool2", "description": "Tool 2"},
            ],
            "prompts": [{"name": "optimizer_prompt1", "description": "Prompt 1"}],
            "resources": [],
        }

        servers = extract_servers()

        # Should extract "optimizer" as the server
        assert "optimizer" in servers
        assert servers[0] == "optimizer"  # optimizer should be first

    def test_extract_servers_multiple_servers(self, app_server):
        """Test extracting multiple MCP servers"""
        assert app_server is not None

        from streamlit import session_state as state
        from client.content.config.tabs.mcp import extract_servers

        state.mcp_configs = {
            "tools": [
                {"name": "optimizer_tool1", "description": "Tool 1"},
                {"name": "custom_tool1", "description": "Custom tool"},
                {"name": "external_tool1", "description": "External tool"},
            ],
            "prompts": [{"name": "optimizer_prompt1", "description": "Prompt 1"}],
            "resources": [{"name": "custom_resource1", "description": "Resource 1"}],
        }

        servers = extract_servers()

        # Should have three servers
        assert len(servers) == 3
        # optimizer should be first
        assert servers[0] == "optimizer"
        # Others should be sorted
        assert set(servers) == {"optimizer", "custom", "external"}

    def test_extract_servers_no_underscore(self, app_server):
        """Test extract_servers with names without underscores"""
        assert app_server is not None

        from streamlit import session_state as state
        from client.content.config.tabs.mcp import extract_servers

        state.mcp_configs = {
            "tools": [{"name": "notool", "description": "No underscore"}],
            "prompts": [],
            "resources": [],
        }

        servers = extract_servers()

        # Should return empty list since no underscores
        assert len(servers) == 0

    def test_extract_servers_with_none_items(self, app_server):
        """Test extract_servers handles None safely"""
        assert app_server is not None

        from streamlit import session_state as state
        from client.content.config.tabs.mcp import extract_servers

        # Set mcp_configs with None values
        state.mcp_configs = {
            "tools": None,
            "prompts": None,
            "resources": None,
        }

        servers = extract_servers()

        # Should handle None gracefully
        assert servers == []

    def test_display_mcp_server_not_ready(self, app_server, monkeypatch):
        """Test behavior when MCP server is not ready"""
        assert app_server is not None

        from client.content.config.tabs import mcp
        from streamlit import session_state as state

        # Mock get_mcp_status to return not ready
        def mock_get_mcp_status():
            return {"status": "not_ready"}

        monkeypatch.setattr(mcp, "get_mcp_status", mock_get_mcp_status)

        # Set mcp_configs in module state
        state.mcp_configs = {"tools": [], "prompts": [], "resources": []}

        # Call get_mcp_status directly to verify mock
        status = mcp.get_mcp_status()
        assert status["status"] == "not_ready"
