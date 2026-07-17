"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.models.connectivity.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from server.app.core.settings import settings
from server.app.models.connectivity import (
    _normalize_ollama_name,
    _probe_endpoint,
    check_model_reachability,
    check_single_model,
)
from server.app.models.schemas import ModelConfig
from server.app.oci.schemas import OciProfileConfig
from server.tests.constants import TEST_OLLAMA_MODEL_ID, TEST_OPENAI_MODEL_ID


@pytest.fixture(autouse=True)
def _reset_configs():
    """Reset model and OCI configs before and after each test."""
    orig_models = settings.model_configs
    orig_oci = settings.oci_configs
    settings.model_configs = []
    settings.oci_configs = []
    yield
    settings.model_configs = orig_models
    settings.oci_configs = orig_oci


# ---------------------------------------------------------------------------
# _probe_endpoint
# ---------------------------------------------------------------------------


class TestProbeEndpoint:
    """Tests for the low-level HTTP probe."""

    @pytest.mark.anyio
    async def test_reachable_returns_true(self):
        """Any HTTP response counts as reachable."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.head.return_value = httpx.Response(200)
        reachable, error = await _probe_endpoint(mock_client, "http://localhost:11434")
        assert reachable is True
        assert error is None

    @pytest.mark.anyio
    async def test_401_counts_as_reachable(self):
        """A 401 response still means the endpoint is reachable."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.head.return_value = httpx.Response(401)
        reachable, error = await _probe_endpoint(mock_client, "http://api.openai.com")
        assert reachable is True
        assert error is None

    @pytest.mark.anyio
    async def test_connection_error_returns_false(self):
        """Connection errors mean unreachable."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.head.side_effect = httpx.ConnectError("refused")
        reachable, error = await _probe_endpoint(mock_client, "http://dead-host:1234")
        assert reachable is False
        assert error is not None and "refused" in error

    @pytest.mark.anyio
    async def test_timeout_returns_false(self):
        """Timeouts mean unreachable."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.head.side_effect = httpx.ConnectTimeout("timed out")
        reachable, error = await _probe_endpoint(mock_client, "http://slow-host:1234")
        assert reachable is False
        assert error is not None and "timed out" in error


# ---------------------------------------------------------------------------
# check_model_reachability — rules
# ---------------------------------------------------------------------------


def _ok_response(*_args, **_kwargs):
    """Return a successful HEAD response."""
    return httpx.Response(200)


def _connect_error(*_args, **_kwargs):
    """Raise a connection error."""
    raise httpx.ConnectError("refused")


class TestRule1Unreachable:
    """Rule 1: Endpoint not accessible → usable=False."""

    @pytest.mark.anyio
    async def test_unreachable_marks_unusable(self):
        """Unreachable endpoint sets usable=False but leaves enabled unchanged."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OPENAI_MODEL_ID,
                type="ll",
                provider="openai",
                api_key=SecretStr("sk-123"),
                api_base="http://dead:1234",
                enabled=True,
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.head.side_effect = httpx.ConnectError("refused")
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        assert settings.model_configs[0].status == "unreachable"
        assert settings.model_configs[0].enabled is True  # enabled unchanged


class TestRule2ReachableWithKey:
    """Rule 2: Endpoint accessible + has api_key → usable=True."""

    @pytest.mark.anyio
    async def test_reachable_with_key(self):
        """Reachable endpoint with api_key sets usable=True."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OPENAI_MODEL_ID,
                type="ll",
                provider="openai",
                api_key=SecretStr("sk-123"),
                api_base="http://api.openai.com",
                enabled=True,
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.head.return_value = httpx.Response(200)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        assert settings.model_configs[0].status == "available"


