"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

WayFlow runtime tests for the VecSearch flow: AgentSpec → WayFlow loading and session.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, patch

from server.app.runtime.wayflow.vecsearch import (
    VecSearchFlowSession,
    build_vecsearch_runtime_flow,
)
from server.tests.conftest import (
    MOCK_API_KEY,
    MOCK_SERVER_URL,
    MOCK_SYSTEM_PROMPT,
    SAMPLE_CLIENT_SETTINGS_OBJ,
)


class TestBuildVecsearchRuntimeFlow:
    """Unit tests for WayFlow loading (mocking MCP)."""

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_returns_runtime_flow(self, mock_fetch):
        """Verify the loader produces a WayFlow runtime flow."""
        mock_fetch.return_value = MOCK_SYSTEM_PROMPT
        flow = await build_vecsearch_runtime_flow(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert hasattr(flow, "start_conversation")

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_uses_mcp_prompt(self, mock_fetch):
        """Verify the loader fetches the optimizer_vs-tools-default prompt."""
        mock_fetch.return_value = "Custom VecSearch prompt."
        await build_vecsearch_runtime_flow(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        mock_fetch.assert_awaited_once_with(MOCK_SERVER_URL, MOCK_API_KEY, "optimizer_vs-tools-default")

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_fallback_on_mcp_failure(self, mock_fetch):
        """Verify the loader falls back to the default prompt when MCP fails."""
        mock_fetch.side_effect = ConnectionError("MCP server unreachable")
        flow = await build_vecsearch_runtime_flow(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert hasattr(flow, "start_conversation")


def test_vecsearch_session_is_flow_session_subclass():
    """Verify VecSearchFlowSession inherits from FlowSession."""
    from server.app.runtime.wayflow.session import FlowSession

    assert issubclass(VecSearchFlowSession, FlowSession)
