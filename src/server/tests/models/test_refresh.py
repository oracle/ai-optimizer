"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.models.refresh (throttled background reachability re-probe).
"""

import time
from unittest.mock import AsyncMock, patch

import pytest

from server.app.core.settings import _settings_lock, settings
from server.app.models import refresh
from server.tests.models.test_ollama import _mock_client


@pytest.mark.anyio
async def test_recheck_holds_settings_lock():
    """The background recheck must probe-and-write status under _settings_lock, serialized with writes."""
    observed = {}

    async def fake_check():
        observed["locked"] = _settings_lock.locked()

    with patch("server.app.models.refresh.check_model_reachability", side_effect=fake_check):
        await refresh._run_recheck()

    assert observed["locked"] is True


@pytest.mark.anyio
async def test_recheck_does_not_recreate_deleted_models(monkeypatch):
    """A pulled Ollama model the user deleted is NOT recreated by the background recheck."""
    monkeypatch.setenv("AIO_ON_PREM_OLLAMA_URL", "http://localhost:11434")
    original = settings.model_configs
    settings.model_configs = []  # user deleted their Ollama models
    try:
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_mock_client({"models": [{"name": "mistral:latest", "details": {"families": ["llama"]}}]})
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await refresh._run_recheck()
        assert settings.model_configs == []  # still-pulled but deleted model must not reappear
    finally:
        settings.model_configs = original


@pytest.mark.anyio
async def test_recheck_runs_when_stale():
    """A stale throttle window schedules a background re-probe (reachability only)."""
    refresh._recheck["last_monotonic"] = time.monotonic() - 10_000
    with patch("server.app.models.refresh.check_model_reachability", new=AsyncMock()) as mock_check:
        task = refresh.trigger_reachability_recheck(interval=1000)
        assert task is not None
        await task
        mock_check.assert_awaited_once()


@pytest.mark.anyio
async def test_recheck_throttled_within_interval():
    """A recent re-probe means a follow-up call is a no-op (no task, no probes)."""
    refresh._recheck["last_monotonic"] = time.monotonic()
    with patch("server.app.models.refresh.check_model_reachability", new=AsyncMock()) as mock_check:
        assert refresh.trigger_reachability_recheck(interval=1000) is None
        mock_check.assert_not_awaited()
