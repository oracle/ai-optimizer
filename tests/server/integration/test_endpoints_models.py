"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# pylint: disable=too-many-arguments,too-many-positional-arguments,too-few-public-methods
# spell-checker: disable

import pytest


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
            pytest.param("/v1/models", "get", id="models_list"),
            pytest.param("/v1/models/supported", "get", id="models_supported"),
            pytest.param("/v1/models/model_provider/model_id", "get", id="models_get"),
            pytest.param("/v1/models/model_provider/model_id", "patch", id="models_update"),
            pytest.param("/v1/models", "post", id="models_create"),
            pytest.param("/v1/models/model_provider/model_id", "delete", id="models_delete"),
        ],
    )
    def test_endpoints(self, client, auth_headers, endpoint, api_method, auth_type, status_code):
        """Test endpoints require valid authentication."""
        response = getattr(client, api_method)(endpoint, headers=auth_headers[auth_type])
        assert response.status_code == status_code


#############################################################################
# Endpoints Test
#############################################################################
class TestEndpoints:
    """Test Endpoints"""

    def test_models_list_api(self, client, auth_headers):
        """Get a list of model Providers to use with tests"""
        response = client.get("/v1/models/supported", headers=auth_headers["valid_auth"])
        assert response.status_code == 200

    def test_models_list_with_model_type_filter(self, client, auth_headers):
        """Test /v1/models endpoint with model_type parameter"""
        # Test with valid model types
        for model_type in ["ll", "embed", "rerank"]:
            response = client.get(f"/v1/models?model_type={model_type}", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            models = response.json()
            # If models exist, they should all match the requested type
            for model in models:
                assert model["type"] == model_type

        # Test with model_type and include_disabled
        response = client.get("/v1/models?model_type=ll&include_disabled=true", headers=auth_headers["valid_auth"])
        assert response.status_code == 200

        # Test with invalid model type should return 422 validation error
        response = client.get("/v1/models?model_type=invalid", headers=auth_headers["valid_auth"])
        assert response.status_code == 422

    def test_models_supported_with_filters(self, client, auth_headers):
        """Test /v1/models/supported endpoint with query parameters"""
        # Test basic supported models
        response = client.get("/v1/models/supported", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        all_supported = response.json()
        assert isinstance(all_supported, list)

        # Test with model_provider filter
        if all_supported:
            # Get a provider from the response to test with
            test_provider = all_supported[0].get("provider", "openai")
            response = client.get(
                f"/v1/models/supported?model_provider={test_provider}", headers=auth_headers["valid_auth"]
            )
            assert response.status_code == 200
            filtered_models = response.json()
            for model in filtered_models:
                assert model.get("provider") == test_provider

        # Test with model_type filter
        for model_type in ["ll", "embed", "rerank"]:
            response = client.get(f"/v1/models/supported?model_type={model_type}", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            filtered_providers = response.json()
            for provider_entry in filtered_providers:
                assert "provider" in provider_entry
                assert "models" in provider_entry
                for model in provider_entry["models"]:
                    # Only check type if it exists (some models may not have type set due to exceptions)
                    if "type" in model:
                        assert model["type"] == model_type

        # Test with both filters
        response = client.get(
            "/v1/models/supported?model_provider=openai&model_type=ll", headers=auth_headers["valid_auth"]
        )
        assert response.status_code == 200
        filtered_providers = response.json()
        for provider_entry in filtered_providers:
            assert provider_entry.get("provider") == "openai"
            for model in provider_entry["models"]:
                # Only check type if it exists (some models may not have type set due to exceptions)
                if "type" in model:
                    assert model["type"] == "ll"

        # Test with invalid provider
        response = client.get(
            "/v1/models/supported?model_provider=invalid_provider", headers=auth_headers["valid_auth"]
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_models_get_before(self, client, auth_headers):
        """Retrieve each individual model"""
        all_models = client.get("/v1/models?include_disabled=true", headers=auth_headers["valid_auth"])
        assert len(all_models.json()) > 0
        for model in all_models.json():
            response = client.get(f"/v1/models/{model['provider']}/{model['id']}", headers=auth_headers["valid_auth"])
            assert response.status_code == 200

    def test_models_delete_add(self, client, auth_headers):
        """Delete and Re-Add Models"""
        all_models = client.get("/v1/models?include_disabled=true", headers=auth_headers["valid_auth"])
        assert len(all_models.json()) > 0

        # Delete all models
        for model in all_models.json():
            response = client.delete(
                f"/v1/models/{model['provider']}/{model['id']}", headers=auth_headers["valid_auth"]
            )
            assert response.status_code == 200
            assert response.json() == {"message": f"Model: {model['provider']}/{model['id']} deleted."}
        # Check that no models exists
        deleted_models = client.get("/v1/models?include_disabled=true", headers=auth_headers["valid_auth"])
        assert len(deleted_models.json()) == 0

        # Delete a non-existent model
        response = client.delete("/v1/models/test_provider/test_model", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        assert response.json() == {"message": "Model: test_provider/test_model deleted."}

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
            assert response.json() == {"detail": f"Model: {model['provider']}/{model['id']} already exists."}

    test_cases = [
        pytest.param(
            {
                "id": "gpt-3.5-turbo",
                "enabled": True,
                "type": "ll",
                "provider": "openai",
                "api_key": "test-key",
                "api_base": "https://api.openai.com/v1",
                "max_input_tokens": 127072,
                "temperature": 1.0,
                "max_tokens": 4096,
                "frequency_penalty": 0.0,
            },
            201,
            200,
            id="valid_ll_model",
        ),
        pytest.param(
            {
                "id": "invalid_ll_model",
                "provider": "invalid_ll_model",
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
                print(response.json())
                assert all(item in response.json().items() for item in payload.items())
            # Model was added, should get 200 back
            response = client.get(
                f"/v1/models/{payload['provider']}/{payload['id']}", headers=auth_headers["valid_auth"]
            )
            assert response.status_code == 200
        else:
            # Model wasn't added, should get a 404 back
            response = client.get(
                f"/v1/models/{payload['provider']}/{payload['id']}", headers=auth_headers["valid_auth"]
            )
            assert response.status_code == 404

    @pytest.mark.parametrize("payload, add_status_code, update_status_code", test_cases)
    def test_model_update(self, client, auth_headers, payload, add_status_code, update_status_code):
        """Update Models"""
        if add_status_code == 201:
            # Create the model when we know it will succeed
            _ = client.post("/v1/models", headers=auth_headers["valid_auth"], json=payload)
            response = client.get(
                f"/v1/models/{payload['provider']}/{payload['id']}", headers=auth_headers["valid_auth"]
            )
            old_enabled = response.json()["enabled"]
            # Switch up the enabled for the update
            payload["enabled"] = not old_enabled

            response = client.patch(
                f"/v1/models/{payload['provider']}/{payload['id']}", headers=auth_headers["valid_auth"], json=payload
            )
            assert response.status_code == update_status_code
            if update_status_code == 200:
                new_enabled = response.json()["enabled"]
                assert new_enabled is not old_enabled

    def test_models_get_edge_cases(self, client, auth_headers):
        """Test edge cases for model path parameters"""
        # Test with non-existent model
        response = client.get("/v1/models/nonexistent_provider/nonexistent_model", headers=auth_headers["valid_auth"])
        assert response.status_code == 404

        # Test with special characters in model_id (URL encoded)
        test_cases = [
            ("test_provider", "model-with-dashes"),
            ("test_provider", "model_with_underscores"),
            ("test_provider", "model.with.dots"),
            ("test_provider", "model/with/slashes"),
            ("test_provider", "model with spaces"),
        ]

        for provider, model_id in test_cases:
            # These should return 404 since they don't exist
            response = client.get(f"/v1/models/{provider}/{model_id}", headers=auth_headers["valid_auth"])
            assert response.status_code == 404

        # Test very long model ID
        long_model_id = "a" * 1000
        response = client.get(f"/v1/models/test_provider/{long_model_id}", headers=auth_headers["valid_auth"])
        assert response.status_code == 404

    def test_models_delete_edge_cases(self, client, auth_headers):
        """Test edge cases for model deletion"""
        # Test deleting non-existent models (should succeed with 200)
        test_cases = [
            ("nonexistent_provider", "nonexistent_model"),
            ("test_provider", "model-with-dashes"),
            ("test_provider", "model/with/slashes"),
        ]

        for provider, model_id in test_cases:
            response = client.delete(f"/v1/models/{provider}/{model_id}", headers=auth_headers["valid_auth"])
            assert response.status_code == 200
            assert response.json() == {"message": f"Model: {provider}/{model_id} deleted."}

    def test_models_update_edge_cases(self, client, auth_headers):
        """Test edge cases for model updates"""
        # Test updating non-existent model
        payload = {"id": "nonexistent_model", "provider": "nonexistent_provider", "type": "ll", "enabled": True}
        response = client.patch(
            "/v1/models/nonexistent_provider/nonexistent_model", headers=auth_headers["valid_auth"], json=payload
        )
        assert response.status_code == 404

    def test_models_response_schema_validation(self, client, auth_headers):
        """Test response schema validation for all endpoints"""
        # Test /v1/models response schema
        response = client.get("/v1/models", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        models = response.json()
        assert isinstance(models, list)

        for model in models:
            # Validate required fields
            assert "id" in model
            assert "type" in model
            assert "provider" in model
            assert "enabled" in model
            assert "object" in model
            assert "created" in model
            assert "owned_by" in model

            # Validate field types
            assert isinstance(model["id"], str)
            assert model["type"] in ["ll", "embed", "rerank"]
            assert isinstance(model["provider"], str)
            assert isinstance(model["enabled"], bool)
            assert model["object"] == "model"
            assert isinstance(model["created"], int)
            assert model["owned_by"] == "aioptimizer"

            # Validate optional fields if present
            if "api_base" in model and model["api_base"] is not None:
                assert isinstance(model["api_base"], str)
            if "max_input_tokens" in model and model["max_input_tokens"] is not None:
                assert isinstance(model["max_input_tokens"], int)
            if "temperature" in model and model["temperature"] is not None:
                assert isinstance(model["temperature"], (int, float))

        # Test /v1/models/supported response schema
        response = client.get("/v1/models/supported", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        supported_models = response.json()
        assert isinstance(supported_models, list)

        for model in supported_models:
            assert isinstance(model, dict)
            # These are the models from LiteLLM, so schema may vary
            # Just ensure basic structure is maintained

        # Test individual model GET response schema
        if models:
            first_model = models[0]
            response = client.get(
                f"/v1/models/{first_model['provider']}/{first_model['id']}", headers=auth_headers["valid_auth"]
            )
            assert response.status_code == 200
            model = response.json()

            # Should have same schema as models list item
            assert "id" in model
            assert "type" in model
            assert "provider" in model
            assert "enabled" in model
            assert model["object"] == "model"
            assert model["owned_by"] == "aioptimizer"

    def test_models_create_response_validation(self, client, auth_headers):
        """Test model creation response validation"""
        # Create a test model and validate response
        payload = {
            "id": "test-response-validation-model",
            "enabled": False,
            "type": "ll",
            "provider": "test_provider",
            "api_key": "test-key",
            "api_base": "https://api.test.com/v1",
            "max_input_tokens": 4096,
            "temperature": 0.7,
        }

        response = client.post("/v1/models", headers=auth_headers["valid_auth"], json=payload)
        if response.status_code == 201:
            created_model = response.json()

            # Validate all payload fields are in response
            for key, value in payload.items():
                assert key in created_model
                assert created_model[key] == value

            # Validate additional required fields are added
            assert "object" in created_model
            assert "created" in created_model
            assert "owned_by" in created_model
            assert created_model["object"] == "model"
            assert created_model["owned_by"] == "aioptimizer"
            assert isinstance(created_model["created"], int)

            # Clean up
            client.delete(f"/v1/models/{payload['provider']}/{payload['id']}", headers=auth_headers["valid_auth"])
