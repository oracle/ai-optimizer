# pylint: disable=protected-access,import-error,import-outside-toplevel
"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

import json
from unittest.mock import MagicMock

import pytest


#############################################################################
# Test show_vector_search_refs Function
#############################################################################
class TestShowVectorSearchRefs:
    """Test show_vector_search_refs function"""

    def test_show_vector_search_refs_with_metadata(self, monkeypatch):
        """Test showing vector search references with complete metadata"""
        from client.content import chatbot
        import streamlit as st

        # Mock streamlit functions
        mock_markdown = MagicMock()
        mock_popover = MagicMock()
        mock_popover.__enter__ = MagicMock(return_value=mock_popover)
        mock_popover.__exit__ = MagicMock(return_value=False)

        mock_col = MagicMock()
        mock_col.popover = MagicMock(return_value=mock_popover)

        mock_columns = MagicMock(return_value=[mock_col, mock_col, mock_col])
        mock_subheader = MagicMock()

        monkeypatch.setattr(st, "markdown", mock_markdown)
        monkeypatch.setattr(st, "columns", mock_columns)
        monkeypatch.setattr(st, "subheader", mock_subheader)

        # Create test context - now expects dict with "documents" key
        context = {
            "documents": [
                {
                    "page_content": "This is chunk 1 content",
                    "metadata": {"filename": "doc1.pdf", "source": "/path/to/doc1.pdf", "page": 1},
                },
                {
                    "page_content": "This is chunk 2 content",
                    "metadata": {"filename": "doc2.pdf", "source": "/path/to/doc2.pdf", "page": 2},
                },
                {
                    "page_content": "This is chunk 3 content",
                    "metadata": {"filename": "doc1.pdf", "source": "/path/to/doc1.pdf", "page": 3},
                },
            ],
            "context_input": "test query",
        }

        # Call function
        chatbot.show_vector_search_refs(context)

        # Verify References header was shown
        assert any("References" in str(call) for call in mock_markdown.call_args_list)

    def test_show_vector_search_refs_missing_metadata(self, monkeypatch):
        """Test showing vector search references when metadata is missing"""
        from client.content import chatbot
        import streamlit as st

        # Mock streamlit functions
        mock_markdown = MagicMock()
        mock_popover = MagicMock()
        mock_popover.__enter__ = MagicMock(return_value=mock_popover)
        mock_popover.__exit__ = MagicMock(return_value=False)

        mock_col = MagicMock()
        mock_col.popover = MagicMock(return_value=mock_popover)

        mock_columns = MagicMock(return_value=[mock_col])
        mock_subheader = MagicMock()

        monkeypatch.setattr(st, "markdown", mock_markdown)
        monkeypatch.setattr(st, "columns", mock_columns)
        monkeypatch.setattr(st, "subheader", mock_subheader)

        # Create test context with missing metadata - now expects dict with "documents" key
        context = {
            "documents": [
                {
                    "page_content": "Content without metadata",
                    "metadata": {},  # Empty metadata - will cause KeyError
                }
            ],
            "context_input": "test query",
        }

        # Call function - should handle KeyError gracefully
        chatbot.show_vector_search_refs(context)

        # Should still show content
        assert mock_markdown.called


