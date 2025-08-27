"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from typing import get_args
import pytest
from common.schema import ModelProviders


#############################################################################
# Test AuthN required and Valid
#############################################################################
class TestInvalidAuthEndpoints:
    """Test endpoints without Headers and Invalid AuthN"""

    test_cases = []

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
            pytest.param("/v1/models/api", "get", id="models_list_api"),
            pytest.param("/v1/models", "get", id="models_list"),
            pytest.param("/v1/models/model_id", "get", id="models_get"),
            pytest.param("/v1/models/model_id", "patch", id="models_update"),
            pytest.param("/v1/models", "post", id="models_create"),
            pytest.param("/v1/models/model_id", "delete", id="models_delete"),
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

    def test_models_list_api(self, client, auth_headers):
        """Get a list of model APIs to use with tests"""
        response = client.get("/v1/models/provider", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        assert sorted(response.json()) == sorted(list(get_args(ModelProviders)))

    def test_models_get_before(self, client, auth_headers):
        """Retrieve each individual model"""
        all_models = client.get("/v1/models?include_disabled=true", headers=auth_headers["valid_auth"])
        assert len(all_models.json()) > 0
        for model in all_models.json():
            response = client.get(f"/v1/models/{model['id']}", headers=auth_headers["valid_auth"])
            assert response.status_code == 200

    def test_models_delete_add(self, client, auth_headers):
        """Delete and Re-Add Models"""
        all_models = client.get("/v1/models?include_disabled=true", headers=auth_headers["valid_auth"])
        assert len(all_models.json()) > 0

        # Delete all models
        for model in all_models.json():
            response = client.delete(f"/v1/models/{model['id']}", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            assert response.json() == {"message": f"Model: {model['id']} deleted."}
        # Check that no models exists
        deleted_models = client.get("/v1/models?include_disabled=true", headers=auth_headers["valid_auth"])
        assert len(deleted_models.json()) == 0

        # Delete a non-existent model
        response = client.delete("/v1/models/test_model", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        assert response.json() == {"message": "Model: test_model deleted."}

        # Add all models back
        for model in all_models.json():
            payload = model
            response = client.post("/v1/models", headers=auth_headers["valid_auth"], json=payload)
            assert response.status_code == 201
            assert response.json() == payload
        new_models = client.get("/v1/models?include_disabled=true", headers=auth_headers["valid_auth"])
        assert new_models.json() == all_models.json()

    def test_models_add_dupl(self, client, auth_headers):
        """Add Duplicate Models"""
        all_models = client.get("/v1/models?include_disabled=true", headers=auth_headers["valid_auth"])
        assert len(all_models.json()) > 0
        for model in all_models.json():
            payload = model
            response = client.post("/v1/models", headers=auth_headers["valid_auth"], json=payload)
            assert response.status_code == 409
            assert response.json() == {"detail": f"Model: {model['id']} already exists."}

    test_cases = [
        pytest.param(
            {
                "id": "valid_ll_model",
                "enabled": True,
                "type": "ll",
                "provider": "openai",
                "api_key": "test-key",
                "api_base": "https://api.openai.com/v1",
                "openai_compat": True,
                "context_length": 127072,
                "temperature": 1.0,
                "max_completion_tokens": 4096,
                "frequency_penalty": 0.0,
            },
            201,
            200,
            id="valid_ll_model",
        ),
        pytest.param(
            {
                "id": "invalid_ll_model",
                "enabled": False,
            },
            422,
            422,
            id="invalid_ll_model",
        ),
        pytest.param(
            {
                "id": "test_embed_model",
                "enabled": False,
                "type": "embed",
                "provider": "huggingface",
                "api_base": "http://127.0.0.1:8080",
                "api_key": "",
                "openai_compat": True,
                "max_chunk_size": 512,
            },
            201,
            422,
            id="valid_embed_model",
        ),
        pytest.param(
            {
                "id": "unreachable_api_base_model",
                "enabled": True,
                "type": "embed",
                "provider": "huggingface",
                "api_base": "http://127.0.0.1:112233",
                "api_key": "",
                "openai_compat": True,
                "max_chunk_size": 512,
            },
            201,
            422,
            id="unreachable_api_base_model",
        ),
    ]

    @pytest.mark.parametrize("payload, add_status_code, _", test_cases)
    def test_model_create(self, client, auth_headers, payload, add_status_code, _, request):
        """Create Models"""
        response = client.post("/v1/models", headers=auth_headers["valid_auth"], json=payload)
        assert response.status_code == add_status_code
        if add_status_code == 201:
            if request.node.callspec.id == "unreachable_api_base_model":
                assert response.json()["enabled"] is False
            else:
                assert all(item in response.json().items() for item in payload.items())
            # Model was added, should get 200 back
            response = client.get(f"/v1/models/{payload['id']}", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
        else:
            # Model wasn't added, should get a 404 back
            response = client.get(f"/v1/models/{payload['id']}", headers=auth_headers["valid_auth"])
            assert response.status_code == 404

    @pytest.mark.parametrize("payload, add_status_code, update_status_code", test_cases)
    def test_model_update(self, client, auth_headers, payload, add_status_code, update_status_code):
        """Update Models"""
        if add_status_code == 201:
            # Create the model when we know it will succeed
            _ = client.post("/v1/models", headers=auth_headers["valid_auth"], json=payload)
            response = client.get(f"/v1/models/{payload['id']}", headers=auth_headers["valid_auth"])
            old_enabled = response.json()["enabled"]
            # Switch up the enabled for the update
            payload["enabled"] = not old_enabled

            response = client.patch(f"/v1/models/{payload['id']}", headers=auth_headers["valid_auth"], json=payload)
            assert response.status_code == update_status_code
            if update_status_code == 200:
                new_enabled = response.json()["enabled"]
                assert new_enabled is not old_enabled
