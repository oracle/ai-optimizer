"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the /api/v1/agentspec/ endpoints.
"""
# spell-checker: disable

import pytest


class TestListSpecs:
    """GET /api/v1/agentspec/specs"""

    @pytest.mark.anyio
    async def test_returns_list_of_specs(self, app_client, auth_headers):
        """Endpoint returns 200 with a list containing name, description, and spec."""
        response = await app_client.get("/v1/agentspec/specs", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) > 0
        for entry in body:
            assert "name" in entry
            assert "description" in entry
            assert "spec" in entry

    @pytest.mark.anyio
    async def test_contains_expected_spec_names(self, app_client, auth_headers):
        """Response contains llm_only, nl2sql_agent, and rag specs."""
        response = await app_client.get("/v1/agentspec/specs", headers=auth_headers)
        names = [s["name"] for s in response.json()]
        assert "llm_only" in names
        assert "nl2sql_agent" in names
        assert "rag" in names

    @pytest.mark.anyio
    async def test_each_spec_serializes_without_error(self, app_client, auth_headers):
        """Every spec must contain a valid serialized agentspec, not an error fallback."""
        response = await app_client.get("/v1/agentspec/specs", headers=auth_headers)
        for entry in response.json():
            assert "error" not in entry["spec"], f"spec {entry['name']!r} failed to serialize"

    @pytest.mark.anyio
    async def test_unauthenticated_rejected(self, app_client):
        """Request without auth headers is rejected."""
        response = await app_client.get("/v1/agentspec/specs")
        assert response.status_code in (401, 403)


class TestGetSpecByName:
    """GET /api/v1/agentspec/specs/{name}"""

    @pytest.mark.anyio
    async def test_known_spec_returns_200(self, app_client, auth_headers):
        """Valid spec name returns 200 with matching name."""
        response = await app_client.get("/v1/agentspec/specs/llm_only", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "llm_only"
        assert "spec" in body
        assert isinstance(body["spec"], dict)

    @pytest.mark.anyio
    async def test_unknown_spec_returns_404(self, app_client, auth_headers):
        """Requesting a nonexistent spec name returns 404."""
        response = await app_client.get(
            "/v1/agentspec/specs/this-does-not-exist",
            headers=auth_headers,
        )
        assert response.status_code == 404

    @pytest.mark.anyio
    @pytest.mark.parametrize("name", ["llm_only", "nl2sql_agent", "rag"])
    async def test_each_individual_spec_serializes_without_error(self, app_client, auth_headers, name):
        """Each spec endpoint must return a valid serialized agentspec, not an error fallback."""
        response = await app_client.get(f"/v1/agentspec/specs/{name}", headers=auth_headers)
        assert response.status_code == 200
        assert "error" not in response.json()["spec"], f"spec {name!r} failed to serialize"

    @pytest.mark.anyio
    async def test_unauthenticated_rejected(self, app_client):
        """Request without auth headers is rejected."""
        response = await app_client.get("/v1/agentspec/specs/llm_only")
        assert response.status_code in (401, 403)
