"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LiteLLM-backed LangChain Embeddings implementation.
"""
# spell-checker:ignore litellm aembedding ocigenai pydantic

from typing import Any, Iterator, Optional

import litellm
from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, ConfigDict, Field, field_validator

# OCI Cohere caps inputs at 96 per call; OpenAI/Cohere-direct allow more.
# 96 is the safe lower bound across providers we support.
DEFAULT_BATCH_SIZE = 96


class LiteLLMEmbeddings(BaseModel, Embeddings):
    """LangChain Embeddings backed by ``litellm.embedding`` / ``litellm.aembedding``.

    Inputs are chunked by ``batch_size`` to stay within provider per-call limits.

    Inherits from ``pydantic.BaseModel`` to align with the rest of the LangChain
    ``Embeddings`` ecosystem (OpenAIEmbeddings, OCIGenAIEmbeddings, …), so logs
    and debugging surfaces field info via ``model_dump()`` / ``repr()`` rather
    than an opaque ``<LiteLLMEmbeddings object at 0x…>``.
    """

    model_key: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    batch_size: int = DEFAULT_BATCH_SIZE
    extra_params: dict[str, Any] = Field(default_factory=dict)

    # ``model_`` collides with Pydantic's reserved namespace; opening it mirrors
    # what OCIGenAIEmbeddings does. ``arbitrary_types_allowed`` lets
    # ``extra_params`` carry live objects (OCI signers, etc.) without per-field
    # declaration.
    model_config = ConfigDict(arbitrary_types_allowed=True, protected_namespaces=())

    def __init__(self, model_key: Optional[str] = None, /, **data: Any) -> None:
        # Preserve the positional ``model_key`` argument the prior dataclass-
        # style constructor exposed. Pydantic's BaseModel.__init__ is
        # kwargs-only by default; this shim routes a positional first arg into
        # the model_key field while leaving the kwarg form working too.
        if model_key is not None:
            data["model_key"] = model_key
        super().__init__(**data)

    @field_validator("batch_size")
    @classmethod
    def _validate_batch_size(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"batch_size must be >= 1, got {v}")
        return v

    def _call_kwargs(self) -> dict[str, Any]:
        # Build extras first so the explicit model_key / api_key / api_base
        # can never be silently shadowed by an extra_params collision.
        kw: dict[str, Any] = {**self.extra_params, "model": self.model_key}
        if self.api_key is not None:
            kw["api_key"] = self.api_key
        if self.api_base is not None:
            kw["api_base"] = self.api_base
        return kw

    def _chunks(self, texts: list[str]) -> Iterator[list[str]]:
        for i in range(0, len(texts), self.batch_size):
            yield texts[i : i + self.batch_size]

    @staticmethod
    def _first_embedding(resp: Any, model_key: str) -> list[float]:
        if not resp.data:
            raise ValueError(f"Embedding endpoint returned no data (model={model_key})")
        return resp.data[0]["embedding"]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for chunk in self._chunks(texts):
            resp = litellm.embedding(input=chunk, **self._call_kwargs())
            out.extend(item["embedding"] for item in resp.data)
        return out

    def embed_query(self, text: str) -> list[float]:
        resp = litellm.embedding(input=[text], **self._call_kwargs())
        return self._first_embedding(resp, self.model_key)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for chunk in self._chunks(texts):
            resp = await litellm.aembedding(input=chunk, **self._call_kwargs())
            out.extend(item["embedding"] for item in resp.data)
        return out

    async def aembed_query(self, text: str) -> list[float]:
        resp = await litellm.aembedding(input=[text], **self._call_kwargs())
        return self._first_embedding(resp, self.model_key)