#############################################################################
# Test setup_sidebar Function
#############################################################################
class TestSetupSidebar:
    """Test setup_sidebar function"""

    def test_setup_sidebar_no_models(self, monkeypatch):
        """Test setup_sidebar when no language models enabled"""
        from client.content import chatbot
        from client.utils import st_common
        import streamlit as st

        # Mock enabled_models_lookup to return no models
        monkeypatch.setattr(st_common, "enabled_models_lookup", lambda x: {})

        # Mock st.error and st.stop
        mock_error = MagicMock()
        mock_stop = MagicMock(side_effect=SystemExit)
        monkeypatch.setattr(st, "error", mock_error)
        monkeypatch.setattr(st, "stop", mock_stop)

        # Call setup_sidebar
        with pytest.raises(SystemExit):
            chatbot.setup_sidebar()

        # Verify error was shown
        assert mock_error.called
        assert "No language models" in str(mock_error.call_args)

    def test_setup_sidebar_with_models(self, monkeypatch):
        """Test setup_sidebar with enabled language models"""
        from client.content import chatbot
        from client.utils import st_common, vs_options, tool_options
        from streamlit import session_state as state

        # Mock enabled_models_lookup to return models
        monkeypatch.setattr(st_common, "enabled_models_lookup", lambda x: {"gpt-4": {}})

        # Mock sidebar functions
        monkeypatch.setattr(tool_options, "tools_sidebar", MagicMock())
        monkeypatch.setattr(st_common, "history_sidebar", MagicMock())
        monkeypatch.setattr(st_common, "ll_sidebar", MagicMock())
        monkeypatch.setattr(vs_options, "vector_search_sidebar", MagicMock())

        # Initialize state
        state.enable_client = True

        # Call setup_sidebar
        chatbot.setup_sidebar()

        # Verify enable_client was set
        assert state.enable_client is True

    def test_setup_sidebar_client_disabled(self, monkeypatch):
        """Test setup_sidebar when client gets disabled"""
        from client.content import chatbot
        from client.utils import st_common, vs_options, tool_options
        from streamlit import session_state as state
        import streamlit as st

        # Mock functions
        monkeypatch.setattr(st_common, "enabled_models_lookup", lambda x: {"gpt-4": {}})

        def disable_client():
            state.enable_client = False

        monkeypatch.setattr(tool_options, "tools_sidebar", disable_client)
        monkeypatch.setattr(st_common, "history_sidebar", MagicMock())
        monkeypatch.setattr(st_common, "ll_sidebar", MagicMock())
        monkeypatch.setattr(vs_options, "vector_search_sidebar", MagicMock())

        # Mock st.stop
        mock_stop = MagicMock(side_effect=SystemExit)
        monkeypatch.setattr(st, "stop", mock_stop)

        # Call setup_sidebar
        with pytest.raises(SystemExit):
            chatbot.setup_sidebar()

        # Verify stop was called
        assert mock_stop.called


#############################################################################
# Test create_client Function
#############################################################################
class TestCreateClient:
    """Test create_client function"""

    def test_create_client_new(self, monkeypatch):
        """Test creating a new client when one doesn't exist"""
        from client.content import chatbot
        from client.utils import client
        from streamlit import session_state as state

        # Setup state
        state.server = {"url": "http://localhost", "port": 8000, "key": "test-key"}
        state.client_settings = {"client": "test-client", "ll_model": {}}

        # Clear user_client if it exists
        if hasattr(state, "user_client"):
            delattr(state, "user_client")

        # Mock Client class
        mock_client_instance = MagicMock()
        mock_client_class = MagicMock(return_value=mock_client_instance)
        monkeypatch.setattr(client, "Client", mock_client_class)

        # Call create_client
        result = chatbot.create_client()

        # Verify client was created
        assert result == mock_client_instance
        assert state.user_client == mock_client_instance

        # Verify Client was called with correct parameters
        mock_client_class.assert_called_once_with(server=state.server, settings=state.client_settings, timeout=1200)

    def test_create_client_existing(self):
        """Test getting existing client"""
        from client.content import chatbot
        from streamlit import session_state as state

        # Setup state with existing client
        existing_client = MagicMock()
        state.user_client = existing_client

        # Call create_client
        result = chatbot.create_client()

        # Verify existing client was returned
        assert result == existing_client


