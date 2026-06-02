"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.models.ollama (Ollama model discovery).
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.app.core.settings import settings
from server.app.models.ollama import _is_embedding_model, load_ollama_models
from server.app.models.schemas import ModelConfig
from server.tests.constants import TEST_OLLAMA_MODEL_ID, TEST_OPENAI_MODEL_ID

OLLAMA_URL = "http://localhost:11434"

TAGS_RESPONSE = {
    "models": [
        {"name": TEST_OLLAMA_MODEL_ID, "details": {"families": ["llama"]}},
        {"name": "llama3.2:1b", "details": {"families": ["llama"]}},
        {"name": "mxbai-embed-large:latest", "details": {"families": ["bert"]}},
    ]
}

SHOW_RESPONSES = {
    TEST_OLLAMA_MODEL_ID: {"model_info": {"general.architecture": "llama", "llama.context_length": 131072}},
    "llama3.2:1b": {"model_info": {"general.architecture": "llama", "llama.context_length": 131072}},
    "mxbai-embed-large:latest": {"model_info": {"general.architecture": "bert", "bert.context_length": 512}},
}


@pytest.fixture(autouse=True)
def _reset_configs():
    """Reset model configs before and after each test."""
    orig = settings.model_configs
    settings.model_configs = []
    yield
    settings.model_configs = orig


def _mock_client(tags_response=None, show_responses=None, *, get_error=None, post_error=None):
    """Return an AsyncMock httpx client handling GET /api/tags and POST /api/show."""
    mock = AsyncMock()
    if get_error:
        mock.get.side_effect = get_error
    else:
        tags_resp = MagicMock()
        tags_resp.status_code = 200
        tags_resp.json.return_value = tags_response or TAGS_RESPONSE
        tags_resp.raise_for_status.return_value = None
        mock.get.return_value = tags_resp

    _show = show_responses if show_responses is not None else SHOW_RESPONSES

    def _post_side_effect(_, **kwargs):
        if post_error:
            raise post_error
        model_name = kwargs.get("json", {}).get("name", "")
        show_data = _show.get(model_name, {"model_info": {}})
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = show_data
        resp.raise_for_status.return_value = None
        return resp

    mock.post.side_effect = _post_side_effect
    return mock


