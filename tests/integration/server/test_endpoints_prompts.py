"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

import pytest


#############################################################################
# Test AuthN required and Valid
#############################################################################
class TestInvalidAuthEndpoints:
    """Test endpoints without Headers and Invalid AuthN"""

    @pytest.mark.parametrize(
        "auth_type, status_code",
        [
            pytest.param("no_auth", 403, id="no_auth"),
            pytest.param("invalid_auth", 401, id="invalid_auth"),
        ],
    )
    @pytest.mark.parametrize(
        "endpoint, api_method",
        [
            pytest.param("/v1/prompts", "get", id="prompts_list"),
            pytest.param("/v1/prompts/sys/Basic", "get", id="prompts_get"),
            pytest.param("/v1/prompts/sys/Basic", "patch", id="prompts_update"),
        ],
    )
    def test_endpoints(self, client, auth_headers, endpoint, api_method, auth_type, status_code):
        """Test endpoints require valide authentication."""
        response = getattr(client, api_method)(endpoint, headers=auth_headers[auth_type])
        assert response.status_code == status_code


#############################################################################
# Endpoints Test
#############################################################################
class TestEndpoints:
    """Test Endpoints"""

    test_cases = [
        pytest.param("Basic Example", "sys", 200, id="basic_example_sys_prompt"),
        pytest.param("Vector Search Example", "sys", 200, id="vs_example_sys_prompt"),
        pytest.param("Custom", "sys", 200, id="basic_sys_prompt"),
        pytest.param("NONEXISTANT", "sys", 404, id="nonexistant_sys_prompt"),
        pytest.param("Basic Example", "ctx", 200, id="basic_example_ctx_prompt"),
        pytest.param("Custom", "ctx", 200, id="custom_ctx_prompt"),
        pytest.param("NONEXISTANT", "ctx", 404, id="nonexistant_ctx_prompt"),
    ]

    @pytest.mark.parametrize("name, category, status_code", test_cases)
    def test_prompts_list_before(self, client, auth_headers, name, category, status_code):
        """List boostrapped prompts"""
        response = client.get("/v1/prompts", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        # If our status_code should return 200, then check that prompt is in output
        if response.status_code == status_code:
            assert any(r["name"] == name and r["category"] == category for r in response.json())

    @pytest.mark.parametrize("name, category, status_code", test_cases)
    def test_prompts_get_before(self, client, auth_headers, name, category, status_code):
        """Get individual prompts"""
        response = client.get(f"/v1/prompts/{category}/{name}", headers=auth_headers["valid_auth"])
        assert response.status_code == status_code
        if status_code == 200:
            data = response.json()
            assert data["name"] == name
            assert data["category"] == category
            assert data["prompt"] is not None
        else:
            assert response.json() == {"detail": f"Prompt: {name} ({category}) not found."}

    @pytest.mark.parametrize("name, category, status_code", test_cases)
    def test_prompts_update(self, client, auth_headers, name, category, status_code):
        """Update Prompt"""
        payload = {"prompt": "New prompt instructions"}
        response = client.patch(f"/v1/prompts/{category}/{name}", headers=auth_headers["valid_auth"], json=payload)
        assert response.status_code == status_code
        if status_code == 200:
            data = response.json()
            assert data["name"] == name
            assert data["category"] == category
            assert data["prompt"] == "New prompt instructions"
        else:
            assert response.json() == {"detail": f"Prompt: {name} ({category}) not found."}

    @pytest.mark.parametrize("name, category, status_code", test_cases)
    def test_prompts_get_after(self, client, auth_headers, name, category, status_code):
        """Get individual prompts"""
        response = client.get(f"/v1/prompts/{category}/{name}", headers=auth_headers["valid_auth"])
        assert response.status_code == status_code
        if status_code == 200:
            response_data = response.json()
            assert response_data["prompt"] == "New prompt instructions"

    def test_prompts_list_after(self, client, auth_headers):
        """List boostrapped prompts"""
        response = client.get("/v1/prompts", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        response_data = response.json()
        assert all(item["prompt"] == "New prompt instructions" for item in response_data)
