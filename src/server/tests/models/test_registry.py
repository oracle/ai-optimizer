"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.models.registry.
"""
# spell-checker: disable

import pytest

from server.app.core.settings import settings
from server.app.models.defaults import FACTORY_MODELS
from server.app.models.registry import _model_key, apply_env_overrides, load_default_models, register_model
from server.app.models.schemas import ModelConfig


@pytest.fixture(autouse=True)
def _reset_model_configs():
    """Reset settings.model_configs before and after each test."""
    original = settings.model_configs
    settings.model_configs = []
    yield
    settings.model_configs = original


# ---------------------------------------------------------------------------
# _model_key
# ---------------------------------------------------------------------------


class TestModelKey:
    """Test _model_key helper."""

    def test_returns_casefolded_tuple(self):
        """Mixed-case inputs are lowered."""
        assert _model_key("GPT-4o", "OpenAI") == ("gpt-4o", "openai")

    def test_preserves_special_characters(self):
        """Slashes and hyphens are kept intact."""
        assert _model_key("meta-llama/Llama-3.2", "hosted_vllm") == ("meta-llama/llama-3.2", "hosted_vllm")

    def test_already_lowercase(self):
        """Already-lowercase strings pass through unchanged."""
        assert _model_key("model", "provider") == ("model", "provider")


# ---------------------------------------------------------------------------
# register_model
# ---------------------------------------------------------------------------


class TestRegisterModel:
    """Test register_model deduplication and append."""

    def test_appends_new_model(self):
        """A fresh model is appended to the list."""
        m = ModelConfig(id="new-model", type="ll", provider="openai")
        register_model(m)
        assert len(settings.model_configs) == 1
        assert settings.model_configs[0].id == "new-model"

    def test_deduplicates_same_id_provider(self):
        """Re-registering same (id, provider) replaces the earlier entry."""
        m1 = ModelConfig(id="test", type="ll", provider="openai", max_tokens=100)
        m2 = ModelConfig(id="test", type="ll", provider="openai", max_tokens=200)
        register_model(m1)
        register_model(m2)
        assert len(settings.model_configs) == 1
        assert settings.model_configs[0].max_tokens == 200

    def test_case_insensitive_dedup(self):
        """Deduplication is case-insensitive on both id and provider."""
        m1 = ModelConfig(id="Test", type="ll", provider="OpenAI")
        m2 = ModelConfig(id="test", type="ll", provider="openai", max_tokens=999)
        register_model(m1)
        register_model(m2)
        assert len(settings.model_configs) == 1
        assert settings.model_configs[0].max_tokens == 999

    def test_different_provider_keeps_both(self):
        """Same id with different provider are separate entries."""
        m1 = ModelConfig(id="model", type="ll", provider="openai")
        m2 = ModelConfig(id="model", type="ll", provider="anthropic")
        register_model(m1)
        register_model(m2)
        assert len(settings.model_configs) == 2


# ---------------------------------------------------------------------------
# load_default_models
# ---------------------------------------------------------------------------


class TestLoadDefaultModels:
    """Test load_default_models startup function."""

    @pytest.mark.anyio
    async def test_populates_from_factory_when_empty(self):
        """Empty model_configs is populated from FACTORY_MODELS."""
        assert settings.model_configs == []
        await load_default_models()
        assert len(settings.model_configs) == len(FACTORY_MODELS)

    @pytest.mark.anyio
    async def test_skips_when_already_populated(self):
        """Non-empty model_configs is left untouched."""
        settings.model_configs = [ModelConfig(id="existing", type="ll", provider="test")]
        await load_default_models()
        assert len(settings.model_configs) == 1
        assert settings.model_configs[0].id == "existing"

    @pytest.mark.anyio
    async def test_all_entries_are_model_config(self):
        """Every loaded entry is a ModelConfig instance."""
        await load_default_models()
        for cfg in settings.model_configs:
            assert isinstance(cfg, ModelConfig)


# ---------------------------------------------------------------------------
# apply_env_overrides
# ---------------------------------------------------------------------------


class TestApplyEnvOverrides:
    """Test apply_env_overrides with monkeypatched env vars."""

    def test_patches_matching_provider(self, monkeypatch):
        """Env var value is written to the matching model field."""
        cfg = ModelConfig(id="gpt-4o", type="ll", provider="openai", api_key="old")
        settings.model_configs = [cfg]
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        apply_env_overrides()
        assert cfg.api_key == "sk-from-env"

    def test_enables_model_when_env_found(self, monkeypatch):
        """Model is enabled when its env var is present."""
        cfg = ModelConfig(id="gpt-4o", type="ll", provider="openai", enabled=False)
        settings.model_configs = [cfg]
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        apply_env_overrides()
        assert cfg.enabled is True

    def test_skips_when_env_absent(self, monkeypatch):
        """Model is unchanged when the env var is not set."""
        cfg = ModelConfig(id="gpt-4o", type="ll", provider="openai", api_key="original", enabled=False)
        settings.model_configs = [cfg]
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        apply_env_overrides()
        assert cfg.api_key == "original"
        assert cfg.enabled is False

    def test_case_insensitive_provider_match(self, monkeypatch):
        """Provider comparison is case-insensitive."""
        cfg = ModelConfig(id="cmd-r", type="ll", provider="Cohere", api_key="old")
        settings.model_configs = [cfg]
        monkeypatch.setenv("COHERE_API_KEY", "new-key")
        apply_env_overrides()
        assert cfg.api_key == "new-key"

    def test_patches_api_base_field(self, monkeypatch):
        """api_base overrides work the same as api_key overrides."""
        cfg = ModelConfig(id="phi-4", type="ll", provider="huggingface", api_base="http://old:1234/v1")
        settings.model_configs = [cfg]
        monkeypatch.setenv("ON_PREM_HF_URL", "http://new:1234/v1")
        apply_env_overrides()
        assert cfg.api_base == "http://new:1234/v1"

    def test_patches_multiple_models_same_provider(self, monkeypatch):
        """All models sharing a provider are patched."""
        cfg1 = ModelConfig(id="gpt-4o", type="ll", provider="openai", api_key="old1")
        cfg2 = ModelConfig(id="text-embed", type="embed", provider="openai", api_key="old2")
        settings.model_configs = [cfg1, cfg2]
        monkeypatch.setenv("OPENAI_API_KEY", "sk-shared")
        apply_env_overrides()
        assert cfg1.api_key == "sk-shared"
        assert cfg2.api_key == "sk-shared"
