"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/mcp_prompts.py

Tests the MCP prompts endpoints through the full API stack.
These endpoints require authentication.
"""
# spell-checker: disable
# pylint: disable=protected-access,import-error,import-outside-toplevel


class TestMCPPromptsEndpoints:
    """Test MCP Prompts API Endpoints"""

    def test_mcp_prompts_list_metadata_only(self, client, auth_headers):
        """Test listing MCP prompts without full text (MCP standard)"""
        response = client.get("/v1/mcp/prompts", headers=auth_headers["valid_auth"])

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        if data:
            # Check structure of first prompt
            prompt = data[0]
            assert "name" in prompt
            assert "title" in prompt
            assert "description" in prompt
            # MCP standard format may not include "text" field

    def test_mcp_prompts_list_with_full_text(self, client, auth_headers):
        """Test listing MCP prompts with full text parameter"""
        response = client.get("/v1/mcp/prompts", headers=auth_headers["valid_auth"], params={"full": True})

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        if data:
            # Check structure includes resolved text
            prompt = data[0]
            assert "name" in prompt
            assert "title" in prompt
            assert "description" in prompt
            assert "text" in prompt
            assert isinstance(prompt["text"], str)
            assert len(prompt["text"]) > 0

    def test_mcp_prompts_full_parameter_false(self, client, auth_headers):
        """Test listing MCP prompts with full=false explicitly"""
        response = client.get("/v1/mcp/prompts", headers=auth_headers["valid_auth"], params={"full": False})

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_mcp_prompts_only_optimizer_prompts(self, client, auth_headers):
        """Test that only optimizer_ prefixed prompts are returned"""
        response = client.get("/v1/mcp/prompts", headers=auth_headers["valid_auth"], params={"full": True})

        assert response.status_code == 200
        data = response.json()

        # All prompts should start with "optimizer_"
        for prompt in data:
            assert prompt["name"].startswith("optimizer_")

    def test_mcp_get_single_prompt(self, client, auth_headers):
        """Test getting a single prompt by name"""
        # First get list to find a prompt name
        response = client.get("/v1/mcp/prompts", headers=auth_headers["valid_auth"], params={"full": True})
        assert response.status_code == 200
        prompts = response.json()

        if not prompts:
            # No prompts available, skip test
            return

        prompt_name = prompts[0]["name"]

        # Get single prompt
        response = client.get(f"/v1/mcp/prompts/{prompt_name}", headers=auth_headers["valid_auth"])

        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert isinstance(data["messages"], list)
        assert len(data["messages"]) > 0
        assert "content" in data["messages"][0]
        assert "text" in data["messages"][0]["content"]

    def test_mcp_patch_prompt(self, client, auth_headers):
        """Test updating a prompt's text"""
        # Get a prompt name first
        response = client.get("/v1/mcp/prompts", headers=auth_headers["valid_auth"], params={"full": True})
        assert response.status_code == 200
        prompts = response.json()

        if not prompts:
            # No prompts available, skip test
            return

        prompt_name = prompts[0]["name"]
        original_text = prompts[0]["text"]

        # Update the prompt
        new_text = "Updated test instruction"
        response = client.patch(
            f"/v1/mcp/prompts/{prompt_name}",
            headers=auth_headers["valid_auth"],
            json={"instructions": new_text},
        )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert prompt_name in data["message"]

        # Verify the change
        response = client.get("/v1/mcp/prompts", headers=auth_headers["valid_auth"], params={"full": True})
        assert response.status_code == 200
        updated_prompts = response.json()
        updated_prompt = next((p for p in updated_prompts if p["name"] == prompt_name), None)
        assert updated_prompt is not None
        assert updated_prompt["text"] == new_text

        # Restore original text
        client.patch(
            f"/v1/mcp/prompts/{prompt_name}",
            headers=auth_headers["valid_auth"],
            json={"instructions": original_text},
        )
