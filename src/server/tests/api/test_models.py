"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for models endpoint.
"""
# pylint: disable=duplicate-code

import pytest

from server.app.models.schemas import ModelConfig, ModelSensitive
from server.app.core.settings import settings

SENSITIVE_KEYS = set(ModelSensitive.model_fields.keys())


@pytest.fixture(autouse=True)
def _populate_configs():
    """Inject test ModelConfig entries into settings."""
    original = settings.model_configs
    settings.model_configs = [
        ModelConfig(
            id="test-llm",
            type="ll",
            provider="openai",
            api_key="sk-secret-key",
            temperature=0.7,
        ),
        ModelConfig(
            id="test-embed",
            type="embed",
            provider="openai",
            api_key="sk-embed-key",
        ),
    ]
    yield
    settings.model_configs = original


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_models_no_auth(app_client):
    """Models endpoint rejects requests without API key."""
    resp = await app_client.get("/v1/models")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_models(app_client, auth_headers):
    """Default response returns all configs without sensitive fields."""
    resp = await app_client.get("/v1/models", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    for entry in body:
        for key in SENSITIVE_KEYS:
            assert key not in entry
        assert "id" in entry
        assert "provider" in entry


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_models_sensitive(app_client, auth_headers):
    """Response includes sensitive fields when include_sensitive=true."""
    resp = await app_client.get("/v1/models", params={"include_sensitive": "true"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["api_key"] == "sk-secret-key"
    assert body[1]["api_key"] == "sk-embed-key"


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_model(app_client, auth_headers):
    """Fetch a single model config by provider/id."""
    resp = await app_client.get("/v1/models/openai/test-llm", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "test-llm"
    assert body["provider"] == "openai"
    for key in SENSITIVE_KEYS:
        assert key not in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_model_not_found(app_client, auth_headers):
    """Return 404 for unknown provider/id."""
    resp = await app_client.get("/v1/models/openai/MISSING", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_model_case_insensitive(app_client, auth_headers):
    """Provider and model id lookup is case-insensitive."""
    resp = await app_client.get("/v1/models/OPENAI/TEST-LLM", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == "test-llm"


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_model_wrong_provider(app_client, auth_headers):
    """Return 404 when id exists but provider does not match."""
    resp = await app_client.get("/v1/models/anthropic/test-llm", headers=auth_headers)
    assert resp.status_code == 404


# --- POST /models ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_model(app_client, auth_headers):
    """POST new model returns 201 and config appears in list."""
    resp = await app_client.post(
        "/v1/models",
        json={"id": "new-model", "type": "ll", "provider": "anthropic"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == "new-model"
    assert body["provider"] == "anthropic"
    for key in SENSITIVE_KEYS:
        assert key not in body
    # Verify it appears in the list
    list_resp = await app_client.get("/v1/models", headers=auth_headers)
    model_ids = [(m["id"], m["provider"]) for m in list_resp.json()]
    assert ("new-model", "anthropic") in model_ids


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_model_duplicate(app_client, auth_headers):
    """POST existing (id, provider) returns 409."""
    resp = await app_client.post(
        "/v1/models",
        json={"id": "test-llm", "type": "ll", "provider": "openai"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_model_duplicate_case_insensitive(app_client, auth_headers):
    """POST 'TEST-LLM'/'OPENAI' when 'test-llm'/'openai' exists returns 409."""
    resp = await app_client.post(
        "/v1/models",
        json={"id": "TEST-LLM", "type": "ll", "provider": "OPENAI"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_model_same_id_different_provider(app_client, auth_headers):
    """POST same id with different provider succeeds (composite key)."""
    resp = await app_client.post(
        "/v1/models",
        json={"id": "test-llm", "type": "ll", "provider": "anthropic"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["provider"] == "anthropic"


# --- PUT /models/{provider}/{model_id} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_model(app_client, auth_headers):
    """PUT with new temperature returns 200 and field is changed."""
    resp = await app_client.put(
        "/v1/models/openai/test-llm",
        json={"temperature": 0.9},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["temperature"] == 0.9
    for key in SENSITIVE_KEYS:
        assert key not in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_model_not_found(app_client, auth_headers):
    """PUT unknown provider/id returns 404."""
    resp = await app_client.put(
        "/v1/models/openai/MISSING",
        json={"temperature": 0.5},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_model_partial(app_client, auth_headers):
    """PUT only one field leaves others unchanged."""
    resp = await app_client.put(
        "/v1/models/openai/test-llm",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["provider"] == "openai"  # unchanged


# --- DELETE /models/{provider}/{model_id} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_model(app_client, auth_headers):
    """DELETE removes config and returns 204."""
    resp = await app_client.delete("/v1/models/openai/test-llm", headers=auth_headers)
    assert resp.status_code == 204
    # Verify it's gone
    list_resp = await app_client.get("/v1/models", headers=auth_headers)
    model_ids = [(m["id"], m["provider"]) for m in list_resp.json()]
    assert ("test-llm", "openai") not in model_ids


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_model_not_found(app_client, auth_headers):
    """DELETE unknown provider/id returns 404."""
    resp = await app_client.delete("/v1/models/openai/MISSING", headers=auth_headers)
    assert resp.status_code == 404
