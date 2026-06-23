"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for models endpoint.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from server.app.core.settings import settings
from server.app.models.schemas import ModelConfig, ModelSensitive
from server.tests.conftest import assert_no_sensitive_keys

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
            api_key=SecretStr("sk-secret-key"),
            temperature=0.7,
        ),
        ModelConfig(
            id="test-embed",
            type="embed",
            provider="openai",
            api_key=SecretStr("sk-embed-key"),
        ),
    ]
    yield
    settings.model_configs = original


@pytest.fixture(autouse=True)
def mock_persist_settings():
    """Prevent persist_settings from doing real DB I/O in every test."""
    with patch("server.app.api.v1.endpoints.models.persist_settings", new_callable=AsyncMock) as mock_persist:
        yield mock_persist


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
    assert_no_sensitive_keys(body, SENSITIVE_KEYS, "id")


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_models_uses_standard_projection(app_client, auth_headers):
    """The list endpoint uses the standard projection when extra params are present."""
    resp = await app_client.get("/v1/models", params={"include_sensitive": "true"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert_no_sensitive_keys(body, SENSITIVE_KEYS, "id")


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


# --- GET /models/supported ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_models_supported(app_client, auth_headers):
    """GET /models/supported returns 200 and a list of provider dicts."""
    resp = await app_client.get("/v1/models/supported", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) > 0
    # Each entry should have provider and ids keys
    for entry in body:
        assert "provider" in entry
        assert "ids" in entry
        assert isinstance(entry["ids"], list)


@pytest.mark.unit
@pytest.mark.anyio
async def test_models_supported_filter_type(app_client, auth_headers):
    """GET /models/supported with model_type=ll filters to chat/completion models."""
    resp = await app_client.get("/v1/models/supported", params={"model_type": "ll"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    # Verify that any returned model entries have type "ll" (if they have a type field)
    for entry in body:
        for model in entry["ids"]:
            if "type" in model:
                assert model["type"] == "ll"


# --- Auth tests for mutating endpoints ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_model_no_auth(app_client):
    """POST without auth returns 403."""
    resp = await app_client.post("/v1/models", json={"id": "x", "type": "ll", "provider": "y"})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_model_no_auth(app_client):
    """PUT without auth returns 403."""
    resp = await app_client.put("/v1/models/openai/test-llm", json={"temperature": 0.5})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_model_no_auth(app_client):
    """DELETE without auth returns 403."""
    resp = await app_client.delete("/v1/models/openai/test-llm")
    assert resp.status_code == 403


# --- Sensitive fields ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_model_alternate_projection(app_client, auth_headers):
    """Fetch the alternate projection for a single model."""
    resp = await app_client.get(
        "/v1/models/openai/test-llm",
        params={"include_sensitive": "true"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["api_key"] == "sk-secret-key"


# --- Update edge cases ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_model_provider_change_duplicate(app_client, auth_headers):
    """PUT changing provider to create duplicate composite key returns 409."""
    # Add a model with provider "anthropic" and same id "test-llm"
    settings.model_configs.append(ModelConfig(id="test-llm", type="ll", provider="anthropic"))
    resp = await app_client.put(
        "/v1/models/openai/test-llm",
        json={"provider": "anthropic"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_model_case_insensitive(app_client, auth_headers):
    """PUT with uppercased provider/id returns 200."""
    resp = await app_client.put(
        "/v1/models/OPENAI/TEST-LLM",
        json={"temperature": 0.3},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["temperature"] == 0.3


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_model_case_insensitive(app_client, auth_headers):
    """DELETE with uppercased provider/id returns 204."""
    resp = await app_client.delete("/v1/models/OPENAI/TEST-LLM", headers=auth_headers)
    assert resp.status_code == 204


# --- persist_settings verification ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_model_persists_settings(app_client, auth_headers, mock_persist_settings):
    """POST calls persist_settings after successful creation."""
    resp = await app_client.post(
        "/v1/models",
        json={"id": "persist-model", "type": "ll", "provider": "anthropic"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    mock_persist_settings.assert_called_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_model_persists_settings(app_client, auth_headers, mock_persist_settings):
    """PUT calls persist_settings after successful update."""
    resp = await app_client.put(
        "/v1/models/openai/test-llm",
        json={"temperature": 0.1},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    mock_persist_settings.assert_called_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_model_persists_settings(app_client, auth_headers, mock_persist_settings):
    """DELETE calls persist_settings after successful deletion."""
    resp = await app_client.delete("/v1/models/openai/test-llm", headers=auth_headers)
    assert resp.status_code == 204
    mock_persist_settings.assert_called_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_model_persist_fails_restores_usable(app_client, auth_headers, mock_persist_settings):
    """PUT persist failure restores usable and enabled flags to pre-check state."""
    cfg = settings.model_configs[0]
    cfg.usable = True
    cfg.enabled = True

    mock_persist_settings.return_value = False

    async def fake_check(model):
        model.usable = False

    with patch("server.app.api.v1.endpoints.models.check_single_model", side_effect=fake_check):
        resp = await app_client.put(
            "/v1/models/openai/test-llm",
            json={"temperature": 0.1},
            headers=auth_headers,
        )

    assert resp.status_code == 503
    assert cfg.usable is True
    assert cfg.enabled is True
    assert cfg.temperature == 0.7  # user field also restored


# --- Supported models filter by provider ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_models_supported_filter_provider(app_client, auth_headers):
    """GET /models/supported?model_provider=openai filters by provider."""
    resp = await app_client.get("/v1/models/supported", params={"model_provider": "openai"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    # Only the openai entry should have non-empty ids (others have empty ids)

    providers_with_ids = [e["provider"] for e in body if e["ids"]]
    if providers_with_ids:
        assert all(p == "openai" for p in providers_with_ids)


@pytest.mark.unit
@pytest.mark.anyio
async def test_models_supported_does_no_per_model_io(app_client, auth_headers):
    """The supported list must be built from the static cost map, not the
    network/auth-triggering ``get_model_info``/``get_llm_provider`` helpers
    (iterating those blocked the endpoint past the client read timeout)."""

    def _boom(*_args, **_kwargs):
        raise AssertionError("per-model litellm I/O path must not be called")

    with (
        patch("litellm.get_model_info", side_effect=_boom),
        patch("litellm.get_llm_provider", side_effect=_boom),
    ):
        resp = await app_client.get("/v1/models/supported", params={"model_type": "ll"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    # Still populated, and entries carry the key the client UI indexes on.
    all_ids = [entry for provider in body for entry in provider["ids"]]
    assert all_ids
    assert all("key" in entry for entry in all_ids)


@pytest.mark.unit
@pytest.mark.anyio
async def test_models_supported_covers_embed_and_rerank(app_client, auth_headers):
    """The static map exposes embed and rerank models, not just chat."""
    for model_type in ("embed", "rerank"):
        resp = await app_client.get("/v1/models/supported", params={"model_type": model_type}, headers=auth_headers)
        assert resp.status_code == 200
        typed = [e for prov in resp.json() for e in prov["ids"] if e.get("type") == model_type]
        assert typed, f"no {model_type} models returned"


class TestFindModel:
    """Cover _find_model early-return cases."""

    def test_returns_none_for_missing_inputs(self):
        """None provider or id returns None immediately."""
        from server.app.api.v1.endpoints import models as mod

        assert mod._find_model(None, "id") is None
        assert mod._find_model("provider", None) is None
