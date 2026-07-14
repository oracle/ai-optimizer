"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for client.app.content.chatbot (functions only — not module-level page code)
"""
# spell-checker: disable

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from client.tests.conftest import AttrDict, make_http_error

MODULE = "client.app.content.chatbot"
HELPERS = "client.app.core.helpers"
SIDEBAR = "client.app.core.sidebar"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_state(extra=None):
    data = AttrDict(
        {
            "settings": {
                "database_configs": [],
                "model_configs": [],
                "client_settings": {},
            },
            "optimizer_client": "test-client",
        }
    )
    if extra:
        data.update(extra)
    return data


# ---------------------------------------------------------------------------
# Module import helper — chatbot.py has module-level sidebar/st calls
# ---------------------------------------------------------------------------
def _ensure_chatbot_loaded():
    """Import chatbot module once with module-level code neutralized.

    chatbot.py has module-level calls (sidebar, st.chat_input, etc.) and
    references ``state`` (streamlit session_state via ``from streamlit
    import session_state as state``). We must mock the entire ``streamlit``
    module so the ``from streamlit import session_state`` binding picks up
    our mock state.
    """
    if "client.app.content.chatbot" in sys.modules:
        return

    import streamlit as real_st

    state = _make_state()
    # Patch streamlit.session_state so `from streamlit import session_state as state` works
    with (
        patch.object(real_st, "session_state", state),
        patch(f"{SIDEBAR}.toolkit_sidebar"),
        patch(f"{SIDEBAR}.history_sidebar"),
        patch(f"{SIDEBAR}.lm_sidebar", return_value=[]),
        patch(f"{SIDEBAR}.vector_search_sidebar"),
        patch(f"{SIDEBAR}.state", state),
        patch(f"{HELPERS}.state", state),
        patch(f"{HELPERS}.api_get", return_value={"messages": []}),
    ):
        import client.app.content.chatbot  # noqa: F401


_ensure_chatbot_loaded()


# ---------------------------------------------------------------------------
# _extract_search_query
# ---------------------------------------------------------------------------
def _rephrase_payload(rephrased: str = "What is data redaction?") -> str:
    import json

    return json.dumps(
        {
            "original_prompt": "data redaction?",
            "rephrased_prompt": rephrased,
            "was_rephrased": True,
            "status": "success",
        }
    )


def _content_blocks(text: str) -> str:
    import json

    return json.dumps([{"type": "text", "text": text, "id": "lc_abc123"}])


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("data redaction?", "data redaction?"),
        (_content_blocks(_rephrase_payload()), "What is data redaction?"),
        (_rephrase_payload(), "What is data redaction?"),
        (_content_blocks("simple query"), "simple query"),
        ("not json {", "not json {"),
    ],
    ids=[
        "plain_string",
        "content_blocks_with_rephrase",
        "rephrase_without_content_blocks",
        "content_blocks_plain",
        "malformed_json",
    ],
)
def test_extract_search_query(raw, expected):
    """_extract_search_query unwraps LangChain content blocks and RephrasePrompt JSON."""
    from client.app.content.chatbot import _extract_search_query

    assert _extract_search_query(raw) == expected


# ---------------------------------------------------------------------------
# show_vector_search_refs
# ---------------------------------------------------------------------------
class TestShowVectorSearchRefs:
    """Tests for show_vector_search_refs."""

    def test_renders_refs(self, mock_st):
        """Renders markdown references header for provided docs."""
        vs_meta = {
            "documents": [
                {
                    "page_content": "text1",
                    "metadata": {"similarity_score": 0.95, "source": "doc1", "filename": "f1.pdf"},
                },
                {"page_content": "text2", "metadata": {"similarity_score": 0.80}},
            ],
        }
        with patch(f"{MODULE}.st", mock_st):
            from client.app.content.chatbot import show_vector_search_refs

            show_vector_search_refs(vs_meta)
        mock_st.markdown.assert_any_call("**References:**")

    def test_score_in_label(self, mock_st):
        """Similarity score appears in the popover label."""
        vs_meta = {"documents": [{"page_content": "text", "metadata": {"similarity_score": 0.95}}]}
        col = MagicMock()
        popover_ctx = MagicMock()
        popover_ctx.__enter__ = MagicMock()
        popover_ctx.__exit__ = MagicMock(return_value=False)
        col.popover.return_value = popover_ctx
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = [col, MagicMock(), MagicMock()]
        with patch(f"{MODULE}.st", mock_st):
            from client.app.content.chatbot import show_vector_search_refs

            show_vector_search_refs(vs_meta)
        label = col.popover.call_args[0][0]
        assert "0.95" in label

    def test_no_score(self, mock_st):
        """Missing similarity score produces a plain reference label."""
        vs_meta = {"documents": [{"page_content": "text", "metadata": {}}]}
        col = MagicMock()
        popover_ctx = MagicMock()
        popover_ctx.__enter__ = MagicMock()
        popover_ctx.__exit__ = MagicMock(return_value=False)
        col.popover.return_value = popover_ctx
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = [col, MagicMock(), MagicMock()]
        with patch(f"{MODULE}.st", mock_st):
            from client.app.content.chatbot import show_vector_search_refs

            show_vector_search_refs(vs_meta)
        label = col.popover.call_args[0][0]
        assert "Reference:" in label

    def test_metadata_expander_with_vs_metadata(self, mock_st):
        """Expander is rendered when vs_metadata is provided."""
        vs_meta = {
            "documents": [{"page_content": "text", "metadata": {"filename": "f1.pdf"}}],
            "searched_tables": ["t1"],
            "context_input": "query",
        }
        col = MagicMock()
        popover_ctx = MagicMock()
        popover_ctx.__enter__ = MagicMock()
        popover_ctx.__exit__ = MagicMock(return_value=False)
        col.popover.return_value = popover_ctx
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = [col, MagicMock(), MagicMock()]
        with patch(f"{MODULE}.st", mock_st):
            from client.app.content.chatbot import show_vector_search_refs

            show_vector_search_refs(vs_meta)
        mock_st.expander.assert_called_once()

    def test_source_docs_in_expander(self, mock_st):
        """Source documents trigger an expander widget."""
        vs_meta = {"documents": [{"page_content": "text", "metadata": {"filename": "file.pdf"}}]}
        col = MagicMock()
        popover_ctx = MagicMock()
        popover_ctx.__enter__ = MagicMock()
        popover_ctx.__exit__ = MagicMock(return_value=False)
        col.popover.return_value = popover_ctx
        mock_st.columns.side_effect = None
        mock_st.columns.return_value = [col, MagicMock(), MagicMock()]
        with patch(f"{MODULE}.st", mock_st):
            from client.app.content.chatbot import show_vector_search_refs

            show_vector_search_refs(vs_meta)
        mock_st.expander.assert_called_once()

    def test_missing_page_content_filtered(self, mock_st):
        """Documents without page_content are silently skipped; expander still renders."""
        vs_meta = {
            "documents": [
                {"metadata": {"similarity_score": 0.5}},
                {"page_content": "", "metadata": {}},
                {"page_content": None, "metadata": {}},
            ],
            "searched_tables": ["t1"],
            "context_input": "query",
        }
        with patch(f"{MODULE}.st", mock_st):
            from client.app.content.chatbot import show_vector_search_refs

            show_vector_search_refs(vs_meta)
        # No References header or columns because all documents were filtered out
        for call in mock_st.markdown.call_args_list:
            assert call[0][0] != "**References:**"
        mock_st.columns.assert_not_called()
        # Expander still renders
        mock_st.expander.assert_called_once()

    def test_empty_docs(self, mock_st):
        """Empty doc list still renders the expander with search details."""
        vs_meta = {"documents": [], "searched_tables": ["t1"], "context_input": "query"}
        with patch(f"{MODULE}.st", mock_st):
            from client.app.content.chatbot import show_vector_search_refs

            show_vector_search_refs(vs_meta)
        mock_st.expander.assert_called_once()


# ---------------------------------------------------------------------------
# _stream_chat (async generator)
# ---------------------------------------------------------------------------
class TestStreamChat:
    """Tests for _stream_chat."""

    def _setup_async_client(self, chunks):
        """Create properly nested async context manager mocks for httpx.AsyncClient + stream."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        async def _aiter_text():
            for chunk in chunks:
                yield chunk

        mock_resp.aiter_text = _aiter_text

        # Inner async context manager: client.stream(...)
        stream_ctx = MagicMock()
        stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        stream_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_client_instance = MagicMock()
        mock_client_instance.stream = MagicMock(return_value=stream_ctx)

        # Outer async context manager: httpx.AsyncClient(...)
        client_ctx = MagicMock()
        client_ctx.__aenter__ = AsyncMock(return_value=mock_client_instance)
        client_ctx.__aexit__ = AsyncMock(return_value=False)

        return client_ctx

    async def test_yields_chunks(self):
        """Stream chunks are yielded as text content."""
        state = _make_state()
        chunks = [
            'data: {"type": "stream", "content": "Hello"}\n\n',
            'data: {"type": "stream", "content": " world"}\n\n',
            "data: [DONE]\n\n",
        ]
        client_ctx = self._setup_async_client(chunks)

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._base_url", return_value="http://test/v1"),
            patch(f"{MODULE}._headers", return_value={"X-API-Key": "k"}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client_ctx),
        ):
            from client.app.content.chatbot import _stream_chat

            metadata: dict = {}
            result = []
            async for chunk in _stream_chat([{"role": "user", "content": "hi"}], metadata):
                result.append(chunk)
        assert result == ["Hello", " world"]

    async def test_local_https_disables_certificate_verification(self):
        """Local self-signed HTTPS streams should not verify the generated cert."""
        state = _make_state()
        chunks = ["data: [DONE]\n\n"]
        client_ctx = self._setup_async_client(chunks)

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._base_url", return_value="https://127.0.0.1:8000/v1"),
            patch(f"{MODULE}._headers", return_value={"X-API-Key": "k"}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client_ctx) as mock_client,
        ):
            from client.app.content.chatbot import _stream_chat

            async for _ in _stream_chat([{"role": "user", "content": "hi"}], {}):
                pass

        mock_client.assert_called_once_with(timeout=120, verify=False)

    async def test_populates_token_usage(self):
        """Completion event populates token usage in metadata."""
        state = _make_state()
        chunks = [
            (
                'data: {"type": "completion", "token_usage":'
                ' {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}\n\n'
            ),
            "data: [DONE]\n\n",
        ]
        client_ctx = self._setup_async_client(chunks)

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._base_url", return_value="http://test/v1"),
            patch(f"{MODULE}._headers", return_value={}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client_ctx),
        ):
            from client.app.content.chatbot import _stream_chat

            metadata: dict = {}
            async for _ in _stream_chat([], metadata):
                pass
        assert metadata["token_usage"]["total_tokens"] == 30

    async def test_populates_vs_metadata(self):
        """Completion event with vs_metadata populates metadata dict."""
        state = _make_state()
        chunks = [
            ('data: {"type": "completion", "vs_metadata": {"documents": [{"page_content": "x"}]}}\n\n'),
            "data: [DONE]\n\n",
        ]
        client_ctx = self._setup_async_client(chunks)

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._base_url", return_value="http://test/v1"),
            patch(f"{MODULE}._headers", return_value={}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client_ctx),
        ):
            from client.app.content.chatbot import _stream_chat

            metadata: dict = {}
            async for _ in _stream_chat([], metadata):
                pass
        assert "vs_metadata" in metadata

    async def test_populates_sql_metadata(self):
        """Completion event with sql_metadata populates metadata dict."""
        state = _make_state()
        chunks = [
            ('data: {"type": "completion", "sql_metadata": {"executed_sql": ["SELECT * FROM drivers"]}}\n\n'),
            "data: [DONE]\n\n",
        ]
        client_ctx = self._setup_async_client(chunks)

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._base_url", return_value="http://test/v1"),
            patch(f"{MODULE}._headers", return_value={}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client_ctx),
        ):
            from client.app.content.chatbot import _stream_chat

            metadata: dict = {}
            async for _ in _stream_chat([], metadata):
                pass
        assert metadata["sql_metadata"]["executed_sql"] == ["SELECT * FROM drivers"]

    async def test_error_type_raises(self):
        """Error-type SSE event raises RuntimeError."""
        state = _make_state()
        chunks = [
            'data: {"type": "error", "content": "Something failed"}\n\n',
        ]
        client_ctx = self._setup_async_client(chunks)

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._base_url", return_value="http://test/v1"),
            patch(f"{MODULE}._headers", return_value={}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client_ctx),
        ):
            from client.app.content.chatbot import _stream_chat

            with pytest.raises(RuntimeError, match="Something failed"):
                async for _ in _stream_chat([], {}):
                    pass

    async def test_malformed_json_skipped(self):
        """Malformed JSON lines are silently skipped."""
        state = _make_state()
        chunks = [
            "data: not-json\n\n",
            'data: {"type": "stream", "content": "ok"}\n\n',
            "data: [DONE]\n\n",
        ]
        client_ctx = self._setup_async_client(chunks)

        with (
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._base_url", return_value="http://test/v1"),
            patch(f"{MODULE}._headers", return_value={}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=client_ctx),
        ):
            from client.app.content.chatbot import _stream_chat

            result = []
            async for chunk in _stream_chat([], {}):
                result.append(chunk)
        assert result == ["ok"]