class TestRule3NoKeyAllowedProvider:
    """Rule 3: Reachable + no api_key + ollama/huggingface/hosted_vllm → usable=True."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("provider", ["huggingface", "hosted_vllm"])
    async def test_no_key_allowed_providers(self, provider):
        """Reachable keyless model with allowed provider is usable."""
        settings.model_configs = [
            ModelConfig(
                id="local-model", type="ll", provider=provider, api_base="http://localhost:11434", enabled=True
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.head.return_value = httpx.Response(200)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        assert settings.model_configs[0].status == "available"


class TestRule4NoKeyOtherProvider:
    """Rule 4: Reachable + no api_key + other provider → usable=False."""

    @pytest.mark.anyio
    async def test_no_key_openai(self):
        """Reachable keyless OpenAI model is not usable."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", api_base="http://api.openai.com", enabled=True
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.head.return_value = httpx.Response(200)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        assert settings.model_configs[0].status == "no_key"


class TestRule5OciModels:
    """Rule 5: OCI models without a usable OCI profile → status="unreachable"; enabled left as-is."""

    @pytest.mark.anyio
    async def test_oci_no_usable_profile(self):
        """OCI model without a usable profile is unreachable but stays enabled (user intent)."""
        settings.model_configs = [
            ModelConfig(id="cohere.command-r", type="ll", provider="oci", enabled=True),
        ]
        settings.oci_configs = [
            OciProfileConfig(auth_profile="DEFAULT", usable=False),
        ]
        await check_model_reachability()
        assert settings.model_configs[0].status == "unreachable"
        assert settings.model_configs[0].enabled is True

    @pytest.mark.anyio
    async def test_oci_with_usable_profile(self):
        """OCI model with a usable profile stays enabled and usable."""
        settings.model_configs = [
            ModelConfig(id="cohere.command-r", type="ll", provider="oci", enabled=True),
        ]
        settings.oci_configs = [
            OciProfileConfig(auth_profile="DEFAULT", usable=True),
        ]
        await check_model_reachability()
        assert settings.model_configs[0].status == "available"
        assert settings.model_configs[0].enabled is True

    @pytest.mark.anyio
    async def test_oci_no_profiles_at_all(self):
        """OCI model with no OCI profiles is unreachable but stays enabled (user intent)."""
        settings.model_configs = [
            ModelConfig(id="cohere.command-r", type="ll", provider="oci", enabled=True),
        ]
        settings.oci_configs = []
        await check_model_reachability()
        assert settings.model_configs[0].status == "unreachable"
        assert settings.model_configs[0].enabled is True


