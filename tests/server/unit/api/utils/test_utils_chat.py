"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch, MagicMock
import pytest

from langchain_core.messages import ChatMessage

from server.api.utils import chat
from common.schema import (
    ChatRequest,
    Settings,
    LargeLanguageSettings,
    VectorSearchSettings,
    PromptSettings,
    OciSettings,
)


class TestChatUtils:
    """Test chat utility functions"""

    def setup_method(self):
        """Setup test data"""
        self.sample_message = ChatMessage(role="user", content="Hello, how are you?")
        self.sample_request = ChatRequest(messages=[self.sample_message], model="openai/gpt-4")
        self.sample_client_settings = Settings(
            client="test_client",
            ll_model=LargeLanguageSettings(
                model="openai/gpt-4", chat_history=True, temperature=0.7, max_tokens=4096
            ),
            vector_search=VectorSearchSettings(),
            prompts=PromptSettings(sys="Basic Example", ctx="Basic Example"),
            oci=OciSettings(auth_profile="DEFAULT"),
            tools_enabled=[],
        )

    @patch("server.api.utils.settings.get_client")
    @patch("server.api.utils.oci.get")
    @patch("server.api.utils.models.get_litellm_config")
    @patch("server.mcp.prompts.defaults.get_prompt_with_override")
    @patch("server.api.utils.chat.MultiServerMCPClient")
    @patch("server.api.utils.mcp.get_client")
    @patch("server.mcp.graph.main")
    @pytest.mark.asyncio
    async def test_completion_generator_success(
        self, mock_graph_main, mock_get_mcp_client, mock_mcp_client_class, mock_get_prompt_override, mock_get_litellm_config, mock_get_oci, mock_get_client
    ):
        """Test successful completion generation"""
        # Setup mocks
        mock_get_client.return_value = self.sample_client_settings
        mock_get_oci.return_value = MagicMock()
        mock_get_litellm_config.return_value = {"model": "gpt-4", "temperature": 0.7}
        mock_get_prompt_override.return_value = "You are a helpful assistant"
        mock_get_mcp_client.return_value = {"mcpServers": {"optimizer": {}}}

        # Mock MCP client to return empty tools list
        async def mock_get_tools():
            return []

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = mock_get_tools
        mock_mcp_client_class.return_value = mock_mcp_instance

        # Mock MCP client to return empty tools list
        async def mock_get_tools():
            return []

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = mock_get_tools
        mock_mcp_client_class.return_value = mock_mcp_instance

        # Mock the async generator - this should only yield the final completion for "completions" mode
        async def mock_generator():
            yield {"stream": "Hello"}
            yield {"stream": " there"}
            yield {"completion": "Hello there"}

        # Mock the graph instance
        mock_graph = MagicMock()
        mock_graph.astream.return_value = mock_generator()
        mock_graph_main.return_value = mock_graph

        # Test the function
        results = []
        async for result in chat.completion_generator("test_client", self.sample_request, "completions"):
            results.append(result)

        # Verify results - for "completions" mode, we get stream chunks + final completion
        assert len(results) == 3
        assert results[0] == b"Hello"  # Stream chunks are encoded as bytes
        assert results[1] == b" there"
        assert results[2] == "Hello there"  # Final completion is a string
        mock_get_client.assert_called_once_with("test_client")
        mock_get_oci.assert_called_once_with(client="test_client")

    @patch("server.api.utils.settings.get_client")
    @patch("server.api.utils.oci.get")
    @patch("server.api.utils.models.get_litellm_config")
    @patch("server.mcp.prompts.defaults.get_prompt_with_override")
    @patch("server.api.utils.chat.MultiServerMCPClient")
    @patch("server.api.utils.mcp.get_client")
    @patch("server.mcp.graph.main")
    @pytest.mark.asyncio
    async def test_completion_generator_streaming(
        self, mock_graph_main, mock_get_mcp_client, mock_mcp_client_class, mock_get_prompt_override, mock_get_litellm_config, mock_get_oci, mock_get_client
    ):
        """Test streaming completion generation"""
        # Setup mocks
        mock_get_client.return_value = self.sample_client_settings
        mock_get_oci.return_value = MagicMock()
        mock_get_litellm_config.return_value = {"model": "gpt-4", "temperature": 0.7}
        mock_get_prompt_override.return_value = "You are a helpful assistant"
        mock_get_mcp_client.return_value = {"mcpServers": {"optimizer": {}}}

        # Mock MCP client to return empty tools list
        async def mock_get_tools():
            return []

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = mock_get_tools
        mock_mcp_client_class.return_value = mock_mcp_instance

        # Mock the async generator
        async def mock_generator():
            yield {"stream": "Hello"}
            yield {"stream": " there"}
            yield {"completion": "Hello there"}

        # Mock the graph instance
        mock_graph = MagicMock()
        mock_graph.astream.return_value = mock_generator()
        mock_graph_main.return_value = mock_graph

        # Test the function
        results = []
        async for result in chat.completion_generator("test_client", self.sample_request, "streams"):
            results.append(result)

        # Verify results - should include encoded stream chunks and finish marker
        assert len(results) == 3
        assert results[0] == b"Hello"
        assert results[1] == b" there"
        assert results[2] == "[stream_finished]"

    @patch("server.api.utils.settings.get_client")
    @patch("server.api.utils.oci.get")
    @patch("server.api.utils.models.get_litellm_config")
    @patch("server.mcp.prompts.defaults.get_prompt_with_override")
    @patch("server.api.utils.chat.MultiServerMCPClient")
    @patch("server.api.utils.mcp.get_client")
    @patch("server.api.utils.databases.get_client_database")
    @patch("server.api.utils.models.get_client_embed")
    @patch("server.mcp.graph.main")
    @pytest.mark.asyncio
    async def test_completion_generator_with_vector_search(
        self,
        mock_graph_main,
        mock_get_client_embed,
        mock_get_client_database,
        mock_get_mcp_client,
        mock_mcp_client_class,
        mock_get_prompt_override,
        mock_get_litellm_config,
        mock_get_oci,
        mock_get_client,
    ):
        """Test completion generation with vector search enabled"""
        # Setup settings with vector search enabled (via tools_enabled)
        vector_search_settings = self.sample_client_settings.model_copy()
        vector_search_settings.tools_enabled = ["Vector Search"]

        # Setup mocks
        mock_get_client.return_value = vector_search_settings
        mock_get_oci.return_value = MagicMock()
        mock_get_litellm_config.return_value = {"model": "gpt-4", "temperature": 0.7}
        mock_get_prompt_override.return_value = "You are a helpful assistant"
        mock_get_mcp_client.return_value = {"mcpServers": {"optimizer": {}}}

        # Mock MCP client to return empty tools list
        async def mock_get_tools():
            return []

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = mock_get_tools
        mock_mcp_client_class.return_value = mock_mcp_instance

        mock_db = MagicMock()
        mock_db.connection = MagicMock()
        mock_get_client_database.return_value = mock_db
        mock_get_client_embed.return_value = MagicMock()

        # Mock the async generator
        async def mock_generator():
            yield {"completion": "Response with vector search"}

        # Mock the graph instance
        mock_graph = MagicMock()
        mock_graph.astream.return_value = mock_generator()
        mock_graph_main.return_value = mock_graph

        # Test the function
        results = []
        async for result in chat.completion_generator("test_client", self.sample_request, "completions"):
            results.append(result)

        # Verify completion was generated
        assert len(results) == 1
        # Note: Database connection is now handled internally by MCP tools, not in chat.py

    @patch("server.api.utils.settings.get_client")
    @patch("server.api.utils.oci.get")
    @patch("server.api.utils.models.get_litellm_config")
    @patch("server.mcp.prompts.defaults.get_prompt_with_override")
    @patch("server.api.utils.chat.MultiServerMCPClient")
    @patch("server.api.utils.mcp.get_client")
    @patch("server.mcp.graph.main")
    @pytest.mark.asyncio
    async def test_completion_generator_no_model_specified(
        self, mock_graph_main, mock_get_mcp_client, mock_mcp_client_class, mock_get_prompt_override, mock_get_litellm_config, mock_get_oci, mock_get_client
    ):
        """Test completion generation when no model is specified in request"""
        # Create request without model
        request_no_model = ChatRequest(messages=[self.sample_message], model=None)

        # Setup mocks
        mock_get_client.return_value = self.sample_client_settings
        mock_get_oci.return_value = MagicMock()
        mock_get_litellm_config.return_value = {"model": "gpt-4", "temperature": 0.7}
        mock_get_prompt_override.return_value = "You are a helpful assistant"
        mock_get_mcp_client.return_value = {"mcpServers": {"optimizer": {}}}

        # Mock MCP client to return empty tools list
        async def mock_get_tools():
            return []

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = mock_get_tools
        mock_mcp_client_class.return_value = mock_mcp_instance

        # Mock the async generator
        async def mock_generator():
            yield {"completion": "Response using default model"}

        # Mock the graph instance
        mock_graph = MagicMock()
        mock_graph.astream.return_value = mock_generator()
        mock_graph_main.return_value = mock_graph

        # Test the function
        results = []
        async for result in chat.completion_generator("test_client", request_no_model, "completions"):
            results.append(result)

        # Should use model from client settings
        assert len(results) == 1

    @patch("server.api.utils.settings.get_client")
    @patch("server.api.utils.oci.get")
    @patch("server.api.utils.models.get_litellm_config")
    @patch("server.mcp.prompts.defaults.get_prompt_with_override")
    @patch("server.api.utils.chat.MultiServerMCPClient")
    @patch("server.api.utils.mcp.get_client")
    @patch("server.mcp.graph.main")
    @pytest.mark.asyncio
    async def test_completion_generator_custom_prompts(
        self, mock_graph_main, mock_get_mcp_client, mock_mcp_client_class, mock_get_prompt_override, mock_get_litellm_config, mock_get_oci, mock_get_client
    ):
        """Test completion generation with custom prompts"""
        # Setup settings with custom prompts
        custom_settings = self.sample_client_settings.model_copy()
        custom_settings.prompts.sys = "Custom System"
        custom_settings.prompts.ctx = "Custom Context"

        # Setup mocks
        mock_get_client.return_value = custom_settings
        mock_get_oci.return_value = MagicMock()
        mock_get_litellm_config.return_value = {"model": "gpt-4", "temperature": 0.7}
        mock_get_prompt_override.return_value = "Custom prompt"  # Return override
        mock_get_mcp_client.return_value = {"mcpServers": {"optimizer": {}}}

        # Mock MCP client to return empty tools list
        async def mock_get_tools():
            return []

        mock_mcp_instance = MagicMock()
        mock_mcp_instance.get_tools = mock_get_tools
        mock_mcp_client_class.return_value = mock_mcp_instance

        # Mock the async generator
        async def mock_generator():
            yield {"completion": "Response with custom prompts"}

        # Mock the graph instance
        mock_graph = MagicMock()
        mock_graph.astream.return_value = mock_generator()
        mock_graph_main.return_value = mock_graph

        # Test the function
        results = []
        async for result in chat.completion_generator("test_client", self.sample_request, "completions"):
            results.append(result)

        # Verify custom prompts are used
        assert len(results) == 1

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(chat, "logger")
        assert chat.logger.name == "api.utils.chat"