# ---------------------------------------------------------------------------
# _handle_chat
# ---------------------------------------------------------------------------
class TestHandleChat:
    """Tests for _handle_chat."""

    async def test_streams_to_placeholder(self, mock_st):
        """Streamed chunks are concatenated into assistant message."""
        state = _make_state()

        async def _mock_stream(_messages, _metadata):
            yield "Hello"
            yield " world"

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._stream_chat", side_effect=_mock_stream),
        ):
            from client.app.content.chatbot import _handle_chat

            await _handle_chat("test input")
        # Streamed chunks are rendered via placeholder.markdown
        placeholder = mock_st.empty.return_value
        placeholder.markdown.assert_called_with("Hello world")

    async def test_token_caption(self, mock_st):
        """Token usage metadata triggers a caption display."""
        state = _make_state()

        async def _mock_stream(_messages, metadata):
            metadata["token_usage"] = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
            yield "response"

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._stream_chat", side_effect=_mock_stream),
        ):
            from client.app.content.chatbot import _handle_chat

            await _handle_chat("test")
        mock_st.caption.assert_called_once()

    async def test_vs_refs_rendered(self, mock_st):
        """Vector search references are rendered when vs_metadata is present."""
        state = _make_state()

        async def _mock_stream(_messages, metadata):
            metadata["vs_metadata"] = {"documents": [{"page_content": "ref"}]}
            yield "answer"

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._stream_chat", side_effect=_mock_stream),
            patch(f"{MODULE}.show_vector_search_refs") as mock_refs,
        ):
            from client.app.content.chatbot import _handle_chat

            await _handle_chat("test")
        mock_refs.assert_called_once()

    async def test_sql_metadata_rendered(self, mock_st):
        """SQL metadata is rendered when present."""
        state = _make_state()

        async def _mock_stream(_messages, metadata):
            metadata["sql_metadata"] = {"executed_sql": ["SELECT * FROM drivers"]}
            yield "answer"

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._stream_chat", side_effect=_mock_stream),
            patch(f"{MODULE}.show_sql_details") as mock_sql,
        ):
            from client.app.content.chatbot import _handle_chat

            await _handle_chat("test")
        mock_sql.assert_called_once_with({"executed_sql": ["SELECT * FROM drivers"]})

    async def test_http_status_error(self, mock_st):
        """HTTP status error is caught and displayed via st.error."""
        state = _make_state()

        async def _mock_stream(_messages, _metadata):
            raise make_http_error(500, "Server error")
            yield  # pragma: no cover

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._stream_chat", side_effect=_mock_stream),
        ):
            from client.app.content.chatbot import _handle_chat

            await _handle_chat("test")
        mock_st.error.assert_called_once()

    async def test_read_timeout(self, mock_st):
        """Read timeout is caught and shown as timed-out error."""
        state = _make_state()

        async def _mock_stream(_messages, _metadata):
            raise httpx.ReadTimeout("timeout")
            yield  # pragma: no cover

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._stream_chat", side_effect=_mock_stream),
        ):
            from client.app.content.chatbot import _handle_chat

            await _handle_chat("test")
        mock_st.error.assert_called_once()
        assert "timed out" in mock_st.error.call_args[0][0]

    async def test_http_connection_error(self, mock_st):
        """HTTP connection errors are caught instead of surfacing a traceback."""
        state = _make_state()

        async def _mock_stream(_messages, _metadata):
            request = httpx.Request("POST", "https://127.0.0.1:8000/v1/chat/streams")
            raise httpx.ConnectError("certificate verify failed", request=request)
            yield  # pragma: no cover

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._stream_chat", side_effect=_mock_stream),
        ):
            from client.app.content.chatbot import _handle_chat

            await _handle_chat("test")
        mock_st.error.assert_called_once()
        assert "Unable to connect" in mock_st.error.call_args[0][0]

    async def test_runtime_error(self, mock_st):
        """RuntimeError is caught and displayed via st.error."""
        state = _make_state()

        async def _mock_stream(_messages, _metadata):
            raise RuntimeError("Something broke")
            yield  # pragma: no cover

        with (
            patch(f"{MODULE}.st", mock_st),
            patch(f"{MODULE}.state", state),
            patch(f"{MODULE}._stream_chat", side_effect=_mock_stream),
        ):
            from client.app.content.chatbot import _handle_chat

            await _handle_chat("test")
        mock_st.error.assert_called_once()
        assert "Something broke" in mock_st.error.call_args[0][0]
