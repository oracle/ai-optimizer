"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the MCP adapter: transport construction and prompt fetching.
"""
# spell-checker: disable

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import GetPromptResult, ImageContent, PromptMessage, TextContent
from pyagentspec.mcp import StreamableHTTPTransport

from server.app.agentspec.adapters.mcp import _verify_for_url, build_mcp_transport, fetch_mcp_prompt


class TestBuildMcpTransport:
    """Unit tests for build_mcp_transport."""

    def test_transport_url(self):
        """Verify the URL is passed verbatim."""
        transport = build_mcp_transport("https://mcp.example.com/endpoint", "key")
        assert transport.url == "https://mcp.example.com/endpoint"

    def test_transport_name(self):
        """Verify transport name is fixed to 'mcp-transport'."""
        transport = build_mcp_transport("https://x.com", "k")
        assert transport.name == "mcp-transport"

    def test_transport_type(self):
        """Verify the return type is StreamableHTTPTransport."""
        transport = build_mcp_transport("https://x.com", "k")
        assert isinstance(transport, StreamableHTTPTransport)

    def test_sensitive_headers_contains_api_key(self):
        """Verify X-API-Key is set in sensitive_headers."""
        transport = build_mcp_transport("https://x.com", "secret-key-123")
        headers = dict(transport.sensitive_headers or {})
        assert "X-API-Key" in headers

    def test_sensitive_headers_value(self):
        """Verify sensitive_headers X-API-Key value matches the api_key argument."""
        transport = build_mcp_transport("https://x.com", "my-secret")
        headers = dict(transport.sensitive_headers or {})
        assert headers["X-API-Key"] == "my-secret"


class TestMcpTlsVerification:
    """Unit tests for MCP HTTP client certificate verification policy."""

    def test_local_https_disables_verification(self):
        assert _verify_for_url("https://127.0.0.1:8000/mcp/") is False
        assert _verify_for_url("https://localhost:8000/mcp/") is False
        assert _verify_for_url("https://[::1]:8000/mcp/") is False
        assert _verify_for_url("https://0.0.0.0:8000/mcp/") is False

    def test_external_https_verifies_certificates(self):
        assert _verify_for_url("https://release-ai.appoci.oraclecorp.com:8000/mcp/") is True

    def test_http_uses_default_verification_flag(self):
        assert _verify_for_url("http://127.0.0.1:8000/mcp/") is True


def _mock_mcp_session(prompt_result: GetPromptResult) -> AsyncMock:
    """Create a mock MCP ClientSession that returns the given prompt result."""
    session = AsyncMock()
    session.initialize = AsyncMock()
    session.get_prompt = AsyncMock(return_value=prompt_result)
    return session


def _patch_mcp_context(mock_session):
    """Return mocks for streamable_http_client and ClientSession.

    streamable_http_client is an async context manager yielding (read, write, _).
    ClientSession is an async context manager wrapping the session object.
    """

    @asynccontextmanager
    async def fake_streamable_http_client(_url, *, http_client=None):
        del http_client
        read_stream = MagicMock()
        write_stream = MagicMock()
        yield read_stream, write_stream, None

    @asynccontextmanager
    async def fake_client_session(_read, _write):
        yield mock_session

    return (
        patch("server.app.agentspec.adapters.mcp.streamable_http_client", fake_streamable_http_client),
        patch("server.app.agentspec.adapters.mcp.ClientSession", fake_client_session),
    )


class TestFetchMcpPrompt:
    """Unit tests for fetch_mcp_prompt."""

    server_url: str
    api_key: str

    def setup_method(self):
        """Set up shared MCP configuration used by each test."""
        self.server_url = "https://mcp.example.com"
        self.api_key = "test-key"

    @pytest.mark.anyio
    async def test_happy_path_returns_text(self):
        """Single TextContent message is returned as-is."""
        result = GetPromptResult(
            messages=[PromptMessage(role="assistant", content=TextContent(type="text", text="Hello from MCP"))]
        )
        session = _mock_mcp_session(result)
        p1, p2 = _patch_mcp_context(session)
        with p1, p2:
            text = await fetch_mcp_prompt(self.server_url, self.api_key, "my-prompt")
        assert text == "Hello from MCP"
        session.get_prompt.assert_awaited_once_with("my-prompt", None)

    @pytest.mark.anyio
    async def test_arguments_forwarded(self):
        """Optional arguments dict is passed through to session.get_prompt."""
        result = GetPromptResult(messages=[])
        session = _mock_mcp_session(result)
        p1, p2 = _patch_mcp_context(session)
        with p1, p2:
            await fetch_mcp_prompt(self.server_url, self.api_key, "p", arguments={"k": "v"})
        session.get_prompt.assert_awaited_once_with("p", {"k": "v"})

    @pytest.mark.anyio
    async def test_multiple_messages_joined_with_double_newline(self):
        """Multiple TextContent messages are joined with '\\n\\n'."""
        result = GetPromptResult(
            messages=[
                PromptMessage(role="assistant", content=TextContent(type="text", text="First")),
                PromptMessage(role="assistant", content=TextContent(type="text", text="Second")),
            ]
        )
        session = _mock_mcp_session(result)
        p1, p2 = _patch_mcp_context(session)
        with p1, p2:
            text = await fetch_mcp_prompt(self.server_url, self.api_key, "p")
        assert text == "First\n\nSecond"

    @pytest.mark.anyio
    async def test_non_text_content_filtered(self):
        """Messages with non-TextContent are silently skipped."""
        result = GetPromptResult(
            messages=[
                PromptMessage(role="assistant", content=TextContent(type="text", text="kept")),
                PromptMessage(
                    role="assistant",
                    content=ImageContent(type="image", data="base64data", mimeType="image/png"),
                ),
                PromptMessage(role="assistant", content=TextContent(type="text", text="also kept")),
            ]
        )
        session = _mock_mcp_session(result)
        p1, p2 = _patch_mcp_context(session)
        with p1, p2:
            text = await fetch_mcp_prompt(self.server_url, self.api_key, "p")
        assert text == "kept\n\nalso kept"

    @pytest.mark.anyio
    async def test_empty_messages_returns_empty_string(self):
        """No messages in prompt result yields empty string."""
        result = GetPromptResult(messages=[])
        session = _mock_mcp_session(result)
        p1, p2 = _patch_mcp_context(session)
        with p1, p2:
            text = await fetch_mcp_prompt(self.server_url, self.api_key, "p")
        assert text == ""

    @pytest.mark.anyio
    async def test_connection_error_propagates(self):
        """Network errors from streamable_http_client propagate to the caller."""

        class FailingClient:
            """Async context manager that raises ConnectionError on entry."""

            async def __aenter__(self):
                raise ConnectionError("refused")

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        def failing_client(_url, *, http_client=None):
            del http_client
            return FailingClient()

        with patch("server.app.agentspec.adapters.mcp.streamable_http_client", failing_client), pytest.raises(
            ConnectionError, match="refused"
        ):
            await fetch_mcp_prompt(self.server_url, self.api_key, "p")
