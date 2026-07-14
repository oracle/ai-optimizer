"""
Tests for the /v1/chat/streams endpoint.
"""
# spell-checker: disable

import json
from typing import Any, AsyncGenerator, Dict, List
from unittest.mock import AsyncMock

import pytest

from server.app.api.v1.endpoints import chat as chat_endpoint
from server.app.core.settings import _client_store, settings
from server.tests.conftest import make_test_model_config
from server.tests.constants import TEST_OLLAMA_MODEL_ID
from server.tests.runtime.shared_helpers import ollama_available


async def _collect_sse(response) -> List[str]:
    """Collect 'data:' payloads from an SSE StreamingResponse."""
    payloads: List[str] = []
    async for line in response.aiter_lines():
        if not line:
            continue
        line = line.strip()  # noqa: PLW2901
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        payloads.append(payload)
        if payload == "[DONE]":
            break
    return payloads


def _loads(payload: str) -> Dict[str, Any]:
    """Decode a JSON payload, asserting success."""
    return json.loads(payload)


def test_internal_mcp_url_uses_http_loopback_for_wildcard_bind():
    """Wildcard bind addresses should become dialable loopback targets."""
    assert (
        chat_endpoint._internal_mcp_url(
            server_address="0.0.0.0",
            server_port=8000,
            server_url_prefix="",
            server_ssl=False,
        )
        == "http://127.0.0.1:8000/mcp/"
    )


def test_internal_mcp_url_uses_https_when_server_ssl_enabled():
    """Server-side MCP calls must match the uvicorn TLS mode."""
    assert (
        chat_endpoint._internal_mcp_url(
            server_address="0.0.0.0",
            server_port=8000,
            server_url_prefix="",
            server_ssl=True,
        )
        == "https://127.0.0.1:8000/mcp/"
    )


