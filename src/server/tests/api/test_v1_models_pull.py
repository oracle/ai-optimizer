"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the POST /v1/models/pull/{provider}/{model_id} endpoint.
"""
# spell-checker: disable

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from server.app.core.settings import settings
from server.app.models.schemas import ModelConfig

OLLAMA_URL = "http://localhost:11434"


@pytest.fixture(autouse=True)
def _populate_configs():
    """Inject test ModelConfig entries including an Ollama model."""
    original = settings.model_configs
    settings.model_configs = [
        ModelConfig(
            id="qwen3:8b",
            type="ll",
            provider="ollama",
            api_base=OLLAMA_URL,
        ),
        ModelConfig(
            id="test-llm",
            type="ll",
            provider="openai",
            api_key=SecretStr("sk-secret"),
        ),
        ModelConfig(
            id="no-base",
            type="ll",
            provider="ollama",
        ),
    ]
    yield
    settings.model_configs = original


@pytest.fixture(autouse=True)
def mock_persist_settings():
    """Prevent persist_settings from doing real DB I/O."""
    with patch("server.app.api.v1.endpoints.models.persist_settings", new_callable=AsyncMock, return_value=True):
        yield


async def _collect_ndjson(response) -> list[dict]:
    """Collect parsed NDJSON events from a streaming response."""
    events = []
    async for line in response.aiter_lines():
        stripped = line.strip()
        if stripped:
            events.append(json.loads(stripped))
    return events


async def _fake_pull_success(*_args, **_kwargs):
    yield {"status": "pulling manifest"}
    yield {"status": "downloading", "completed": 500, "total": 1000}
    yield {"status": "downloading", "completed": 1000, "total": 1000}


async def _fake_pull_error(*_args, **_kwargs):
    yield {"status": "pulling manifest"}
    yield {"error": "model not found"}


# --- Happy path ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_pull_model_streams_progress(app_client, auth_headers):
    """POST pull returns 200 and streams NDJSON progress."""
    with patch("server.app.api.v1.endpoints.models.pull_ollama_model", side_effect=_fake_pull_success):
        resp = await app_client.post("/v1/models/pull/ollama/qwen3:8b", headers=auth_headers)

    assert resp.status_code == 200
    assert "application/x-ndjson" in resp.headers["content-type"]

    events = await _collect_ndjson(resp)
    statuses = [e.get("status") for e in events]
    assert "pulling manifest" in statuses
    assert "success" in statuses


@pytest.mark.unit
@pytest.mark.anyio
async def test_pull_model_calls_check_and_persist(app_client, auth_headers):
    """After successful pull, check_single_model and persist_settings are called."""
    with (
        patch("server.app.api.v1.endpoints.models.pull_ollama_model", side_effect=_fake_pull_success),
        patch("server.app.api.v1.endpoints.models.check_single_model", new_callable=AsyncMock) as mock_check,
        patch(
            "server.app.api.v1.endpoints.models.persist_settings", new_callable=AsyncMock, return_value=True
        ) as mock_persist,
    ):
        resp = await app_client.post("/v1/models/pull/ollama/qwen3:8b", headers=auth_headers)
        # Consume the stream to trigger the post-pull logic
        _ = await _collect_ndjson(resp)

    mock_check.assert_called_once()
    mock_persist.assert_called_once()


# --- Persist failure ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_pull_model_persist_failure_emits_error(app_client, auth_headers):
    """When persist_settings returns False, an error event is emitted instead of success."""
    with (
        patch("server.app.api.v1.endpoints.models.pull_ollama_model", side_effect=_fake_pull_success),
        patch("server.app.api.v1.endpoints.models.check_single_model", new_callable=AsyncMock),
        patch("server.app.api.v1.endpoints.models.persist_settings", new_callable=AsyncMock, return_value=False),
    ):
        resp = await app_client.post("/v1/models/pull/ollama/qwen3:8b", headers=auth_headers)

    events = await _collect_ndjson(resp)
    statuses = [e.get("status") for e in events]
    assert "success" not in statuses
    assert any("error" in e for e in events)
    assert any("persist" in e.get("error", "").lower() for e in events if "error" in e)


# --- Error from Ollama ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_pull_model_error_no_success_event(app_client, auth_headers):
    """When Ollama returns an error, no 'success' event is emitted."""
    with patch("server.app.api.v1.endpoints.models.pull_ollama_model", side_effect=_fake_pull_error):
        resp = await app_client.post("/v1/models/pull/ollama/qwen3:8b", headers=auth_headers)

    events = await _collect_ndjson(resp)
    statuses = [e.get("status") for e in events]
    assert "success" not in statuses
    assert any("error" in e for e in events)


# --- Validation errors ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_pull_non_ollama_returns_400(app_client, auth_headers):
    """Pull is only supported for Ollama models."""
    resp = await app_client.post("/v1/models/pull/openai/test-llm", headers=auth_headers)
    assert resp.status_code == 400
    assert "Ollama" in resp.json()["detail"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_pull_unknown_model_returns_404(app_client, auth_headers):
    """Pull for a model not in config returns 404."""
    resp = await app_client.post("/v1/models/pull/ollama/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_pull_no_api_base_returns_400(app_client, auth_headers):
    """Pull for an Ollama model with no api_base returns 400."""
    resp = await app_client.post("/v1/models/pull/ollama/no-base", headers=auth_headers)
    assert resp.status_code == 400
    assert "API base URL" in resp.json()["detail"]


# --- Auth ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_pull_model_no_auth(app_client):
    """Pull without auth returns 403."""
    resp = await app_client.post("/v1/models/pull/ollama/qwen3:8b")
    assert resp.status_code == 403
