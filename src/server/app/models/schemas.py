"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for AI model configuration.
"""
# spell-checker: ignore aioptimizer ollama qwen rerank

import re
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, computed_field

from server.app.core.secrets import SecretField

# Pattern to extract parameter count from model names (e.g., "llama3.2:1b" -> 1.0)
_PARAM_PATTERN = re.compile(r"(\d+(?:\.\d+)?)[bB](?![a-zA-Z])")
_SMALL_MODEL_THRESHOLD_B = 7


class LanguageModelParameters(BaseModel):
    """Language Model Parameters (also used by settings.py)."""

    max_input_tokens: Optional[int] = None
    frequency_penalty: Optional[float] = 0.00
    max_tokens: Optional[int] = 4096
    presence_penalty: Optional[float] = 0.00
    temperature: Optional[float] = 0.50
    top_p: Optional[float] = 1.00


class EmbeddingModelParameters(BaseModel):
    """Embedding Model Parameters (also used by settings.py)."""

    max_chunk_size: Optional[int] = 8192


class ModelSensitive(BaseModel):
    """Sensitive model fields excluded from default API responses."""

    api_key: SecretField = None


class SupportedProviderIds(BaseModel):
    """A provider and its available models from LiteLLM."""

    provider: Optional[str] = Field(default=None, examples=["openai", "anthropic", "ollama"])
    ids: list[dict[str, Any]] = []


class ModelIdentity(BaseModel):
    """Model identity fields reused by client settings."""

    provider: Optional[str] = Field(default=None, examples=["openai", "anthropic", "ollama"])
    id: Optional[str] = Field(default=None, examples=["gpt-5-mini", "sonnet", "qwen3:8b"])

    @classmethod
    def from_key(cls, model_key: str) -> "ModelIdentity":
        """Parse a ``provider/id`` string into a :class:`ModelIdentity`.

        Raises :class:`ValueError` when *model_key* does not contain exactly
        one ``/`` separator.
        """
        parts = model_key.split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid model format: {model_key}. Expected 'provider/id'.")
        return cls(provider=parts[0], id=parts[1])


class ModelConfig(LanguageModelParameters, EmbeddingModelParameters, ModelSensitive, ModelIdentity):
    """Model Object."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "ll",
                "provider": "openai",
                "id": "gpt-5-mini",
                "api_base": "https://api.openai.com/v1",
                "api_key": "sk-...",
                "enabled": True,
                "max_tokens": 4096,
                "temperature": 0.5,
                "frequency_penalty": 0.0,
                "presence_penalty": 0.0,
                "top_p": 1.0,
            }
        }
    }

    object: Literal["model"] = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: Literal["aioptimizer"] = "aioptimizer"
    type: Literal["ll", "embed", "rerank"] = Field(...)
    api_base: Optional[str] = None
    enabled: Optional[bool] = False
    usable: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def small_model(self) -> bool:
        """True when the model has < 7B parameters (detected from model name)."""
        if not self.id:
            return False
        match = _PARAM_PATTERN.search(self.id)
        if match:
            try:
                return float(match.group(1)) < _SMALL_MODEL_THRESHOLD_B
            except ValueError:
                pass
        return False


class ModelUpdate(ModelSensitive):
    """Fields allowed in a model config update (all optional)."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "enabled": True,
                "api_base": "https://api.openai.com/v1",
                "api_key": "sk-...",
                "max_tokens": 8192,
                "temperature": 0.2,
            }
        }
    }

    type: Optional[Literal["ll", "embed", "rerank"]] = None
    provider: Optional[str] = None
    enabled: Optional[bool] = None
    api_base: Optional[str] = None
    max_input_tokens: Optional[int] = None
    frequency_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_chunk_size: Optional[int] = None