# ---------------------------------------------------------------------------
# check_model_reachability — edge cases
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Shared api_base is probed only once."""

    @pytest.mark.anyio
    async def test_shared_api_base_probed_once(self):
        """Two models sharing an api_base result in only one HEAD request."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OPENAI_MODEL_ID,
                type="ll",
                provider="openai",
                api_key=SecretStr("sk-1"),
                api_base="http://api.openai.com",
                enabled=True,
            ),
            ModelConfig(
                id="text-embed",
                type="embed",
                provider="openai",
                api_key=SecretStr("sk-2"),
                api_base="http://api.openai.com",
                enabled=True,
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.head.return_value = httpx.Response(200)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        # HEAD called once despite two models sharing the URL
        assert mock_client.head.call_count == 1
        assert settings.model_configs[0].status == "available"
        assert settings.model_configs[1].status == "available"


class TestDisabledModelsSkipped:
    """Disabled models are not probed."""

    @pytest.mark.anyio
    async def test_disabled_not_probed(self):
        """Disabled models are skipped and remain unusable."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OPENAI_MODEL_ID,
                type="ll",
                provider="openai",
                api_key=SecretStr("sk-1"),
                api_base="http://api.openai.com",
                enabled=False,
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        mock_client.head.assert_not_called()
        assert settings.model_configs[0].status == "unreachable"


class TestNoApiBase:
    """Models without api_base are marked unusable."""

    @pytest.mark.anyio
    async def test_no_api_base_marked_unusable(self):
        """Model without api_base is marked unusable without probing."""
        settings.model_configs = [
            ModelConfig(id="mystery", type="ll", provider="openai", api_key=SecretStr("sk-1"), enabled=True),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        mock_client.head.assert_not_called()
        assert settings.model_configs[0].status == "unreachable"


class TestNoEnabledModels:
    """No enabled models → nothing happens."""

    @pytest.mark.anyio
    async def test_all_disabled_is_noop(self):
        """No enabled models means no HTTP calls are made."""
        settings.model_configs = [
            ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=False),
        ]
        # Should not raise or make any HTTP calls
        await check_model_reachability()


# ---------------------------------------------------------------------------
# Rule 6: Ollama models — verify pulled
# ---------------------------------------------------------------------------

OLLAMA_TAGS_RESPONSE = {
    "models": [
        {"name": TEST_OLLAMA_MODEL_ID},
        {"name": "llama3.2:1b"},
        {"name": "mxbai-embed-large:latest"},
    ]
}


def _ollama_mock_client(tags_response=None, *, get_error=None):
    """Create an AsyncMock httpx client that responds to GET /api/tags."""
    mock_client = AsyncMock()
    if get_error:
        mock_client.get.side_effect = get_error
    else:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = tags_response or OLLAMA_TAGS_RESPONSE
        resp.raise_for_status.return_value = None
        mock_client.get.return_value = resp
    mock_client.head.return_value = httpx.Response(200)
    return mock_client


class TestNormalizeOllamaName:
    """Unit tests for _normalize_ollama_name."""

    def test_strips_latest(self):
        """':latest' suffix is removed."""
        assert _normalize_ollama_name(TEST_OLLAMA_MODEL_ID) == TEST_OLLAMA_MODEL_ID

    def test_keeps_explicit_tag(self):
        """Non-latest tags like ':1b' are preserved."""
        assert _normalize_ollama_name("llama3.2:1b") == "llama3.2:1b"

    def test_no_tag(self):
        """Name without any tag is returned unchanged."""
        assert _normalize_ollama_name("phi4-mini") == "phi4-mini"


class TestRule6OllamaModels:
    """Rule 6: Ollama models not pulled on server → usable=False."""

    @pytest.mark.anyio
    async def test_available_model_is_usable(self):
        """Ollama model present in /api/tags is marked usable."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OLLAMA_MODEL_ID,
                type="ll",
                provider="ollama",
                api_base="http://localhost:11434",
                enabled=True,
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_ollama_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        assert settings.model_configs[0].status == "available"
        assert settings.model_configs[0].enabled is True

    @pytest.mark.anyio
    async def test_unavailable_model_is_unusable(self):
        """Ollama model NOT in /api/tags is unusable but stays enabled."""
        settings.model_configs = [
            ModelConfig(
                id="gemma3:1b",
                type="ll",
                provider="ollama",
                api_base="http://localhost:11434",
                enabled=True,
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_ollama_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        assert settings.model_configs[0].status == "not_pulled"
        assert settings.model_configs[0].enabled is True

    @pytest.mark.anyio
    async def test_unreachable_server_marks_unusable_keeps_enabled(self):
        """Ollama server unreachable → usable=False but enabled stays True."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OLLAMA_MODEL_ID,
                type="ll",
                provider="ollama",
                api_base="http://dead:11434",
                enabled=True,
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_ollama_mock_client(get_error=httpx.ConnectError("refused"))
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        assert settings.model_configs[0].status == "unreachable"
        assert settings.model_configs[0].enabled is True

    @pytest.mark.anyio
    async def test_explicit_tag_match(self):
        """Model with explicit tag like 'llama3.2:1b' matches Ollama response."""
        settings.model_configs = [
            ModelConfig(
                id="llama3.2:1b",
                type="ll",
                provider="ollama",
                api_base="http://localhost:11434",
                enabled=True,
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_ollama_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        assert settings.model_configs[0].status == "available"

    @pytest.mark.anyio
    async def test_mixed_available_and_missing(self):
        """Two Ollama models: one available, one not."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OLLAMA_MODEL_ID,
                type="ll",
                provider="ollama",
                api_base="http://localhost:11434",
                enabled=True,
            ),
            ModelConfig(
                id="phi4-mini",
                type="ll",
                provider="ollama",
                api_base="http://localhost:11434",
                enabled=True,
            ),
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_ollama_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        # granite4.1:8b is available
        assert settings.model_configs[0].status == "available"
        assert settings.model_configs[0].enabled is True
        # phi4-mini is NOT in tags
        assert settings.model_configs[1].status == "not_pulled"
        assert settings.model_configs[1].enabled is True

    @pytest.mark.anyio
    async def test_bulk_recheck_defaults_ollama_api_base(self, monkeypatch):
        """An Ollama config with no api_base defaults to the configured server.

        Mirrors ``check_single_model`` so an imported/loaded config (whose URL
        discovery couldn't populate while Ollama was down) recovers on a later
        bulk recheck once the server comes online — instead of being pinned
        ``unreachable`` forever.
        """
        monkeypatch.setenv("AIO_ON_PREM_OLLAMA_URL", "http://localhost:11434")
        settings.model_configs = [
            ModelConfig(id=TEST_OLLAMA_MODEL_ID, type="ll", provider="ollama", enabled=True),  # no api_base
        ]
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_ollama_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_model_reachability()

        assert settings.model_configs[0].api_base == "http://localhost:11434"  # defaulted from env
        assert settings.model_configs[0].status == "available"

    @pytest.mark.anyio
    async def test_bulk_recheck_no_ollama_server_marks_unreachable(self, monkeypatch):
        """With no Ollama server configured, a no-api_base config is unreachable."""
        monkeypatch.delenv("AIO_ON_PREM_OLLAMA_URL", raising=False)
        monkeypatch.delenv("ON_PREM_OLLAMA_URL", raising=False)
        settings.model_configs = [
            ModelConfig(id=TEST_OLLAMA_MODEL_ID, type="ll", provider="ollama", enabled=True),  # no api_base
        ]
        await check_model_reachability()

        assert settings.model_configs[0].status == "unreachable"

    @pytest.mark.anyio
    async def test_check_single_model_ollama_available(self):
        """check_single_model verifies ollama model via /api/tags."""
        model = ModelConfig(
            id=TEST_OLLAMA_MODEL_ID,
            type="ll",
            provider="ollama",
            api_base="http://localhost:11434",
            enabled=True,
        )
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_ollama_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_single_model(model)

        assert model.status == "available"

    @pytest.mark.anyio
    async def test_check_single_model_ollama_not_pulled(self):
        """check_single_model marks ollama model not in /api/tags as unusable."""
        model = ModelConfig(
            id="gemma3:1b",
            type="ll",
            provider="ollama",
            api_base="http://localhost:11434",
            enabled=True,
        )
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_ollama_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_single_model(model)

        assert model.status == "not_pulled"
        assert model.enabled is True

    @pytest.mark.anyio
    async def test_check_single_model_defaults_ollama_api_base(self, monkeypatch):
        """A manually added Ollama model with no api_base defaults to the configured server."""
        monkeypatch.setenv("AIO_ON_PREM_OLLAMA_URL", "http://localhost:11434")
        model = ModelConfig(id="gemma3:1b", type="ll", provider="ollama", enabled=True)  # no api_base
        with patch("server.app.models.connectivity.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_ollama_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await check_single_model(model)

        assert model.api_base == "http://localhost:11434"  # defaulted from env
        assert model.status == "not_pulled"  # server up, model absent -> Pull offered

    @pytest.mark.anyio
    async def test_check_single_model_ollama_no_server_configured(self, monkeypatch):
        """With no Ollama server configured, a no-api_base model is simply unreachable."""
        monkeypatch.delenv("AIO_ON_PREM_OLLAMA_URL", raising=False)
        monkeypatch.delenv("ON_PREM_OLLAMA_URL", raising=False)
        model = ModelConfig(id="gemma3:1b", type="ll", provider="ollama", enabled=True)
        await check_single_model(model)
        assert model.status == "unreachable"
