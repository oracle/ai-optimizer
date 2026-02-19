"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/probes.py
Tests for Kubernetes health probe endpoints.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from server.api.v1 import probes


class TestGetMcp:
    """Tests for the get_mcp dependency function."""

    def test_get_mcp_returns_fastmcp_app(self):
        """get_mcp should return the FastMCP app from request state."""
        mock_request = MagicMock()
        mock_fastmcp = MagicMock()
        mock_request.app.state.fastmcp_app = mock_fastmcp

        result = probes.get_mcp(mock_request)

        assert result == mock_fastmcp

    def test_get_mcp_accesses_correct_state_attribute(self):
        """get_mcp should access app.state.fastmcp_app."""
        mock_request = MagicMock()

        probes.get_mcp(mock_request)

        _ = mock_request.app.state.fastmcp_app  # Verify attribute access


class TestLivenessProbe:
    """Tests for the liveness_probe endpoint."""

    @pytest.mark.asyncio
    async def test_liveness_probe_returns_alive(self):
        """liveness_probe should return alive status."""
        result = await probes.liveness_probe()

        assert result == {"status": "alive"}

    @pytest.mark.asyncio
    async def test_liveness_probe_is_async(self):
        """liveness_probe should be an async function."""
        assert asyncio.iscoroutinefunction(probes.liveness_probe)


class TestReadinessProbe:
    """Tests for the readiness_probe endpoint."""

    @pytest.mark.asyncio
    async def test_readiness_probe_returns_ready(self):
        """readiness_probe should return ready status."""
        result = await probes.readiness_probe()

        assert result == {"status": "ready"}

    @pytest.mark.asyncio
    async def test_readiness_probe_is_async(self):
        """readiness_probe should be an async function."""
        assert asyncio.iscoroutinefunction(probes.readiness_probe)


class TestMcpHealthz:
    """Tests for the mcp_healthz endpoint."""

    def test_mcp_healthz_returns_ready_status(self):
        """mcp_healthz should return ready status with server info."""
        mock_fastmcp = MagicMock()
        mock_fastmcp.__dict__["_mcp_server"] = MagicMock()
        mock_fastmcp.__dict__["_mcp_server"].__dict__ = {
            "name": "test-server",
            "version": "1.0.0",
        }
        mock_fastmcp.available_tools = ["tool1", "tool2"]

        result = probes.mcp_healthz(mock_fastmcp)

        assert result["status"] == "ready"
        assert result["name"] == "test-server"
        assert result["version"] == "1.0.0"
        assert result["available_tools"] == 2

    def test_mcp_healthz_returns_not_ready_when_none(self):
        """mcp_healthz should return not ready when mcp_engine is None."""
        result = probes.mcp_healthz(None)

        assert result["status"] == "not ready"

    def test_mcp_healthz_with_no_available_tools(self):
        """mcp_healthz should handle missing available_tools attribute."""
        mock_fastmcp = MagicMock(spec=[])  # No available_tools attribute
        mock_fastmcp.__dict__["_mcp_server"] = MagicMock()
        mock_fastmcp.__dict__["_mcp_server"].__dict__ = {
            "name": "test-server",
            "version": "1.0.0",
        }

        result = probes.mcp_healthz(mock_fastmcp)

        assert result["status"] == "ready"
        assert result["available_tools"] == 0

    def test_mcp_healthz_is_not_async(self):
        """mcp_healthz should be a sync function."""
        assert not asyncio.iscoroutinefunction(probes.mcp_healthz)


class TestRouterConfiguration:
    """Tests for router configuration."""

    def test_noauth_router_exists(self):
        """The noauth router should be defined."""
        assert hasattr(probes, "noauth")

    def test_noauth_router_has_routes(self):
        """The noauth router should have registered routes."""
        routes = [route.path for route in probes.noauth.routes]

        assert "/liveness" in routes
        assert "/readiness" in routes
        assert "/mcp/healthz" in routes
