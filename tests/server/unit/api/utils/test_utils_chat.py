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
    SelectAISettings,
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
            vector_search=VectorSearchSettings(enabled=False),
            selectai=SelectAISettings(enabled=False),
            oci=OciSettings(auth_profile="DEFAULT"),
        )

    @patch("server.api.core.settings.get_client_settings")
    @patch("server.api.utils.oci.get")
    @patch("server.api.utils.models.get_litellm_config")
    @patch("server.agents.chatbot.chatbot_graph.astream")
    @pytest.mark.asyncio
    async def test_completion_generator_success(
        self, mock_astream, mock_get_litellm_config, mock_get_oci, mock_get_client_settings
    ):
        """Test successful completion generation"""
        # Setup mocks
        mock_get_client_settings.return_value = self.sample_client_settings
        mock_get_oci.return_value = MagicMock()
        mock_get_litellm_config.return_value = {"model": "gpt-4", "temperature": 0.7}

        # Mock the async generator - this should only yield the final completion for "completions" mode
        async def mock_generator():
            yield {"stream": "Hello"}
            yield {"stream": " there"}
            yield {"completion": "Hello there"}

        mock_astream.return_value = mock_generator()

        # Test the function
        results = []
        async for result in chat.completion_generator("test_client", self.sample_request, "completions"):
            results.append(result)

        # Verify results - for "completions" mode, we get stream chunks + final completion
        assert len(results) == 3
        assert results[0] == b"Hello"  # Stream chunks are encoded as bytes
        assert results[1] == b" there"
        assert results[2] == "Hello there"  # Final completion is a string
        mock_get_client_settings.assert_called_once_with("test_client")
        mock_get_oci.assert_called_once_with(client="test_client")

    @patch("server.api.core.settings.get_client_settings")
    @patch("server.api.utils.oci.get")
    @patch("server.api.utils.models.get_litellm_config")
    @patch("server.agents.chatbot.chatbot_graph.astream")
    @pytest.mark.asyncio
    async def test_completion_generator_streaming(
        self, mock_astream, mock_get_litellm_config, mock_get_oci, mock_get_client_settings
    ):
        """Test streaming completion generation"""
        # Setup mocks
        mock_get_client_settings.return_value = self.sample_client_settings
        mock_get_oci.return_value = MagicMock()
        mock_get_litellm_config.return_value = {"model": "gpt-4", "temperature": 0.7}

        # Mock the async generator
        async def mock_generator():
            yield {"stream": "Hello"}
            yield {"stream": " there"}
            yield {"completion": "Hello there"}

        mock_astream.return_value = mock_generator()

        # Test the function
        results = []
        async for result in chat.completion_generator("test_client", self.sample_request, "streams"):
            results.append(result)

        # Verify results - should include encoded stream chunks and finish marker
        assert len(results) == 3
        assert results[0] == b"Hello"
        assert results[1] == b" there"
        assert results[2] == "[stream_finished]"

    @patch("server.api.core.settings.get_client_settings")
    @patch("server.api.utils.oci.get")
    @patch("server.api.utils.models.get_litellm_config")
    @patch("server.api.utils.databases.get_client_database")
    @patch("server.api.utils.models.get_client_embed")
    @patch("server.agents.chatbot.chatbot_graph.astream")
    @pytest.mark.asyncio
    async def test_completion_generator_with_vector_search(
        self,
        mock_astream,
        mock_get_client_embed,
        mock_get_client_database,
        mock_get_litellm_config,
        mock_get_oci,
        mock_get_client_settings,
    ):
        """Test completion generation with vector search enabled"""
        # Setup settings with vector search enabled
        vector_search_settings = self.sample_client_settings.model_copy()
        vector_search_settings.vector_search.enabled = True

        # Setup mocks
        mock_get_client_settings.return_value = vector_search_settings
        mock_get_oci.return_value = MagicMock()
        mock_get_litellm_config.return_value = {"model": "gpt-4", "temperature": 0.7}

        mock_db = MagicMock()
        mock_db.connection = MagicMock()
        mock_get_client_database.return_value = mock_db
        mock_get_client_embed.return_value = MagicMock()

        # Mock the async generator
        async def mock_generator():
            yield {"completion": "Response with vector search"}

        mock_astream.return_value = mock_generator()

        # Test the function
        results = []
        async for result in chat.completion_generator("test_client", self.sample_request, "completions"):
            results.append(result)

        # Verify vector search setup
        mock_get_client_database.assert_called_once_with("test_client", False)
        mock_get_client_embed.assert_called_once()
        assert len(results) == 1

    @patch("server.api.core.settings.get_client_settings")
    @patch("server.api.utils.oci.get")
    @patch("server.api.utils.models.get_litellm_config")
    @patch("server.api.utils.databases.get_client_database")
    @patch("server.api.utils.selectai.set_profile")
    @patch("server.agents.chatbot.chatbot_graph.astream")
    @pytest.mark.asyncio
    async def test_completion_generator_with_selectai(
        self,
        mock_astream,
        mock_set_profile,
        mock_get_client_database,
        mock_get_litellm_config,
        mock_get_oci,
        mock_get_client_settings,
    ):
        """Test completion generation with SelectAI enabled"""
        # Setup settings with SelectAI enabled
        selectai_settings = self.sample_client_settings.model_copy()
        selectai_settings.selectai.enabled = True
        selectai_settings.selectai.profile = "TEST_PROFILE"

        # Setup mocks
        mock_get_client_settings.return_value = selectai_settings
        mock_get_oci.return_value = MagicMock()
        mock_get_litellm_config.return_value = {"model": "gpt-4", "temperature": 0.7}

        mock_db = MagicMock()
        mock_db.connection = MagicMock()
        mock_get_client_database.return_value = mock_db

        # Mock the async generator
        async def mock_generator():
            yield {"completion": "Response with SelectAI"}

        mock_astream.return_value = mock_generator()

        # Test the function
        results = []
        async for result in chat.completion_generator("test_client", self.sample_request, "completions"):
            results.append(result)

        # Verify SelectAI setup
        mock_get_client_database.assert_called_once_with("test_client", False)
        # Should set profile parameters
        assert mock_set_profile.call_count == 2  # temperature and max_tokens
        assert len(results) == 1

    @patch("server.api.core.settings.get_client_settings")
    @patch("server.api.utils.oci.get")
    @patch("server.api.utils.models.get_litellm_config")
    @patch("server.agents.chatbot.chatbot_graph.astream")
    @pytest.mark.asyncio
    async def test_completion_generator_no_model_specified(
        self, mock_astream, mock_get_litellm_config, mock_get_oci, mock_get_client_settings
    ):
        """Test completion generation when no model is specified in request"""
        # Create request without model
        request_no_model = ChatRequest(messages=[self.sample_message], model=None)

        # Setup mocks
        mock_get_client_settings.return_value = self.sample_client_settings
        mock_get_oci.return_value = MagicMock()
        mock_get_litellm_config.return_value = {"model": "gpt-4", "temperature": 0.7}

        # Mock the async generator
        async def mock_generator():
            yield {"completion": "Response using default model"}

        mock_astream.return_value = mock_generator()

        # Test the function
        results = []
        async for result in chat.completion_generator("test_client", request_no_model, "completions"):
            results.append(result)

        # Should use model from client settings
        assert len(results) == 1

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(chat, "logger")
        assert chat.logger.name == "api.utils.chat"
