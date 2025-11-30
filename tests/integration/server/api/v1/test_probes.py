"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/probes.py

Tests the Kubernetes probe endpoints (liveness, readiness, MCP health).
These endpoints do not require authentication.
"""


class TestLivenessProbe:
    """Integration tests for the liveness probe endpoint."""

    def test_liveness_returns_200(self, client):
        """GET /v1/liveness should return 200 with status alive."""
        response = client.get("/v1/liveness")

        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_liveness_no_auth_required(self, client):
        """GET /v1/liveness should not require authentication."""
        # No auth headers provided
        response = client.get("/v1/liveness")

        assert response.status_code == 200


class TestReadinessProbe:
    """Integration tests for the readiness probe endpoint."""

    def test_readiness_returns_200(self, client):
        """GET /v1/readiness should return 200 with status ready."""
        response = client.get("/v1/readiness")

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

    def test_readiness_no_auth_required(self, client):
        """GET /v1/readiness should not require authentication."""
        response = client.get("/v1/readiness")

        assert response.status_code == 200


class TestMcpHealthz:
    """Integration tests for the MCP health check endpoint."""

    def test_mcp_healthz_returns_200(self, client):
        """GET /v1/mcp/healthz should return 200 with MCP status."""
        response = client.get("/v1/mcp/healthz")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "name" in data
        assert "version" in data
        assert "available_tools" in data

    def test_mcp_healthz_no_auth_required(self, client):
        """GET /v1/mcp/healthz should not require authentication."""
        response = client.get("/v1/mcp/healthz")

        assert response.status_code == 200

    def test_mcp_healthz_returns_server_info(self, client):
        """GET /v1/mcp/healthz should return MCP server information."""
        response = client.get("/v1/mcp/healthz")

        data = response.json()
        assert data["name"] == "Oracle AI Optimizer and Toolkit MCP Server"
        assert isinstance(data["available_tools"], int)
        assert data["available_tools"] >= 0
