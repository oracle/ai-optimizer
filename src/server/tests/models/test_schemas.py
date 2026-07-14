"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.models.schemas Pydantic models.
"""
# spell-checker: disable

import time

import pytest
from pydantic import SecretStr, ValidationError

from server.app.core.secrets import REVEAL_KEY, reveal
from server.app.models.schemas import (
    ModelConfig,
    ModelSensitive,
    ModelUpdate,
)
from server.tests.constants import TEST_OPENAI_MODEL_ID

# ---------------------------------------------------------------------------
# ModelSensitive
# ---------------------------------------------------------------------------


class TestModelSensitive:
    """Test ModelSensitive field."""

    def test_api_key_set(self):
        """api_key stores the provided value."""
        m = ModelSensitive(api_key=SecretStr("sk-test"))
        assert reveal(m.api_key) == "sk-test"


# ---------------------------------------------------------------------------
# ModelConfig
# ---------------------------------------------------------------------------


class TestModelConfig:
    """Test ModelConfig composite model."""

    def test_defaults(self):
        """Default fields match expected literal and computed values."""
        now = int(time.time())
        cfg = ModelConfig(type="ll")
        assert cfg.object == "model"
        assert cfg.owned_by == "aioptimizer"
        assert abs(cfg.created - now) <= 2
        assert cfg.enabled is False
        assert cfg.status == "unreachable"

    def test_legacy_usable_field_dropped(self):
        """``usable`` was intentionally replaced by ``status`` (breaking change) — never serialized."""
        dumped = ModelConfig(type="ll").model_dump()
        assert "status" in dumped
        assert "usable" not in dumped

    def test_ollama_chat_provider_normalized_to_ollama(self):
        """``ollama_chat`` (internal alias) is stored as the canonical ``ollama``."""
        assert ModelConfig(id="mistral", provider="ollama_chat", type="ll").provider == "ollama"
        # Other providers are untouched.
        assert ModelConfig(id="gpt", provider="openai", type="ll").provider == "openai"

    def test_type_validation_accepts_valid(self):
        """'ll', 'embed', and 'rerank' are all accepted."""
        for t in ("ll", "embed", "rerank"):
            cfg = ModelConfig(type=t)
            assert cfg.type == t

    def test_type_validation_rejects_invalid(self):
        """An unrecognised type raises ValidationError."""
        with pytest.raises(ValidationError):
            ModelConfig(type="invalid")  # type: ignore[arg-type]

    def test_inherits_language_model_parameters(self):
        """LanguageModelParameters fields are accessible on ModelConfig."""
        cfg = ModelConfig(type="ll", max_tokens=2048, max_input_tokens=4096)
        assert cfg.max_tokens == 2048
        assert cfg.max_input_tokens == 4096

    def test_inherits_embedding_model_parameters(self):
        """EmbeddingModelParameters fields are accessible on ModelConfig."""
        cfg = ModelConfig(type="embed", max_chunk_size=512)
        assert cfg.max_chunk_size == 512

    def test_inherits_model_sensitive(self):
        """ModelSensitive fields are accessible on ModelConfig."""
        cfg = ModelConfig(type="ll", api_key=SecretStr("sk-key"))
        assert reveal(cfg.api_key) == "sk-key"

    def test_inherits_model_identity(self):
        """ModelIdentity fields are accessible on ModelConfig."""
        cfg = ModelConfig(type="ll", provider="openai", id=TEST_OPENAI_MODEL_ID)
        assert cfg.provider == "openai"
        assert cfg.id == TEST_OPENAI_MODEL_ID

    def test_api_base_optional(self):
        """api_base defaults to None and accepts a URL string."""
        cfg = ModelConfig(type="ll")
        assert cfg.api_base is None
        cfg2 = ModelConfig(type="ll", api_base="http://localhost:8000")
        assert cfg2.api_base == "http://localhost:8000"

    # -- small_model computed field ------------------------------------------

    @pytest.mark.parametrize(
        ("model_id", "expected"),
        [
            ("llama3.2:1b", True),
            ("gemma-7b", False),
        ],
    )
    def test_small_model_delegates_to_model_classifier(self, model_id, expected):
        """small_model exposes the classifier result for a configured model."""
        cfg = ModelConfig(type="ll", id=model_id)
        assert cfg.small_model is expected

    def test_small_model_in_serialization(self):
        """small_model appears in model_dump output."""
        cfg = ModelConfig(type="ll", id="llama3.2:1b")
        dumped = cfg.model_dump()
        assert "small_model" in dumped
        assert dumped["small_model"] is True


# ---------------------------------------------------------------------------
# ModelUpdate
# ---------------------------------------------------------------------------


class TestModelUpdate:
    """Test ModelUpdate optional fields."""

    def test_model_dump_exclude_unset_returns_only_set_fields(self):
        """model_dump(exclude_unset=True) omits fields not explicitly set."""
        u = ModelUpdate(temperature=0.5, enabled=True)
        dumped = u.model_dump(exclude_unset=True)
        assert dumped == {"temperature": 0.5, "enabled": True}

    def test_inherits_api_key_from_model_sensitive(self):
        """api_key is available via ModelSensitive inheritance."""
        u = ModelUpdate(api_key=SecretStr("new-key"))
        assert reveal(u.api_key) == "new-key"


# ---------------------------------------------------------------------------
# Sensitive-field rendering
# ---------------------------------------------------------------------------


class TestSensitiveFieldRendering:
    """``api_key`` renders masked by default."""

    def test_repr_is_masked(self):
        cfg = ModelConfig(type="ll", api_key=SecretStr("sk-secret"))
        assert "sk-secret" not in repr(cfg)

    def test_default_dump_is_masked(self):
        cfg = ModelConfig(type="ll", api_key=SecretStr("sk-secret"))
        dumped = cfg.model_dump()
        assert dumped["api_key"] == "**********"

    def test_default_dump_json_is_masked(self):
        cfg = ModelConfig(type="ll", api_key=SecretStr("sk-secret"))
        dumped_json = cfg.model_dump_json()
        assert "sk-secret" not in dumped_json
        assert "**********" in dumped_json

    def test_reveal_context_unmasks(self):
        cfg = ModelConfig(type="ll", api_key=SecretStr("sk-secret"))
        dumped = cfg.model_dump(context={REVEAL_KEY: True})
        assert dumped["api_key"] == "sk-secret"

    def test_reveal_context_unmasks_json(self):
        cfg = ModelConfig(type="ll", api_key=SecretStr("sk-secret"))
        dumped_json = cfg.model_dump_json(context={REVEAL_KEY: True})
        assert "sk-secret" in dumped_json
        assert "**********" not in dumped_json

    def test_none_passes_through(self):
        cfg = ModelConfig(type="ll")
        dumped = cfg.model_dump()
        assert dumped["api_key"] is None
