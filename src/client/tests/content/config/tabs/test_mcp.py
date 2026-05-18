"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.config.tabs.mcp
"""
# spell-checker: disable

import json
from unittest.mock import MagicMock, patch

import pytest

from client.tests.conftest import AttrDict, Rerun, make_http_error

MODULE = "client.app.content.config.tabs.mcp"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_state(mcp_configs=None, extra=None):
    """Build a minimal session state for MCP tests."""
    data = AttrDict(
        {
            "settings": {
                "database_configs": [],
                "model_configs": [],
                "client_settings": {},
            },
        }
    )
    if mcp_configs is not None:
        data["mcp_configs"] = mcp_configs
    if extra:
        data.update(extra)
    return data


# ---------------------------------------------------------------------------
# _configs_lookup
# ---------------------------------------------------------------------------
class TestConfigsLookup:
    """Tests for _configs_lookup."""

    def test_lookup_by_key(self):
        """Lookup returns a dict keyed by the specified field."""
        state = _make_state(
            mcp_configs={
                "tools": [{"name": "opt_search", "desc": "search"}, {"name": "opt_list", "desc": "list"}],
            }
        )
        with patch(f"{MODULE}.state", state):
            from client.app.content.config.tabs.mcp import _configs_lookup

            result = _configs_lookup("tools", "name")
        assert "opt_search" in result
        assert "opt_list" in result
        assert result["opt_search"]["desc"] == "search"

    def test_none_section_returns_empty(self):
        """A None section value returns an empty dict."""
        state = _make_state(mcp_configs={"tools": None})
        with patch(f"{MODULE}.state", state):
            from client.app.content.config.tabs.mcp import _configs_lookup

            result = _configs_lookup("tools", "name")
        assert result == {}

    def test_empty_section(self):
        """An empty section list returns an empty dict."""
        state = _make_state(mcp_configs={"tools": []})
        with patch(f"{MODULE}.state", state):
            from client.app.content.config.tabs.mcp import _configs_lookup

            result = _configs_lookup("tools", "name")
        assert result == {}

    def test_missing_key_skipped(self):
        """Items without the lookup key are silently skipped."""
        state = _make_state(
            mcp_configs={
                "tools": [{"name": "opt_a"}, {"no_name": True}],
            }
        )
        with patch(f"{MODULE}.state", state):
            from client.app.content.config.tabs.mcp import _configs_lookup

            result = _configs_lookup("tools", "name")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# get_mcp_status
# ---------------------------------------------------------------------------
class TestGetMcpStatus:
    """Tests for get_mcp_status."""

    def test_success(self):
        """Successful API call returns the status dict."""
        with patch(f"{MODULE}.api_get", return_value={"status": "ok", "name": "MCP"}):
            from client.app.content.config.tabs.mcp import get_mcp_status

            result = get_mcp_status()
        assert result["status"] == "ok"

    def test_http_error_returns_empty(self):
        """HTTP error is caught and an empty dict is returned."""
        with patch(f"{MODULE}.api_get", side_effect=make_http_error(500)):
            from client.app.content.config.tabs.mcp import get_mcp_status

            result = get_mcp_status()
        assert result == {}


# ---------------------------------------------------------------------------
# get_mcp_client
# ---------------------------------------------------------------------------
class TestGetMcpClient:
    """Tests for get_mcp_client."""

    def test_returns_json_string_default_client(self):
        """Successful API call returns the default client config as a JSON string."""
        config = {"mcpServers": {"oracle-ai-optimizer": {"url": "http://test/mcp"}}}

        with patch(f"{MODULE}.api_get", return_value=config) as mock_api_get:
            from client.app.content.config.tabs.mcp import get_mcp_client

            result = get_mcp_client()

        assert json.loads(result) == config
        mock_api_get.assert_called_once_with(
            "client-config",
            api_prefix="/mcp",
            params={"client": "generic"},
        )

    def test_returns_json_string_for_selected_client(self):
        """Successful API call passes the selected MCP client to the API."""
        config = {
            "mcpServers": {
                "oracle-ai-optimizer": {
                    "command": "npx",
                    "args": ["-y", "mcp-remote", "http://test/mcp"],
                }
            }
        }

        with patch(f"{MODULE}.api_get", return_value=config) as mock_api_get:
            from client.app.content.config.tabs.mcp import get_mcp_client

            result = get_mcp_client("claude-desktop")

        assert json.loads(result) == config
        mock_api_get.assert_called_once_with(
            "client-config",
            api_prefix="/mcp",
            params={"client": "claude-desktop"},
        )

    def test_http_error_returns_empty_json(self):
        """HTTP error is caught and an empty JSON object string is returned."""
        with patch(f"{MODULE}.api_get", side_effect=make_http_error(500)):
            from client.app.content.config.tabs.mcp import get_mcp_client

            result = get_mcp_client("cline")

        assert result == "{}"

    def test_connection_error_returns_empty_json(self):
        """ConnectionError is caught and an empty JSON object string is returned."""
        with patch(f"{MODULE}.api_get", side_effect=ConnectionError("refused")):
            from client.app.content.config.tabs.mcp import get_mcp_client

            result = get_mcp_client("inspector")

        assert result == "{}"


# ---------------------------------------------------------------------------
# get_mcp
# ---------------------------------------------------------------------------
class TestGetMcp:
    """Tests for get_mcp."""

    def test_fetches_all_endpoints(self):
        """All three MCP endpoints are fetched and stored in state."""
        state = _make_state()
        tools = [{"name": "opt_search"}]
        prompts = [{"name": "opt_greet"}]
        resources = [{"name": "opt_doc"}]

        def _api_get(endpoint, **kwargs):
            return {"tools": tools, "prompts": prompts, "resources": resources}.get(endpoint, {})

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", side_effect=_api_get),
        ):
            from client.app.content.config.tabs.mcp import get_mcp

            get_mcp()
        assert "mcp_configs" in state
        assert state.mcp_configs["tools"] == tools
        assert state.mcp_configs["prompts"] == prompts
        assert state.mcp_configs["resources"] == resources

    def test_skips_when_cached(self):
        """No API calls are made when configs are already cached."""
        state = _make_state(mcp_configs={"tools": [], "prompts": [], "resources": []})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get") as mock_get,
        ):
            from client.app.content.config.tabs.mcp import get_mcp

            get_mcp()
        mock_get.assert_not_called()

    def test_force_refetch(self):
        """Passing force=True re-fetches even when configs are cached."""
        state = _make_state(mcp_configs={"tools": [], "prompts": [], "resources": []})
        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", return_value=[]),
        ):
            from client.app.content.config.tabs.mcp import get_mcp

            get_mcp(force=True)
        assert "mcp_configs" in state

    def test_partial_failure(self):
        """A failing endpoint stores an empty dict while others succeed."""
        state = _make_state()
        call_count = 0

        def _api_get(endpoint, **kwargs):
            nonlocal call_count
            call_count += 1
            if endpoint == "prompts":
                raise make_http_error(500)
            return [{"name": f"opt_{endpoint}"}]

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.api_get", side_effect=_api_get),
        ):
            from client.app.content.config.tabs.mcp import get_mcp

            get_mcp()
        assert state.mcp_configs["prompts"] == {}
        assert len(state.mcp_configs["tools"]) == 1


# ---------------------------------------------------------------------------
# extract_servers
# ---------------------------------------------------------------------------
class TestExtractServers:
    """Tests for extract_servers."""

    def test_unique_prefixes(self):
        """Unique server prefixes are extracted from tool names."""
        state = _make_state(
            mcp_configs={
                "tools": [{"name": "alpha_search"}, {"name": "alpha_list"}, {"name": "beta_run"}],
                "prompts": [],
                "resources": [],
            }
        )
        with patch(f"{MODULE}.state", state):
            from client.app.content.config.tabs.mcp import extract_servers

            result = extract_servers()
        assert result == ["alpha", "beta"]

    def test_optimizer_first(self):
        """The optimizer server is sorted to the front of the list."""
        state = _make_state(
            mcp_configs={
                "tools": [{"name": "optimizer_search"}, {"name": "beta_run"}],
                "prompts": [],
                "resources": [],
            }
        )
        with patch(f"{MODULE}.state", state):
            from client.app.content.config.tabs.mcp import extract_servers

            result = extract_servers()
        assert result[0] == "optimizer"

    def test_no_underscore_skipped(self):
        """Names without an underscore are skipped."""
        state = _make_state(
            mcp_configs={
                "tools": [{"name": "nounderscore"}],
                "prompts": [],
                "resources": [],
            }
        )
        with patch(f"{MODULE}.state", state):
            from client.app.content.config.tabs.mcp import extract_servers

            result = extract_servers()
        assert result == []

    def test_empty_configs(self):
        """Empty config lists produce an empty server list."""
        state = _make_state(
            mcp_configs={
                "tools": [],
                "prompts": [],
                "resources": [],
            }
        )
        with patch(f"{MODULE}.state", state):
            from client.app.content.config.tabs.mcp import extract_servers

            result = extract_servers()
        assert result == []

    def test_none_items_handled(self):
        """None config sections are safely skipped during extraction."""
        state = _make_state(
            mcp_configs={
                "tools": None,
                "prompts": [{"name": "srv_prompt"}],
                "resources": None,
            }
        )
        with patch(f"{MODULE}.state", state):
            from client.app.content.config.tabs.mcp import extract_servers

            result = extract_servers()
        assert result == ["srv"]


# ---------------------------------------------------------------------------
# mcp_details
# ---------------------------------------------------------------------------
class TestMcpDetails:
    """Tests for mcp_details."""

    def test_renders_details(self, mock_st):
        """Detail dialog renders header and subheaders for a valid config."""
        state = _make_state(
            mcp_configs={
                "tools": [{"name": "srv_search", "description": "Search tool", "text": "instructions"}],
            }
        )
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.config.tabs.mcp import mcp_details

            # Call the underlying function (skip the @st.dialog decorator)
            getattr(mcp_details, "__wrapped__")("srv", "tools", "search")
        mock_st.header.assert_called_once()
        assert mock_st.subheader.call_count >= 1

    def test_config_not_found(self, mock_st):
        """Missing config name displays an error."""
        state = _make_state(mcp_configs={"tools": []})
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.config.tabs.mcp import mcp_details

            getattr(mcp_details, "__wrapped__")("srv", "tools", "missing")
        mock_st.error.assert_called_once()

    def test_input_schema_rendered(self, mock_st):
        """Input schema properties are rendered as HTML."""
        state = _make_state(
            mcp_configs={
                "tools": [
                    {
                        "name": "srv_tool",
                        "inputSchema": {
                            "properties": {
                                "query": {"description": "The query", "type": "string", "default": ""},
                            },
                            "required": ["query"],
                        },
                    }
                ],
            }
        )
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
        ):
            from client.app.content.config.tabs.mcp import mcp_details

            getattr(mcp_details, "__wrapped__")("srv", "tools", "tool")
        mock_st.html.assert_called_once()
        html_arg = mock_st.html.call_args[0][0]
        assert "query" in html_arg
        assert "required" in html_arg


# ---------------------------------------------------------------------------
# render_configs
# ---------------------------------------------------------------------------
class TestRenderConfigs:
    """Tests for render_configs."""

    def test_renders_rows(self, mock_st):
        """Each config name gets a text_input and button rendered."""
        # render_configs calls st.columns once; capture the returned cols
        col1, col2 = MagicMock(), MagicMock()
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = [col1, col2]
        with patch(f"{MODULE}.st", mock_st):
            from client.app.content.config.tabs.mcp import render_configs

            render_configs("srv", "tools", ["search", "list"])
        # Header markdown + 2 config text_input calls
        assert col1.text_input.call_count == 2
        assert col2.button.call_count == 2


# ---------------------------------------------------------------------------
# display_mcp
# ---------------------------------------------------------------------------
class TestDisplayMcp:
    """Tests for display_mcp."""

    def test_renders_header_and_status(self, mock_st):
        """Header and status info are rendered when MCP is available."""
        state = _make_state(
            mcp_configs={
                "tools": [{"name": "optimizer_search"}],
                "prompts": [],
                "resources": [],
            }
        )
        mock_st.selectbox.return_value = "optimizer"
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_mcp"),
            patch(f"{MODULE}.get_mcp_status", return_value={"status": "ok", "name": "MCP", "version": "1.0"}),
            patch(f"{MODULE}.get_mcp_client", return_value="{}"),
        ):
            from client.app.content.config.tabs.mcp import display_mcp

            display_mcp()
        mock_st.header.assert_called()

    def test_stops_when_unavailable(self, mock_st):
        """An empty status causes an error and stops rendering."""
        state = _make_state(mcp_configs={"tools": [], "prompts": [], "resources": []})
        mock_st.stop.side_effect = Rerun
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_mcp"),
            patch(f"{MODULE}.get_mcp_status", return_value={}),
        ):
            from client.app.content.config.tabs.mcp import display_mcp

            with pytest.raises(Rerun):
                display_mcp()
        mock_st.error.assert_called_once()

    def test_renders_tools_section(self, mock_st):
        """Tool configs are passed to render_configs for the selected server."""
        state = _make_state(
            mcp_configs={
                "tools": [{"name": "srv_search"}, {"name": "srv_list"}],
                "prompts": [],
                "resources": [],
            }
        )
        mock_st.selectbox.return_value = "srv"
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_mcp"),
            patch(f"{MODULE}.get_mcp_status", return_value={"status": "ok", "name": "MCP", "version": "1.0"}),
            patch(f"{MODULE}.get_mcp_client", return_value="{}"),
            patch(f"{MODULE}.render_configs") as mock_render,
        ):
            from client.app.content.config.tabs.mcp import display_mcp

            display_mcp()
        mock_render.assert_called_once_with("srv", "tools", ["search", "list"])

    def test_no_server_selected_returns_early(self, mock_st):
        """No server selection skips render_configs entirely."""
        state = _make_state(
            mcp_configs={
                "tools": [],
                "prompts": [],
                "resources": [],
            }
        )
        mock_st.selectbox.return_value = None
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_mcp"),
            patch(f"{MODULE}.get_mcp_status", return_value={"status": "ok", "name": "MCP", "version": "1.0"}),
            patch(f"{MODULE}.get_mcp_client", return_value="{}"),
            patch(f"{MODULE}.render_configs") as mock_render,
        ):
            from client.app.content.config.tabs.mcp import display_mcp

            display_mcp()
        mock_render.assert_not_called()

    def test_unauthenticated_skips_client_config(self, mock_st):
        """When unauthenticated, the Client Configuration content is not fetched or rendered."""
        state = _make_state(
            mcp_configs={
                "tools": [],
                "prompts": [],
                "resources": [],
            }
        )
        mock_st.selectbox.return_value = None
        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}.get_mcp"),
            patch(f"{MODULE}.get_mcp_status", return_value={"status": "ok", "name": "MCP", "version": "1.0"}),
            patch(f"{MODULE}.get_mcp_client", return_value="{}") as mock_get_client,
            patch(f"{MODULE}.is_authenticated", return_value=False),
            patch(f"{MODULE}.locked_notice") as mock_locked_notice,
            patch(f"{MODULE}.render_configs"),
        ):
            from client.app.content.config.tabs.mcp import display_mcp

            display_mcp()
        mock_get_client.assert_not_called()
        mock_st.expander.assert_not_called()
        mock_locked_notice.assert_called_once()