class TestLoadOllamaModels:
    """Tests for load_ollama_models discovery function."""

    @pytest.mark.anyio
    async def test_no_env_var_is_noop(self, monkeypatch):
        """No ON_PREM_OLLAMA_URL → no models registered."""
        monkeypatch.delenv("AIO_ON_PREM_OLLAMA_URL", raising=False)
        monkeypatch.delenv("ON_PREM_OLLAMA_URL", raising=False)
        await load_ollama_models()
        assert settings.model_configs == []

    @pytest.mark.anyio
    async def test_discovers_chat_models(self, monkeypatch):
        """Models without 'embed' in name are registered as type='ll'."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        chat_models = [m for m in settings.model_configs if m.type == "ll"]
        assert len(chat_models) == 2
        assert {m.id for m in chat_models} == {TEST_OLLAMA_MODEL_ID, "llama3.2:1b"}

    @pytest.mark.anyio
    async def test_discovers_embed_models(self, monkeypatch):
        """Models with 'embed' in name are registered as type='embed'."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        embed_models = [m for m in settings.model_configs if m.type == "embed"]
        assert len(embed_models) == 1
        assert embed_models[0].id == "mxbai-embed-large"

    @pytest.mark.anyio
    async def test_strips_latest_from_name(self, monkeypatch):
        """':latest' suffix is stripped from model id."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_mock_client(
                    {"models": [{"name": TEST_OLLAMA_MODEL_ID, "details": {"families": ["llama"]}}]}
                )
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert settings.model_configs[0].id == TEST_OLLAMA_MODEL_ID

    @pytest.mark.anyio
    async def test_keeps_explicit_tag(self, monkeypatch):
        """Explicit tags like ':1b' are preserved in model id."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_mock_client({"models": [{"name": "llama3.2:1b", "details": {"families": ["llama"]}}]})
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert settings.model_configs[0].id == "llama3.2:1b"

    @pytest.mark.anyio
    async def test_removes_models_no_longer_pulled(self, monkeypatch):
        """Ollama models no longer on server are removed."""
        settings.model_configs = [
            ModelConfig(id="old-model", type="ll", provider="ollama", api_base=OLLAMA_URL, enabled=True),
        ]
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_mock_client(
                    {"models": [{"name": TEST_OLLAMA_MODEL_ID, "details": {"families": ["llama"]}}]}
                )
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert len(settings.model_configs) == 1
        assert settings.model_configs[0].id == TEST_OLLAMA_MODEL_ID

    @pytest.mark.anyio
    async def test_preserves_persisted_settings(self, monkeypatch):
        """Persisted model settings (enabled, max_tokens, etc.) are preserved on rediscovery."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OLLAMA_MODEL_ID,
                type="ll",
                provider="ollama",
                api_base="http://old:11434",
                enabled=False,
                max_tokens=2048,
            ),
        ]
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_mock_client(
                    {"models": [{"name": TEST_OLLAMA_MODEL_ID, "details": {"families": ["llama"]}}]}
                )
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert len(settings.model_configs) == 1
        model = settings.model_configs[0]
        assert model.id == TEST_OLLAMA_MODEL_ID
        assert model.enabled is False  # preserved, not overwritten to True
        assert model.max_tokens == 2048  # preserved
        assert model.api_base == OLLAMA_URL  # updated to current URL

    @pytest.mark.anyio
    async def test_non_ollama_models_preserved(self, monkeypatch):
        """Models from other providers are not affected."""
        openai_model = ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=True)
        settings.model_configs = [openai_model]
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_mock_client(
                    {"models": [{"name": TEST_OLLAMA_MODEL_ID, "details": {"families": ["llama"]}}]}
                )
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert len(settings.model_configs) == 2
        providers = {m.provider for m in settings.model_configs}
        assert providers == {"openai", "ollama"}

    @pytest.mark.anyio
    async def test_server_unreachable_no_existing(self, monkeypatch):
        """Unreachable Ollama server with no existing models registers nothing."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("refused")
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert settings.model_configs == []

    @pytest.mark.anyio
    async def test_server_unreachable_updates_api_base(self, monkeypatch):
        """Unreachable server still updates api_base on existing models."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OLLAMA_MODEL_ID, type="ll", provider="ollama", api_base="http://old:11434", enabled=True
            ),
        ]
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("refused")
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert len(settings.model_configs) == 1
        assert settings.model_configs[0].api_base == OLLAMA_URL

    @pytest.mark.anyio
    async def test_models_enabled_and_have_api_base(self, monkeypatch):
        """Discovered models are enabled and have the correct api_base."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_mock_client())
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        for model in settings.model_configs:
            assert model.enabled is True
            assert model.api_base == OLLAMA_URL
            assert model.provider == "ollama"

    @pytest.mark.anyio
    async def test_aio_prefix_takes_precedence(self, monkeypatch):
        """AIO_ON_PREM_OLLAMA_URL takes precedence over ON_PREM_OLLAMA_URL."""
        monkeypatch.setenv("AIO_ON_PREM_OLLAMA_URL", "http://aio-host:11434")
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", "http://legacy-host:11434")
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_mock_client(
                    {"models": [{"name": TEST_OLLAMA_MODEL_ID, "details": {"families": ["llama"]}}]}
                )
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert settings.model_configs[0].api_base == "http://aio-host:11434"

    @pytest.mark.anyio
    async def test_bert_family_classified_as_embed(self, monkeypatch):
        """Models with 'bert' family (all-minilm, bge-large, etc.) are registered as embed."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_mock_client(
                    {
                        "models": [
                            {"name": "all-minilm:latest", "details": {"families": ["bert"]}},
                            {"name": "bge-large:latest", "details": {"families": ["bert"]}},
                        ]
                    }
                )
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert all(m.type == "embed" for m in settings.model_configs)

    @pytest.mark.anyio
    async def test_nomic_bert_family_classified_as_embed(self, monkeypatch):
        """Models with 'nomic-bert' family are registered as embed."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_mock_client(
                    {
                        "models": [
                            {"name": "nomic-embed-text:latest", "details": {"families": ["nomic-bert"]}},
                        ]
                    }
                )
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert settings.model_configs[0].type == "embed"