def test_internal_mcp_url_preserves_url_prefix():
    """Mounted deployments should call MCP below the configured prefix."""
    assert (
        chat_endpoint._internal_mcp_url(
            server_address="localhost",
            server_port=9443,
            server_url_prefix="optimizer/",
            server_ssl=True,
        )
        == "https://localhost:9443/optimizer/mcp/"
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_streams_happy_path(app_client, auth_headers, monkeypatch):
    """Aggregates streamed chunks into completion payload with metadata."""

    async def fake_stream(*_args, **_kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        yield {"type": "stream", "content": "Hello"}
        yield {"type": "stream", "content": " world"}
        yield {
            "type": "_meta",
            "route": "llm_only",
            "vs_metadata": {"documents": [{"page_content": "docs"}]},
            "sql_metadata": {"executed_sql": ["SELECT * FROM drivers"]},
        }
        yield {
            "type": "_token_usage",
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        }

    monkeypatch.setattr(
        chat_endpoint,
        "_orchestrator",
        AsyncMock(execute_chat_stream=fake_stream),
    )

    resp = await app_client.post(
        "/v1/chat/streams",
        json={"messages": [{"role": "user", "content": "Say hello"}]},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    payloads = await _collect_sse(resp)
    assert payloads[-1] == "[DONE]"

    parsed = [_loads(p) for p in payloads[:-1]]
    stream_chunks = [p for p in parsed if p["type"] == "stream"]
    completion = next(p for p in parsed if p["type"] == "completion")

    assert [c["content"] for c in stream_chunks] == ["Hello", " world"]
    assert completion["content"] == "Hello world"
    assert completion["route"] == "llm_only"
    assert completion["vs_metadata"] == {"documents": [{"page_content": "docs"}]}
    assert completion["sql_metadata"] == {"executed_sql": ["SELECT * FROM drivers"]}
    assert completion["token_usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }


@pytest.mark.unit
@pytest.mark.anyio
async def test_streams_status_and_error_passthrough(app_client, auth_headers, monkeypatch):
    """Status and error events stream through without completion payload."""

    async def fake_stream(*_args, **_kwargs):
        yield {"type": "status", "content": "Thinking"}
        yield {"type": "error", "content": "Failed to answer."}

    monkeypatch.setattr(
        chat_endpoint,
        "_orchestrator",
        AsyncMock(execute_chat_stream=fake_stream),
    )

    resp = await app_client.post(
        "/v1/chat/streams",
        json={"messages": [{"role": "user", "content": "break it"}]},
        headers=auth_headers,
    )

    payloads = await _collect_sse(resp)
    assert payloads[-1] == "[DONE]"

    parsed = [_loads(p) for p in payloads[:-1]]

    assert parsed == [
        {"type": "status", "content": "Thinking"},
        {"type": "error", "content": "Failed to answer."},
    ]


@pytest.mark.unit
@pytest.mark.anyio
async def test_streams_exception_translated_to_error_event(app_client, auth_headers, monkeypatch):
    """Unexpected orchestrator errors are converted to error events and completion stops."""

    async def failing_stream(*_args, **_kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(
        chat_endpoint,
        "_orchestrator",
        AsyncMock(execute_chat_stream=failing_stream),
    )

    resp = await app_client.post(
        "/v1/chat/streams",
        json={"messages": [{"role": "user", "content": "trigger failure"}]},
        headers=auth_headers,
    )

    payloads = await _collect_sse(resp)
    assert payloads[-1] == "[DONE]"

    error_payloads = [_loads(p) for p in payloads[:-1]]
    assert len(error_payloads) == 1
    assert error_payloads[0]["type"] == "error"
    assert "boom" in error_payloads[0]["content"]


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.skipif(not ollama_available(), reason="ollama not running at 127.0.0.1:11434")
async def test_streams_ollama_integration(app_client, auth_headers):
    """Streams a short prompt end-to-end against a running Ollama instance.

    Verifies real token-by-token streaming reaches the SSE consumer:

    - More than one ``stream`` chunk arrives (the no-stream fallback in
      ``session.execute`` would emit a single chunk of the whole answer; that
      shape would have masked an ``include_types`` regression on
      ``astream_events``).
    - The ``completion`` event matches the assembled chunk content.
    - The ``completion`` event carries non-zero ``token_usage``, exercising
      the ``UsageMetadataCallbackHandler`` path end-to-end (the endpoint
      folds the internal ``_token_usage`` event into ``completion``).
    - No ``error`` events.
    """
    original_settings = settings.client_settings
    original_store = dict(_client_store)
    original_models = list(settings.model_configs)

    try:
        new_settings = original_settings.model_copy(deep=True)
        new_settings.ll_model.provider = "ollama"
        new_settings.ll_model.id = TEST_OLLAMA_MODEL_ID
        new_settings.tools_enabled = []
        new_settings.client = "server"

        settings.client_settings = new_settings
        _client_store["server"] = new_settings
        settings.model_configs = [
            *original_models,
            make_test_model_config(
                provider="ollama",
                id=TEST_OLLAMA_MODEL_ID,
                type="ll",
                api_base="http://127.0.0.1:11434",
                enabled=True,
                usable=True,
            ),
        ]

        resp = await app_client.post(
            "/v1/chat/streams",
            json={"messages": [{"role": "user", "content": "Count from 1 to 5, one number per line."}]},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        payloads = await _collect_sse(resp)
        assert payloads[-1] == "[DONE]"

        parsed = [_loads(p) for p in payloads[:-1]]
        stream_chunks = [p for p in parsed if p["type"] == "stream"]
        error_events = [p for p in parsed if p["type"] == "error"]
        completion = next((p for p in parsed if p["type"] == "completion"), None)

        assert not error_events, f"Unexpected error events: {error_events}"
        assert stream_chunks, "Expected on_chat_model_stream chunks — streaming not engaged"
        assert len(stream_chunks) > 1, (
            f"Expected multiple incremental stream chunks (real token streaming); "
            f"got {len(stream_chunks)} — the no-stream fallback in session.execute likely fired, "
            f"which means astream_events delivered no on_chat_model_stream events"
        )
        assert completion is not None, "Expected a completion event"
        assembled = "".join(chunk["content"] for chunk in stream_chunks)
        assert assembled.strip()
        assert completion["content"].strip() == assembled.strip()
        token_usage = completion.get("token_usage")
        assert token_usage, (
            "Expected token_usage on the completion event — UsageMetadataCallbackHandler should observe usage"
        )
        assert token_usage.get("total_tokens", 0) > 0, (
            f"Expected non-zero total_tokens, got {token_usage}"
        )
    finally:
        settings.client_settings = original_settings
        _client_store.clear()
        _client_store.update(original_store)
        settings.model_configs = original_models
