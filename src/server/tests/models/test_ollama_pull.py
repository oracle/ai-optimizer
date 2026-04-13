"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.models.ollama.pull_ollama_model.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.app.models.ollama import pull_ollama_model

OLLAMA_URL = "http://localhost:11434"


def _make_stream_response(lines: list[str]):
    """Return a mock response whose aiter_lines yields the given lines."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()

    async def _aiter():
        for item in lines:
            yield item

    resp.aiter_lines = _aiter
    return resp


def _patch_client(stream_resp):
    """Patch httpx.AsyncClient to return a mock that yields stream_resp from .stream()."""
    mock_cls = patch("server.app.models.ollama.httpx.AsyncClient")
    mock = mock_cls.start()
    client = MagicMock()
    mock.return_value.__aenter__ = AsyncMock(return_value=client)
    mock.return_value.__aexit__ = AsyncMock(return_value=False)

    # client.stream() is a sync call returning an async context manager
    stream_ctx = MagicMock()
    stream_ctx.__aenter__ = AsyncMock(return_value=stream_resp)
    stream_ctx.__aexit__ = AsyncMock(return_value=False)
    client.stream.return_value = stream_ctx

    return mock_cls, client


class TestPullOllamaModel:
    """Tests for pull_ollama_model async generator."""

    @pytest.mark.anyio
    async def test_streams_progress(self):
        """Yields parsed NDJSON progress dicts from Ollama."""
        ndjson_lines = [
            '{"status": "pulling manifest"}',
            '{"status": "downloading", "completed": 500, "total": 1000}',
            '{"status": "downloading", "completed": 1000, "total": 1000}',
            '{"status": "success"}',
        ]
        resp = _make_stream_response(ndjson_lines)
        patcher, _ = _patch_client(resp)
        try:
            events = [event async for event in pull_ollama_model(OLLAMA_URL, "qwen3:8b")]
        finally:
            patcher.stop()

        assert len(events) == 4
        assert events[0] == {"status": "pulling manifest"}
        assert events[1]["completed"] == 500
        assert events[3] == {"status": "success"}

    @pytest.mark.anyio
    async def test_skips_empty_lines(self):
        """Empty and whitespace-only lines are skipped."""
        ndjson_lines = ['{"status": "pulling"}', "", "  ", '{"status": "done"}']
        resp = _make_stream_response(ndjson_lines)
        patcher, _ = _patch_client(resp)
        try:
            events = [event async for event in pull_ollama_model(OLLAMA_URL, "qwen3:8b")]
        finally:
            patcher.stop()

        assert len(events) == 2

    @pytest.mark.anyio
    async def test_skips_invalid_json(self):
        """Lines that aren't valid JSON are silently skipped."""
        ndjson_lines = ['{"status": "pulling"}', "not-json", '{"status": "done"}']
        resp = _make_stream_response(ndjson_lines)
        patcher, _ = _patch_client(resp)
        try:
            events = [event async for event in pull_ollama_model(OLLAMA_URL, "qwen3:8b")]
        finally:
            patcher.stop()

        assert len(events) == 2

    @pytest.mark.anyio
    async def test_http_error_yields_error_dict(self):
        """On httpx.HTTPError, yields a single error dict."""
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            client = MagicMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            client.stream.side_effect = httpx.ConnectError("refused")

            events = [event async for event in pull_ollama_model(OLLAMA_URL, "qwen3:8b")]

        assert len(events) == 1
        assert "error" in events[0]
        assert "refused" in events[0]["error"]

    @pytest.mark.anyio
    async def test_calls_correct_url(self):
        """Verifies the pull hits /api/pull with the correct model name."""
        resp = _make_stream_response(['{"status": "success"}'])
        patcher, client = _patch_client(resp)
        try:
            _ = [event async for event in pull_ollama_model(OLLAMA_URL, "qwen3:8b")]
        finally:
            patcher.stop()

        client.stream.assert_called_once_with(
            "POST",
            f"{OLLAMA_URL}/api/pull",
            json={"name": "qwen3:8b"},
        )

    @pytest.mark.anyio
    async def test_trailing_slash_stripped(self):
        """Trailing slash on api_base doesn't produce double-slash in URL."""
        resp = _make_stream_response(['{"status": "success"}'])
        patcher, client = _patch_client(resp)
        try:
            _ = [event async for event in pull_ollama_model(f"{OLLAMA_URL}/", "qwen3:8b")]
        finally:
            patcher.stop()

        call_url = client.stream.call_args[0][1]
        assert "//" not in call_url.replace("http://", "")
