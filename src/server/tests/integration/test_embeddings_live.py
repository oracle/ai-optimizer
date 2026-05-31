"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Live OCI GenAI embedding tests, parametrized over EMBED-capable Cohere
models discovered through ``/v1/oci/genai/{profile}``.

Validates the embedding path end-to-end against the real OCI endpoint:

* ``litellm.embedding`` accepts OCI auth + model name and returns vectors
  (mirrors ``test_reasoning_live`` for the chat path).
* ``LiteLLMEmbeddings`` (the server's LangChain Embeddings wrapper) returns
  embeddings via ``embed_documents`` and ``embed_query``.
* The wrapper's batch-size guarantee: when given >96 inputs, it chunks to
  ≤96 per upstream call — the contract preserved from the prior
  ``OCIGenAIEmbeddings`` implementation.

Skipped unless ``AIO_GENAI_COMPARTMENT_ID`` and ``AIO_GENAI_REGION`` are
set (typically via ``.env.pytest`` at the repo root).
"""

import os
from unittest.mock import patch

import litellm
import pytest

from server.app.models.litellm_embeddings import LiteLLMEmbeddings

pytestmark = [pytest.mark.live_oci, pytest.mark.integration]


@pytest.fixture
def cohere_embed_models(live_oci_genai_models) -> list[str]:
    """Cohere-vendor TEXT_EMBEDDINGS models discovered in the configured region.

    Restricting to ``AIO_GENAI_REGION`` because that's where the LiteLLM
    embedding calls are routed; same ``model_name`` may appear across regions.
    """
    region = os.environ["AIO_GENAI_REGION"]
    models = sorted({
        m["model_name"]
        for m in live_oci_genai_models
        if (m.get("vendor") or "").lower() == "cohere"
        and "TEXT_EMBEDDINGS" in (m.get("capabilities") or [])
        and m.get("region") == region
    })
    if not models:
        pytest.skip(
            f"no Cohere TEXT_EMBEDDINGS models in region {region} "
            "(OCI's lineup in this region exposes none, or the vendor/capabilities shape changed)"
        )
    return models


def _litellm_id(model_id: str) -> str:
    """LiteLLM expects the ``oci/`` provider prefix on the model name."""
    return f"oci/{model_id}"


def test_litellm_embedding_accepts(cohere_embed_models, live_oci_litellm_kwargs):
    """OCI accepts an embedding request for each discovered Cohere model.

    Per-model outcome is accumulated into a single ``pytest.fail`` so one
    rejecting model doesn't mask the others — same pattern as the chat
    completion tests.
    """
    failures: list[str] = []
    for model_id in cohere_embed_models:
        try:
            response = litellm.embedding(
                model=_litellm_id(model_id),
                input=["Embed this sentence."],
                **live_oci_litellm_kwargs,
            )
            if not response.data:
                raise AssertionError("empty data in response")
            vector = response.data[0]["embedding"]
            if not vector:
                raise AssertionError("empty embedding vector")
        except Exception as exc:  # noqa: BLE001 — surface per-model outcome
            failures.append(f"{model_id}: {exc!r}")
    if failures:
        pytest.fail("litellm.embedding rejected for: " + "; ".join(failures))


def test_litellm_embeddings_wrapper_embeds_documents_and_query(cohere_embed_models, live_oci_litellm_kwargs):
    """The server-side LiteLLMEmbeddings wrapper drives OCI end-to-end.

    Uses the first discovered Cohere model; the per-model acceptance matrix
    is covered by ``test_litellm_embedding_accepts``.
    """
    model_id = cohere_embed_models[0]
    emb = LiteLLMEmbeddings(
        model_key=_litellm_id(model_id),
        extra_params=live_oci_litellm_kwargs,
    )

    doc_vectors = emb.embed_documents(["alpha", "beta", "gamma"])
    assert len(doc_vectors) == 3
    assert all(v and isinstance(v, list) for v in doc_vectors)

    query_vector = emb.embed_query("delta")
    assert query_vector and isinstance(query_vector, list)
    assert len(query_vector) == len(doc_vectors[0])


def test_litellm_embeddings_wrapper_chunks_inputs_against_oci(
    cohere_embed_models, live_oci_litellm_kwargs
):
    """End-to-end: 100 inputs through the wrapper chunk to ≤96 per OCI call.

    Pins the chunking guarantee preserved from the prior OCIGenAIEmbeddings
    implementation against the live OCI endpoint — a regression here would
    surface either as an OCI 400 (cap exceeded) or as a contract violation
    in the spy. 100 inputs is the smallest count that forces a second batch
    at the default ``batch_size=96`` while keeping the per-run cost bounded.
    """
    model_id = cohere_embed_models[0]
    emb = LiteLLMEmbeddings(
        model_key=_litellm_id(model_id),
        extra_params=live_oci_litellm_kwargs,
    )

    real_embedding = litellm.embedding
    call_input_sizes: list[int] = []

    def spy(**kwargs):
        call_input_sizes.append(len(kwargs["input"]))
        return real_embedding(**kwargs)

    with patch("server.app.models.litellm_embeddings.litellm.embedding", side_effect=spy):
        vectors = emb.embed_documents([f"chunk-{i}" for i in range(100)])

    assert len(vectors) == 100
    assert call_input_sizes == [96, 4]
    assert all(size <= 96 for size in call_input_sizes)
