"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/api/v1/models.py

Tests the model configuration endpoints through the full API stack.
These endpoints require authentication.
"""


class TestAuthentication:
    """Integration tests for authentication on model endpoints."""

    def test_models_list_requires_auth(self, client):
        """GET /v1/models should require authentication."""
        response = client.get("/v1/models")

        assert response.status_code == 401

    def test_models_list_rejects_invalid_token(self, client, auth_headers):
        """GET /v1/models should reject invalid tokens."""
        response = client.get("/v1/models", headers=auth_headers["invalid_auth"])

        assert response.status_code == 401

    def test_models_list_accepts_valid_token(self, client, auth_headers):
        """GET /v1/models should accept valid tokens."""
        response = client.get("/v1/models", headers=auth_headers["valid_auth"])

        assert response.status_code == 200


class TestModelsList:
    """Integration tests for the models list endpoint."""

    def test_models_list_returns_list(self, client, auth_headers):
        """GET /v1/models should return a list of models."""
        response = client.get("/v1/models", headers=auth_headers["valid_auth"])

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_models_list_returns_enabled_only_by_default(self, client, auth_headers):
        """GET /v1/models should return only enabled models by default."""
        response = client.get("/v1/models", headers=auth_headers["valid_auth"])

        data = response.json()
        for model in data:
            assert model["enabled"] is True

    def test_models_list_with_include_disabled(self, client, auth_headers):
        """GET /v1/models?include_disabled=true should include disabled models."""
        response = client.get(
            "/v1/models",
            headers=auth_headers["valid_auth"],
            params={"include_disabled": True},
        )

        assert response.status_code == 200
        data = response.json()
        # Should have at least some models (bootstrap loads defaults)
        assert isinstance(data, list)

    def test_models_list_filter_by_type_ll(self, client, auth_headers):
        """GET /v1/models?model_type=ll should return only LL models."""
        response = client.get(
            "/v1/models",
            headers=auth_headers["valid_auth"],
            params={"model_type": "ll", "include_disabled": True},
        )

        assert response.status_code == 200
        data = response.json()
        for model in data:
            assert model["type"] == "ll"

    def test_models_list_filter_by_type_embed(self, client, auth_headers):
        """GET /v1/models?model_type=embed should return only embed models."""
        response = client.get(
            "/v1/models",
            headers=auth_headers["valid_auth"],
            params={"model_type": "embed", "include_disabled": True},
        )

        assert response.status_code == 200
        data = response.json()
        for model in data:
            assert model["type"] == "embed"


class TestModelsSupported:
    """Integration tests for the supported models endpoint."""

    def test_models_supported_returns_list(self, client, auth_headers):
        """GET /v1/models/supported should return supported providers."""
        response = client.get("/v1/models/supported", headers=auth_headers["valid_auth"])

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_models_supported_filter_by_provider(self, client, auth_headers):
        """GET /v1/models/supported?model_provider=openai should filter by provider."""
        response = client.get(
            "/v1/models/supported",
            headers=auth_headers["valid_auth"],
            params={"model_provider": "openai"},
        )

        assert response.status_code == 200
        data = response.json()
        for item in data:
            assert item.get("provider") == "openai"

    def test_models_supported_filter_by_type(self, client, auth_headers):
        """GET /v1/models/supported?model_type=ll should filter by type."""
        response = client.get(
            "/v1/models/supported",
            headers=auth_headers["valid_auth"],
            params={"model_type": "ll"},
        )

        assert response.status_code == 200
        data = response.json()
        # Response is a list of provider objects with provider and models keys
        assert isinstance(data, list)
        # Each item should have provider and models keys
        for item in data:
            assert "provider" in item
            assert "models" in item


class TestModelsGet:
    """Integration tests for the single model get endpoint."""

    def test_models_get_requires_auth(self, client):
        """GET /v1/models/{provider}/{id} should require authentication."""
        response = client.get("/v1/models/openai/gpt-4o-mini")

        assert response.status_code == 401

    def test_models_get_returns_404_for_unknown(self, client, auth_headers):
        """GET /v1/models/{provider}/{id} should return 404 for unknown model."""
        response = client.get(
            "/v1/models/nonexistent/nonexistent-model",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 404

    def test_models_get_returns_model(self, client, auth_headers, model_objects_manager, make_model):
        """GET /v1/models/{provider}/{id} should return the specified model."""
        # Add a test model
        test_model = make_model(id="integration-test-model")
        model_objects_manager.append(test_model)

        response = client.get(
            "/v1/models/openai/integration-test-model",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "integration-test-model"
        assert data["provider"] == "openai"


class TestModelsCreate:
    """Integration tests for the model create endpoint."""

    def test_models_create_requires_auth(self, client):
        """POST /v1/models should require authentication."""
        response = client.post(
            "/v1/models",
            json={"id": "test-model", "type": "ll", "provider": "openai", "enabled": True},
        )

        assert response.status_code == 401

    def test_models_create_success(self, client, auth_headers, model_objects_manager):
        """POST /v1/models should create a new model."""
        # pylint: disable=unused-argument
        response = client.post(
            "/v1/models",
            headers=auth_headers["valid_auth"],
            json={"id": "new-test-model", "type": "ll", "provider": "openai", "enabled": True},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "new-test-model"
        assert data["provider"] == "openai"

    def test_models_create_returns_409_for_duplicate(self, client, auth_headers, model_objects_manager, make_model):
        """POST /v1/models should return 409 for duplicate model."""
        # Add existing model
        existing_model = make_model(id="duplicate-model")
        model_objects_manager.append(existing_model)

        response = client.post(
            "/v1/models",
            headers=auth_headers["valid_auth"],
            json={"id": "duplicate-model", "type": "ll", "provider": "openai", "enabled": True},
        )

        assert response.status_code == 409


class TestModelsUpdate:
    """Integration tests for the model update endpoint."""

    def test_models_update_requires_auth(self, client):
        """PATCH /v1/models/{provider}/{id} should require authentication."""
        response = client.patch(
            "/v1/models/openai/test-model",
            json={"id": "test-model", "type": "ll", "provider": "openai", "enabled": False},
        )

        assert response.status_code == 401

    def test_models_update_returns_404_for_unknown(self, client, auth_headers):
        """PATCH /v1/models/{provider}/{id} should return 404 for unknown model."""
        response = client.patch(
            "/v1/models/nonexistent/nonexistent-model",
            headers=auth_headers["valid_auth"],
            json={"id": "nonexistent-model", "type": "ll", "provider": "nonexistent", "enabled": False},
        )

        assert response.status_code == 404

    def test_models_update_success(self, client, auth_headers, model_objects_manager, make_model):
        """PATCH /v1/models/{provider}/{id} should update the model."""
        # Add a test model
        test_model = make_model(id="update-test-model")
        model_objects_manager.append(test_model)

        response = client.patch(
            "/v1/models/openai/update-test-model",
            headers=auth_headers["valid_auth"],
            json={"id": "update-test-model", "type": "ll", "provider": "openai", "enabled": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False


class TestModelsDelete:
    """Integration tests for the model delete endpoint."""

    def test_models_delete_requires_auth(self, client):
        """DELETE /v1/models/{provider}/{id} should require authentication."""
        response = client.delete("/v1/models/openai/test-model")

        assert response.status_code == 401

    def test_models_delete_success(self, client, auth_headers, model_objects_manager, make_model):
        """DELETE /v1/models/{provider}/{id} should delete the model."""
        # Add a test model to delete
        test_model = make_model(id="delete-test-model")
        model_objects_manager.append(test_model)

        response = client.delete(
            "/v1/models/openai/delete-test-model",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()

    def test_models_delete_nonexistent_succeeds(self, client, auth_headers):
        """DELETE /v1/models/{provider}/{id} should succeed for non-existent model."""
        response = client.delete(
            "/v1/models/test_provider/nonexistent_model",
            headers=auth_headers["valid_auth"],
        )

        assert response.status_code == 200
        assert response.json() == {"message": "Model: test_provider/nonexistent_model deleted."}


class TestModelsValidation:
    """Integration tests for model validation and edge cases."""

    def test_models_list_invalid_type_returns_422(self, client, auth_headers):
        """GET /v1/models?model_type=invalid should return 422 validation error."""
        response = client.get("/v1/models?model_type=invalid", headers=auth_headers["valid_auth"])
        assert response.status_code == 422

    def test_models_supported_invalid_provider_returns_empty(self, client, auth_headers):
        """GET /v1/models/supported?model_provider=invalid returns empty list."""
        response = client.get(
            "/v1/models/supported?model_provider=invalid_provider",
            headers=auth_headers["valid_auth"],
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_models_update_max_chunk_size(self, client, auth_headers, model_objects_manager):
        """Test updating max_chunk_size for embedding models (regression test)."""
        # pylint: disable=unused-argument
        # Create an embedding model with default max_chunk_size
        payload = {
            "id": "test-embed-chunk-size",
            "enabled": False,
            "type": "embed",
            "provider": "test_provider",
            "api_base": "http://127.0.0.1:11434",
            "max_chunk_size": 8192,
        }

        # Create the model
        response = client.post("/v1/models", headers=auth_headers["valid_auth"], json=payload)
        assert response.status_code == 201
        assert response.json()["max_chunk_size"] == 8192

        # Update the max_chunk_size to 512
        payload["max_chunk_size"] = 512
        response = client.patch(
            f"/v1/models/{payload['provider']}/{payload['id']}", headers=auth_headers["valid_auth"], json=payload
        )
        assert response.status_code == 200
        assert response.json()["max_chunk_size"] == 512

        # Verify the update persists by fetching the model again
        response = client.get(f"/v1/models/{payload['provider']}/{payload['id']}", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        assert response.json()["max_chunk_size"] == 512

        # Update to a different value to ensure it's not cached
        payload["max_chunk_size"] = 1024
        response = client.patch(
            f"/v1/models/{payload['provider']}/{payload['id']}", headers=auth_headers["valid_auth"], json=payload
        )
        assert response.status_code == 200
        assert response.json()["max_chunk_size"] == 1024

        # Verify again
        response = client.get(f"/v1/models/{payload['provider']}/{payload['id']}", headers=auth_headers["valid_auth"])
        assert response.status_code == 200
        assert response.json()["max_chunk_size"] == 1024

        # Clean up
        client.delete(f"/v1/models/{payload['provider']}/{payload['id']}", headers=auth_headers["valid_auth"])

    def test_models_response_schema_validation(self, client, auth_headers):
        """Test response schema validation for models list."""
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

    def test_models_create_response_validation(self, client, auth_headers, model_objects_manager):
        """Test model creation response validation."""
        # pylint: disable=unused-argument
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
