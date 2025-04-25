"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable
# pylint: disable=import-error

from typing import Any, Dict, get_args
import pytest
from fastapi.testclient import TestClient
from conftest import TEST_HEADERS, TEST_BAD_HEADERS
from common.schema import LlAPI, EmbedAPI


#############################################################################
# Test AuthN required and Valid
#############################################################################
class TestNoAuthEndpoints:
    """Test endpoints without AuthN"""

    test_cases = [
        pytest.param(
            {"endpoint": "/v1/models", "method": "get"},
            id="models_list",
        ),
        pytest.param(
            {"endpoint": "/v1/models/model_name", "method": "get"},
            id="models_get",
        ),
        pytest.param(
            {"endpoint": "/v1/models/model_name", "method": "patch"},
            id="models_update",
        ),
        pytest.param(
            {"endpoint": "/v1/models", "method": "post"},
            id="models_create",
        ),
        pytest.param(
            {"endpoint": "/v1/models/model_name", "method": "delete"},
            id="models_delete",
        ),
    ]

    @pytest.mark.parametrize("test_case", test_cases)
    def test_no_auth(self, client: TestClient, test_case: Dict[str, Any]) -> None:
        """Testing for required AuthN"""
        response = getattr(client, test_case["method"])(test_case["endpoint"])
        assert response.status_code == 403
        response = getattr(client, test_case["method"])(test_case["endpoint"], headers=TEST_BAD_HEADERS)
        assert response.status_code == 401


#############################################################################
# Test AuthN
#############################################################################
class TestEndpoints:
    """Test endpoints with AuthN"""

    @pytest.mark.parametrize(
        "model_type,expected",
        [
            ("ll", list(get_args(LlAPI))),
            ("embed", list(get_args(EmbedAPI))),
            (None, []),
        ],
    )
    def test_models_list_api(self, client: TestClient, model_type, expected):
        """Get a list of model APIs to use with tests"""
        params = {"model_type": model_type} if model_type else {}
        response = client.get("/v1/models/api", headers=TEST_HEADERS, params=params)
        assert response.status_code == 200
        assert sorted(response.json()) == sorted(expected)

    def models_list(self, client: TestClient):
        """Get a list of bootstrapped models to use with tests"""
        response = client.get("/v1/models", headers=TEST_HEADERS)
        return response.json()

    def test_models_get_before(self, client: TestClient):
        """Retrieve each individual model"""
        all_models = self.models_list(client)
        assert len(all_models) > 0
        for model in all_models:
            response = client.get(f"/v1/models/{model['name']}", headers=TEST_HEADERS)
            assert response.status_code == 200

    def test_models_delete_add(self, client: TestClient):
        """Delete and Re-Add Models"""
        all_models = self.models_list(client)
        assert len(all_models) > 0

        # Delete all models
        for model in all_models:
            response = client.delete(f"/v1/models/{model['name']}", headers=TEST_HEADERS)
            assert response.status_code == 200
            assert response.json() == {"message": f"Model: {model['name']} deleted."}
        # Check that no models exists
        deleted_models = self.models_list(client)
        assert len(deleted_models) == 0

        # Delete a non-existent model
        response = client.delete("/v1/models/test_model", headers=TEST_HEADERS)
        assert response.status_code == 200
        assert response.json() == {"message": "Model: test_model deleted."}

        # Add all models back
        for model in all_models:
            payload = model
            response = client.post("/v1/models", json=payload, headers=TEST_HEADERS)
            assert response.status_code == 200
            assert response.json() == payload
        new_models = self.models_list(client)
        assert new_models == all_models

    def test_models_add_dupl(self, client: TestClient):
        """Add Duplicate Models"""
        all_models = self.models_list(client)
        assert len(all_models) > 0
        for model in all_models:
            payload = model
            response = client.post("/v1/models", json=payload, headers=TEST_HEADERS)
            assert response.status_code == 409
            assert response.json() == {"detail": f"Model: {model['name']} already exists."}

    test_cases = [
        pytest.param(
            {
                "payload": {
                    "name": "valid_ll_model",
                    "enabled": False,
                    "type": "ll",
                    "api": "OpenAI",
                    "api_key": "test-key",
                    "openai_compat": True,
                    "url": "https://api.openai.com",
                    "context_length": 127072,
                    "temperature": 1.0,
                    "max_completion_tokens": 4096,
                    "frequency_penalty": 0.0,
                },
                "status_code": 200,
            },
            id="valid_ll_model",
        ),
        pytest.param(
            {
                "payload": {
                    "name": "invalid_ll_model",
                    "enabled": False,
                },
                "status_code": 422,
            },
            id="invalid_ll_model",
        ),
        pytest.param(
            {
                "payload": {
                    "name": "test_embed_model",
                    "enabled": False,
                    "type": "embed",
                    "api": "HuggingFaceEndpointEmbeddings",
                    "url": "http://127.0.0.1:8080",
                    "api_key": "",
                    "openai_compat": True,
                    "max_chunk_size": 512,
                },
                "status_code": 200,
            },
            id="valid_embed_model",
        ),
    ]

    @pytest.mark.parametrize("test_case", test_cases)
    def test_model_create(self, client: TestClient, test_case: Dict[str, Any]):
        """Create Models"""
        response = client.post("/v1/models", json=test_case["payload"], headers=TEST_HEADERS)
        if test_case["status_code"] == 200:
            assert response.status_code == 200
            assert all(item in response.json().items() for item in test_case["payload"].items())
            response = client.get(f"/v1/models/{test_case['payload']['name']}", headers=TEST_HEADERS)
            assert response.status_code == 200
        else:
            assert response.status_code == test_case["status_code"]
            response = client.get(f"/v1/models/{test_case['payload']['name']}", headers=TEST_HEADERS)
            assert response.status_code == 404

    @pytest.mark.parametrize("test_case", test_cases)
    def test_model_update(self, client: TestClient, test_case: Dict[str, Any]):
        """Create Models"""
        if test_case["status_code"] != 200:
            return

        response = client.get(f"/v1/models/{test_case['payload']['name']}", headers=TEST_HEADERS)
        old_enabled = response.json()["enabled"]
        test_case["payload"]["enabled"] = not old_enabled

        response = client.patch(
            f"/v1/models/{test_case['payload']['name']}", json=test_case["payload"], headers=TEST_HEADERS
        )
        assert response.status_code == 200
        new_enabled = response.json()["enabled"]
        assert new_enabled is not old_enabled