class TestIsEmbeddingModel:
    """Tests for the _is_embedding_model helper."""

    def test_bert_family(self):
        """'bert' family is detected as embedding."""
        assert _is_embedding_model({"details": {"families": ["bert"]}}) is True

    def test_nomic_bert_family(self):
        """'nomic-bert' family is detected as embedding."""
        assert _is_embedding_model({"details": {"families": ["nomic-bert"]}}) is True

    def test_llama_family(self):
        """'llama' family is not an embedding model."""
        assert _is_embedding_model({"details": {"families": ["llama"]}}) is False

    def test_embed_in_name_detected(self):
        """Models with 'embed' in their name are detected even with a non-embed family."""
        assert _is_embedding_model({"name": "qwen3-embedding:latest", "details": {"families": ["qwen3"]}}) is True

    def test_embed_in_name_mxbai(self):
        """'mxbai-embed-large' detected via name even if family check were to miss it."""
        assert _is_embedding_model({"name": "mxbai-embed-large:latest", "details": {"families": ["bert"]}}) is True

    def test_embed_name_case_insensitive(self):
        """Name-based detection is case-insensitive."""
        assert _is_embedding_model({"name": "MyModel-Embed:v1", "details": {}}) is True

    def test_missing_details(self):
        """Entry without 'details' defaults to non-embedding."""
        assert _is_embedding_model({"name": "some-model"}) is False

    def test_missing_families(self):
        """Empty 'details' defaults to non-embedding."""
        assert _is_embedding_model({"details": {}}) is False

    def test_none_families(self):
        """Null 'families' defaults to non-embedding."""
        assert _is_embedding_model({"details": {"families": None}}) is False


class TestContextLength:
    """Tests for /api/show context length extraction."""

    @pytest.mark.anyio
    async def test_chat_model_gets_max_input_tokens(self, monkeypatch):
        """Chat model max_input_tokens is set from context_length."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        tags = {"models": [{"name": TEST_OLLAMA_MODEL_ID, "details": {"families": ["llama"]}}]}
        show = {TEST_OLLAMA_MODEL_ID: {"model_info": {"general.architecture": "llama", "llama.context_length": 131072}}}
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_mock_client(tags, show))
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert settings.model_configs[0].max_input_tokens == 131072

    @pytest.mark.anyio
    async def test_embed_model_gets_max_chunk_size(self, monkeypatch):
        """Embedding model max_chunk_size is set from context_length."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        tags = {"models": [{"name": "mxbai-embed-large:latest", "details": {"families": ["bert"]}}]}
        show = {
            "mxbai-embed-large:latest": {"model_info": {"general.architecture": "bert", "bert.context_length": 512}}
        }
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=_mock_client(tags, show))
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        assert settings.model_configs[0].max_chunk_size == 512

    @pytest.mark.anyio
    async def test_show_failure_uses_defaults(self, monkeypatch):
        """Failed /api/show falls back to Pydantic defaults."""
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        tags = {"models": [{"name": TEST_OLLAMA_MODEL_ID, "details": {"families": ["llama"]}}]}
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=_mock_client(tags, post_error=httpx.ConnectError("refused"))
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        model = settings.model_configs[0]
        assert model.max_input_tokens is None  # Pydantic default
        assert model.max_tokens == 4096  # Pydantic default

    @pytest.mark.anyio
    async def test_existing_models_skip_show(self, monkeypatch):
        """Persisted models do not trigger /api/show calls."""
        settings.model_configs = [
            ModelConfig(
                id=TEST_OLLAMA_MODEL_ID,
                type="ll",
                provider="ollama",
                api_base=OLLAMA_URL,
                enabled=True,
                max_input_tokens=8192,
            ),
        ]
        monkeypatch.setenv("ON_PREM_OLLAMA_URL", OLLAMA_URL)
        tags = {"models": [{"name": TEST_OLLAMA_MODEL_ID, "details": {"families": ["llama"]}}]}
        with patch("server.app.models.ollama.httpx.AsyncClient") as mock_cls:
            client = _mock_client(tags)
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            await load_ollama_models()

        # Preserved user-tuned value, not overwritten by /api/show
        assert settings.model_configs[0].max_input_tokens == 8192
        client.post.assert_not_called()