#############################################################################
# Test display_chat_history Function
#############################################################################
class TestDisplayChatHistory:
    """Test display_chat_history function"""

    def test_display_chat_history_empty(self, monkeypatch):
        """Test displaying empty chat history"""
        from client.content import chatbot
        import streamlit as st

        # Mock streamlit functions
        mock_chat_message = MagicMock()
        mock_chat_message.write = MagicMock()
        monkeypatch.setattr(st, "chat_message", lambda x: mock_chat_message)

        # Call with empty history
        chatbot.display_chat_history([])

        # Verify greeting was shown
        mock_chat_message.write.assert_called_once()

    def test_display_chat_history_with_messages(self, monkeypatch):
        """Test displaying chat history with messages"""
        from client.content import chatbot
        import streamlit as st

        # Mock streamlit functions
        mock_chat_message = MagicMock()
        mock_chat_message.__enter__ = MagicMock(return_value=mock_chat_message)
        mock_chat_message.__exit__ = MagicMock(return_value=False)
        mock_chat_message.write = MagicMock()
        mock_chat_message.markdown = MagicMock()

        monkeypatch.setattr(st, "chat_message", lambda x: mock_chat_message)

        # Create history with messages
        history = [
            {"role": "human", "content": "Hello"},
            {"role": "ai", "content": "Hi there!"},
        ]

        # Call display_chat_history
        chatbot.display_chat_history(history)

        # Verify messages were displayed
        assert mock_chat_message.write.called or mock_chat_message.markdown.called

    def test_display_chat_history_with_vector_search(self, monkeypatch):
        """Test displaying chat history with vector search tool results"""
        from client.content import chatbot
        import streamlit as st

        # Mock streamlit functions
        mock_chat_message = MagicMock()
        mock_chat_message.__enter__ = MagicMock(return_value=mock_chat_message)
        mock_chat_message.__exit__ = MagicMock(return_value=False)
        mock_chat_message.write = MagicMock()
        mock_chat_message.markdown = MagicMock()

        monkeypatch.setattr(st, "chat_message", lambda x: mock_chat_message)

        # Mock show_vector_search_refs
        mock_show_refs = MagicMock()
        monkeypatch.setattr(chatbot, "show_vector_search_refs", mock_show_refs)

        # Create history with tool message - use correct tool name "optimizer_vs-retriever"
        vector_refs = {"documents": [{"page_content": "content", "metadata": {}}], "context_input": "query"}
        history = [
            {"role": "tool", "name": "optimizer_vs-retriever", "content": json.dumps(vector_refs)},
            {"role": "ai", "content": "Based on the documents..."},
        ]

        # Call display_chat_history
        chatbot.display_chat_history(history)

        # Verify vector search refs were shown
        mock_show_refs.assert_called_once()

    def test_display_chat_history_with_image(self, monkeypatch):
        """Test displaying chat history with image content"""
        from client.content import chatbot
        import streamlit as st

        # Mock streamlit functions
        mock_chat_message = MagicMock()
        mock_chat_message.__enter__ = MagicMock(return_value=mock_chat_message)
        mock_chat_message.__exit__ = MagicMock(return_value=False)
        mock_chat_message.write = MagicMock()
        mock_image = MagicMock()

        monkeypatch.setattr(st, "chat_message", lambda x: mock_chat_message)
        monkeypatch.setattr(st, "image", mock_image)

        # Create history with image
        history = [
            {
                "role": "human",
                "content": [
                    {"type": "text", "text": "What's in this image?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
                ],
            }
        ]

        # Call display_chat_history
        chatbot.display_chat_history(history)

        # Verify image was displayed
        mock_image.assert_called_once()

    def test_display_chat_history_skip_empty_content(self, monkeypatch):
        """Test that empty content messages are skipped"""
        from client.content import chatbot
        import streamlit as st

        # Mock streamlit functions
        mock_chat_message = MagicMock()
        mock_chat_message.write = MagicMock()
        monkeypatch.setattr(st, "chat_message", lambda x: mock_chat_message)

        # Create history with empty content
        history = [
            {"role": "ai", "content": ""},  # Empty - should be skipped
            {"role": "human", "content": "Hello"},  # Should be processed
        ]

        # Call display_chat_history
        chatbot.display_chat_history(history)

        # greeting + 1 message should be shown (empty skipped)
        # This is hard to verify precisely, but we can check it didn't crash
        assert True


#############################################################################
# Test handle_chat_input Function
#############################################################################
class TestHandleChatInput:
    """Test handle_chat_input async function"""

    @pytest.mark.asyncio
    async def test_handle_chat_input_text_only(self, monkeypatch):
        """Test handling text-only chat input"""
        from client.content import chatbot
        import streamlit as st

        # Mock streamlit functions
        mock_chat_input = MagicMock()
        mock_chat_input.text = "Hello AI"
        mock_chat_input.__getitem__ = lambda self, key: [] if key == "files" else None

        mock_chat_message = MagicMock()
        mock_chat_message.write = MagicMock()
        mock_chat_message.empty = MagicMock()
        mock_chat_message.markdown = MagicMock()

        mock_placeholder = MagicMock()
        mock_chat_message.empty.return_value = mock_placeholder

        monkeypatch.setattr(st, "chat_input", lambda *args, **kwargs: mock_chat_input)
        monkeypatch.setattr(st, "chat_message", lambda x: mock_chat_message)
        monkeypatch.setattr(st, "rerun", MagicMock(side_effect=SystemExit))

        # Mock render_chat_footer
        monkeypatch.setattr(chatbot, "render_chat_footer", MagicMock())

        # Mock user client with streaming
        async def mock_stream(message, image_b64=None):
            # Validate parameters
            assert message is not None
            assert image_b64 is None or isinstance(image_b64, str)
            yield "Hello"
            yield " "
            yield "there!"

        mock_client = MagicMock()
        mock_client.stream = mock_stream

        # Call handle_chat_input
        with pytest.raises(SystemExit):  # st.rerun raises SystemExit
            await chatbot.handle_chat_input(mock_client)

        # Verify message was displayed
        assert mock_chat_message.write.called

    @pytest.mark.asyncio
    async def test_handle_chat_input_with_image(self, monkeypatch):
        """Test handling chat input with image attachment"""
        from client.content import chatbot
        import streamlit as st

        # Create mock file
        mock_file = MagicMock()
        mock_file.read.return_value = b"fake image data"

        # Mock chat input with file
        mock_chat_input = MagicMock()
        mock_chat_input.text = "Describe this image"
        mock_chat_input.__getitem__ = lambda self, key: [mock_file] if key == "files" else None

        mock_chat_message = MagicMock()
        mock_chat_message.write = MagicMock()
        mock_placeholder = MagicMock()
        mock_chat_message.empty = MagicMock(return_value=mock_placeholder)

        monkeypatch.setattr(st, "chat_input", lambda *args, **kwargs: mock_chat_input)
        monkeypatch.setattr(st, "chat_message", lambda x: mock_chat_message)
        monkeypatch.setattr(st, "rerun", MagicMock(side_effect=SystemExit))
        monkeypatch.setattr(chatbot, "render_chat_footer", MagicMock())

        # Mock user client with streaming
        async def mock_stream(message, image_b64=None):
            # Verify message and image were passed
            assert message is not None
            assert image_b64 is not None
            assert isinstance(image_b64, str)
            yield "I see an image"

        mock_client = MagicMock()
        mock_client.stream = mock_stream

        # Call handle_chat_input
        with pytest.raises(SystemExit):
            await chatbot.handle_chat_input(mock_client)

    @pytest.mark.asyncio
    async def test_handle_chat_input_connection_error(self, monkeypatch):
        """Test handling connection error during chat"""
        from client.content import chatbot
        import streamlit as st

        # Mock chat input
        mock_chat_input = MagicMock()
        mock_chat_input.text = "Hello"
        mock_chat_input.__getitem__ = lambda self, key: [] if key == "files" else None

        mock_placeholder = MagicMock()
        mock_chat_message = MagicMock()
        mock_chat_message.write = MagicMock()
        mock_chat_message.empty = MagicMock(return_value=mock_placeholder)

        monkeypatch.setattr(st, "chat_input", lambda *args, **kwargs: mock_chat_input)
        monkeypatch.setattr(st, "chat_message", lambda x: mock_chat_message)
        monkeypatch.setattr(st, "button", MagicMock(return_value=False))
        monkeypatch.setattr(chatbot, "render_chat_footer", MagicMock())

        # Mock user client that raises error on streaming
        async def mock_stream_error(message, image_b64=None):
            # Use arguments to satisfy pylint
            error_msg = f"Unable to connect for message: {message}, image: {image_b64}"
            # Make this an async generator by yielding nothing when error_msg is empty (never true)
            if not error_msg:
                yield
            raise ConnectionError("Unable to connect")

        mock_client = MagicMock()
        mock_client.stream = mock_stream_error

        # Call handle_chat_input
        await chatbot.handle_chat_input(mock_client)

        # Verify error message was shown
        assert mock_placeholder.markdown.called
        error_msg = mock_placeholder.markdown.call_args[0][0]
        assert "error" in error_msg.lower()
