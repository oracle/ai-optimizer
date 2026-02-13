"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/utils/chat.py
Tests for chat completion utility functions.
"""
# pylint: disable=too-few-public-methods protected-access

from dataclasses import dataclass
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from server.api.utils import chat as utils_chat
from common.schema import ChatRequest


@dataclass
class CompletionMocks:
    """Container for completion_generator test mocks."""

    get_client: MagicMock
    oci_get: MagicMock
    get_config: MagicMock
    get_mcp: MagicMock
    mcp_client_class: MagicMock
    graph_main: MagicMock
    get_prompt: MagicMock


#############################################################################
# Tests for _get_system_prompt
#############################################################################
class TestGetSystemPrompt:
    """Tests for the _get_system_prompt helper function."""

    @patch("server.api.utils.chat.default_prompts.get_prompt_with_override")
    def test_returns_basic_prompt_when_no_tools(self, mock_get_prompt):
        """Should return basic-default prompt when tools_enabled is empty."""
        mock_get_prompt.return_value = "Basic prompt"

        result = utils_chat._get_system_prompt([])

        mock_get_prompt.assert_called_once_with("optimizer_basic-default")
        assert result == "Basic prompt"

    @patch("server.api.utils.chat.default_prompts.get_prompt_with_override")
    def test_returns_vs_tools_prompt_when_only_vector_search_enabled(self, mock_get_prompt):
        """Should return vs_tools-default prompt when only Vector Search is enabled."""
        mock_get_prompt.return_value = "VS Tools prompt"

        result = utils_chat._get_system_prompt(["Vector Search"])

        mock_get_prompt.assert_called_once_with("optimizer_vs_tools-default")
        assert result == "VS Tools prompt"

    @patch("server.api.utils.chat.default_prompts.get_prompt_with_override")
    def test_returns_nl2sql_tools_prompt_when_only_nl2sql_enabled(self, mock_get_prompt):
        """Should return nl2sql_tools-default prompt when only NL2SQL is enabled."""
        mock_get_prompt.return_value = "NL2SQL Tools prompt"

        result = utils_chat._get_system_prompt(["NL2SQL"])

        mock_get_prompt.assert_called_once_with("optimizer_nl2sql_tools-default")
        assert result == "NL2SQL Tools prompt"

    @patch("server.api.utils.chat.default_prompts.get_prompt_with_override")
    def test_returns_tools_prompt_with_multiple_tools(self, mock_get_prompt):
        """Should return tools-default prompt when both tools are enabled."""
        mock_get_prompt.return_value = "Tools prompt"

        result = utils_chat._get_system_prompt(["Vector Search", "NL2SQL"])

        mock_get_prompt.assert_called_once_with("optimizer_tools-default")
        assert result == "Tools prompt"


#############################################################################
# Tests for _filter_tools_by_enabled
#############################################################################
class TestFilterToolsByEnabled:
    """Tests for the _filter_tools_by_enabled helper function."""

    def _make_tool(self, name: str) -> MagicMock:
        """Create a mock tool with the given name."""
        tool = MagicMock()
        tool.name = name
        return tool

    def test_filters_vs_tools_when_vector_search_disabled(self):
        """Should filter out optimizer_vs* tools when Vector Search not enabled."""
        tools = [
            self._make_tool("optimizer_vs-retriever"),
            self._make_tool("optimizer_vs-grade"),
            self._make_tool("sqlcl_query"),
            self._make_tool("other_tool"),
        ]

        result = utils_chat._filter_tools_by_enabled(tools, ["NL2SQL"])

        result_names = [t.name for t in result]
        assert "optimizer_vs-retriever" not in result_names
        assert "optimizer_vs-grade" not in result_names
        assert "sqlcl_query" in result_names
        assert "other_tool" in result_names

    def test_filters_internal_vs_tools_when_vector_search_enabled(self):
        """Should filter out internal VS tools (grade/rephrase) when Vector Search enabled."""
        tools = [
            self._make_tool("optimizer_vs-retriever"),
            self._make_tool("optimizer_vs-grade"),
            self._make_tool("optimizer_vs-rephrase"),
            self._make_tool("optimizer_vs-discovery"),
            self._make_tool("other_tool"),
        ]

        result = utils_chat._filter_tools_by_enabled(tools, ["Vector Search"])

        result_names = [t.name for t in result]
        assert "optimizer_vs-retriever" in result_names
        assert "optimizer_vs-discovery" in result_names
        assert "optimizer_vs-grade" not in result_names
        assert "optimizer_vs-rephrase" not in result_names
        assert "other_tool" in result_names

    def test_filters_sqlcl_tools_when_nl2sql_disabled(self):
        """Should filter out sqlcl_* tools when NL2SQL not enabled."""
        tools = [
            self._make_tool("sqlcl_query"),
            self._make_tool("sqlcl_describe"),
            self._make_tool("optimizer_vs-retriever"),
            self._make_tool("other_tool"),
        ]

        result = utils_chat._filter_tools_by_enabled(tools, ["Vector Search"])

        result_names = [t.name for t in result]
        assert "sqlcl_query" not in result_names
        assert "sqlcl_describe" not in result_names
        # VS internal tools filtered
        assert "other_tool" in result_names

    def test_keeps_all_tools_when_both_enabled(self):
        """Should keep appropriate tools when both Vector Search and NL2SQL enabled."""
        tools = [
            self._make_tool("optimizer_vs-retriever"),
            self._make_tool("optimizer_vs-grade"),
            self._make_tool("sqlcl_query"),
            self._make_tool("other_tool"),
        ]

        result = utils_chat._filter_tools_by_enabled(tools, ["Vector Search", "NL2SQL"])

        result_names = [t.name for t in result]
        assert "optimizer_vs-retriever" in result_names
        assert "optimizer_vs-grade" not in result_names  # Internal tool filtered
        assert "sqlcl_query" in result_names
        assert "other_tool" in result_names

    def test_returns_empty_when_no_tools_enabled(self):
        """Should filter all specialized tools when nothing enabled."""
        tools = [
            self._make_tool("optimizer_vs-retriever"),
            self._make_tool("sqlcl_query"),
            self._make_tool("other_tool"),
        ]

        result = utils_chat._filter_tools_by_enabled(tools, [])

        result_names = [t.name for t in result]
        assert "optimizer_vs-retriever" not in result_names
        assert "sqlcl_query" not in result_names
        assert "other_tool" in result_names


#############################################################################
# Tests for completion_generator
#############################################################################
class TestCompletionGenerator:
    """Tests for the completion_generator function."""

    @pytest.fixture
    def completion_mocks(self):
        """Fixture providing all mocks needed for completion_generator tests."""
        with (
            patch("server.api.utils.chat.utils_settings.get_client") as mock_get_client,
            patch("server.api.utils.chat.utils_oci.get") as mock_oci_get,
            patch("server.api.utils.chat.utils_models.get_litellm_config") as mock_get_config,
            patch("server.api.utils.chat.utils_mcp.get_client") as mock_get_mcp,
            patch("server.api.utils.chat.MultiServerMCPClient") as mock_mcp_client_class,
            patch("server.api.utils.chat.graph.main") as mock_graph_main,
            patch("server.api.utils.chat._get_system_prompt") as mock_get_prompt,
        ):
            yield CompletionMocks(
                get_client=mock_get_client,
                oci_get=mock_oci_get,
                get_config=mock_get_config,
                get_mcp=mock_get_mcp,
                mcp_client_class=mock_mcp_client_class,
                graph_main=mock_graph_main,
                get_prompt=mock_get_prompt,
            )

    @pytest.mark.asyncio
    async def test_completion_generator_completions_mode(
        self, completion_mocks, make_settings, make_chat_request, make_oci_config
    ):
        """completion_generator should yield final response in completions mode."""
        mocks = completion_mocks
        mocks.get_client.return_value = make_settings()
        mocks.oci_get.return_value = make_oci_config()
        mocks.get_config.return_value = {"model": "gpt-4o-mini"}
        mocks.get_prompt.return_value = "System prompt"
        mocks.get_mcp.return_value = {"mcpServers": {"optimizer": {}}}

        # Setup MCP client mock
        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = AsyncMock(return_value=[])
        mocks.mcp_client_class.return_value = mock_mcp_instance

        # Setup graph mock
        mock_agent = MagicMock()

        async def mock_astream(**_kwargs):
            yield {"completion": {"choices": [{"message": {"content": "Hello!"}}]}}

        mock_agent.astream = mock_astream
        mocks.graph_main.return_value = mock_agent

        request = make_chat_request(content="Hi")
        results = []
        async for output in utils_chat.completion_generator("test_client", request, "completions"):
            results.append(output)

        assert len(results) == 1
        assert results[0]["choices"][0]["message"]["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_completion_generator_streams_mode(
        self, completion_mocks, make_settings, make_chat_request, make_oci_config
    ):
        """completion_generator should yield stream chunks in streams mode."""
        mocks = completion_mocks
        mocks.get_client.return_value = make_settings()
        mocks.oci_get.return_value = make_oci_config()
        mocks.get_config.return_value = {"model": "gpt-4o-mini"}
        mocks.get_prompt.return_value = "System prompt"
        mocks.get_mcp.return_value = {"mcpServers": {"optimizer": {}}}

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = AsyncMock(return_value=[])
        mocks.mcp_client_class.return_value = mock_mcp_instance

        mock_agent = MagicMock()

        async def mock_astream(**_kwargs):
            yield {"stream": "Hello"}
            yield {"stream": " World"}
            yield {"completion": {"choices": []}}

        mock_agent.astream = mock_astream
        mocks.graph_main.return_value = mock_agent

        request = make_chat_request(content="Hi")
        results = []
        async for output in utils_chat.completion_generator("test_client", request, "streams"):
            results.append(output)

        # Should have 3 outputs: 2 stream chunks + stream_finished marker
        assert len(results) == 3
        assert results[0] == b"Hello"
        assert results[1] == b" World"
        assert results[2] == utils_chat.STREAM_FINISHED_MARKER

    @pytest.mark.asyncio
    async def test_completion_generator_uses_request_model(
        self, completion_mocks, make_settings, make_oci_config
    ):
        """completion_generator should use model from request if provided."""
        mocks = completion_mocks
        mocks.get_client.return_value = make_settings()
        mocks.oci_get.return_value = make_oci_config()
        mocks.get_config.return_value = {"model": "claude-3"}
        mocks.get_prompt.return_value = "System prompt"
        mocks.get_mcp.return_value = {"mcpServers": {"optimizer": {}}}

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = AsyncMock(return_value=[])
        mocks.mcp_client_class.return_value = mock_mcp_instance

        mock_agent = MagicMock()

        async def mock_astream(**_kwargs):
            yield {"completion": {}}

        mock_agent.astream = mock_astream
        mocks.graph_main.return_value = mock_agent

        request = ChatRequest(messages=[{"role": "user", "content": "Hi"}], model="claude-3")
        async for _ in utils_chat.completion_generator("test_client", request, "completions"):
            pass

        # get_litellm_config should be called with the request model
        call_args = mocks.get_config.call_args[0]
        assert call_args[0]["model"] == "claude-3"

    @pytest.mark.asyncio
    async def test_completion_generator_uses_settings_model_when_not_in_request(
        self, completion_mocks, make_settings, make_chat_request, make_oci_config, make_ll_settings
    ):
        """completion_generator should use model from settings when not in request."""
        mocks = completion_mocks
        settings = make_settings(ll_model=make_ll_settings(model="gpt-4-turbo"))
        mocks.get_client.return_value = settings
        mocks.oci_get.return_value = make_oci_config()
        mocks.get_config.return_value = {"model": "gpt-4-turbo"}
        mocks.get_prompt.return_value = "System prompt"
        mocks.get_mcp.return_value = {"mcpServers": {"optimizer": {}}}

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = AsyncMock(return_value=[])
        mocks.mcp_client_class.return_value = mock_mcp_instance

        mock_agent = MagicMock()

        async def mock_astream(**_kwargs):
            yield {"completion": {}}

        mock_agent.astream = mock_astream
        mocks.graph_main.return_value = mock_agent

        request = make_chat_request(content="Hi")  # No model specified
        async for _ in utils_chat.completion_generator("test_client", request, "completions"):
            pass

        # get_litellm_config should be called with settings model
        call_args = mocks.get_config.call_args[0]
        assert call_args[0]["model"] == "gpt-4-turbo"

    @pytest.mark.asyncio
    async def test_completion_generator_passes_correct_config(
        self, completion_mocks, make_settings, make_chat_request, make_oci_config
    ):
        """completion_generator should pass correct config to graph."""
        mocks = completion_mocks
        settings = make_settings()
        mocks.get_client.return_value = settings
        mocks.oci_get.return_value = make_oci_config()
        mocks.get_config.return_value = {"model": "gpt-4o-mini"}
        mocks.get_prompt.return_value = "System prompt"
        mocks.get_mcp.return_value = {"mcpServers": {"optimizer": {}}}

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = AsyncMock(return_value=[])
        mocks.mcp_client_class.return_value = mock_mcp_instance

        captured_kwargs = {}
        mock_agent = MagicMock()

        async def mock_astream(**kwargs):
            captured_kwargs.update(kwargs)
            yield {"completion": {}}

        mock_agent.astream = mock_astream
        mocks.graph_main.return_value = mock_agent

        request = make_chat_request(content="Test message")
        async for _ in utils_chat.completion_generator("test_client", request, "completions"):
            pass

        assert captured_kwargs["stream_mode"] == "custom"
        assert captured_kwargs["config"]["configurable"]["thread_id"] == "test_client"
        assert captured_kwargs["config"]["recursion_limit"] == utils_chat.GRAPH_RECURSION_LIMIT
        assert "sys_prompt" in captured_kwargs["config"]["metadata"]

    @pytest.mark.asyncio
    async def test_completion_generator_handles_graph_exception_streams(
        self, completion_mocks, make_settings, make_chat_request, make_oci_config
    ):
        """completion_generator should handle exceptions in streams mode."""
        mocks = completion_mocks
        mocks.get_client.return_value = make_settings()
        mocks.oci_get.return_value = make_oci_config()
        mocks.get_config.return_value = {"model": "gpt-4o-mini"}
        mocks.get_prompt.return_value = "System prompt"
        mocks.get_mcp.return_value = {"mcpServers": {"optimizer": {}}}

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = AsyncMock(return_value=[])
        mocks.mcp_client_class.return_value = mock_mcp_instance

        mock_agent = MagicMock()

        async def mock_astream(**_kwargs):
            raise RuntimeError("Graph execution failed")
            yield  # Make it a generator  # pylint: disable=unreachable

        mock_agent.astream = mock_astream
        mocks.graph_main.return_value = mock_agent

        request = make_chat_request(content="Hi")
        results = []
        async for output in utils_chat.completion_generator("test_client", request, "streams"):
            results.append(output)

        # Should yield error message + stream finished marker
        assert len(results) == 2
        assert b"Graph execution failed" in results[0]
        assert results[1] == utils_chat.STREAM_FINISHED_MARKER

    @pytest.mark.asyncio
    async def test_completion_generator_handles_graph_exception_completions(
        self, completion_mocks, make_settings, make_chat_request, make_oci_config
    ):
        """completion_generator should handle exceptions in completions mode."""
        mocks = completion_mocks
        mocks.get_client.return_value = make_settings()
        mocks.oci_get.return_value = make_oci_config()
        mocks.get_config.return_value = {"model": "gpt-4o-mini"}
        mocks.get_prompt.return_value = "System prompt"
        mocks.get_mcp.return_value = {"mcpServers": {"optimizer": {}}}

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = AsyncMock(return_value=[])
        mocks.mcp_client_class.return_value = mock_mcp_instance

        mock_agent = MagicMock()

        async def mock_astream(**_kwargs):
            raise RuntimeError("Graph execution failed")
            yield  # Make it a generator  # pylint: disable=unreachable

        mock_agent.astream = mock_astream
        mocks.graph_main.return_value = mock_agent

        request = make_chat_request(content="Hi")
        results = []
        async for output in utils_chat.completion_generator("test_client", request, "completions"):
            results.append(output)

        # Should yield error response dict
        assert len(results) == 1
        assert "choices" in results[0]
        assert "Graph execution failed" in results[0]["choices"][0]["message"]["content"]

    @pytest.mark.asyncio
    @patch("server.api.utils.chat._filter_tools_by_enabled")
    @patch("server.api.utils.chat.convert_to_openai_function")
    async def test_completion_generator_filters_tools(
        self,
        mock_convert,
        mock_filter_tools,
        completion_mocks,
        make_settings,
        make_chat_request,
        make_oci_config,
    ):
        """completion_generator should filter tools based on enabled settings."""
        mocks = completion_mocks
        settings = make_settings()
        settings.tools_enabled = ["Vector Search"]
        mocks.get_client.return_value = settings
        mocks.oci_get.return_value = make_oci_config()
        mocks.get_config.return_value = {"model": "gpt-4o-mini"}
        mocks.get_prompt.return_value = "System prompt"
        mocks.get_mcp.return_value = {"mcpServers": {"optimizer": {}}}
        mock_convert.return_value = {"name": "optimizer_vs-retriever", "parameters": {}}

        mock_tool = MagicMock()
        mock_tool.name = "optimizer_vs-retriever"

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = AsyncMock(return_value=[mock_tool])
        mocks.mcp_client_class.return_value = mock_mcp_instance

        mock_filter_tools.return_value = [mock_tool]

        mock_agent = MagicMock()

        async def mock_astream(**_kwargs):
            yield {"completion": {}}

        mock_agent.astream = mock_astream
        mocks.graph_main.return_value = mock_agent

        request = make_chat_request(content="Hi")
        async for _ in utils_chat.completion_generator("test_client", request, "completions"):
            pass

        # Verify filter was called with tools and enabled list
        mock_filter_tools.assert_called_once_with([mock_tool], ["Vector Search"])
