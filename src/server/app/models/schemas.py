"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for AI model configuration.
"""

import time
from typing import Literal, Optional

from pydantic import BaseModel, Field


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

    api_key: Optional[str] = None


class ModelConfig(LanguageModelParameters, EmbeddingModelParameters, ModelSensitive):
    """Model Object."""

    id: str = Field(..., min_length=1)
    object: Literal["model"] = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: Literal["aioptimizer"] = "aioptimizer"
    type: Literal["ll", "embed", "rerank"] = Field(...)
    provider: str = Field(..., min_length=1, examples=["openai", "anthropic", "ollama"])
    api_base: Optional[str] = None
    enabled: Optional[bool] = False
    usable: bool = False

class ModelUpdate(ModelSensitive):
    """Fields allowed in a model config update (all optional)."""

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
