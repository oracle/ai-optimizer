"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the LiteLLM-backed LangChain Embeddings wrapper.
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

import pytest

from server.app.models.litellm_embeddings import DEFAULT_BATCH_SIZE, LiteLLMEmbeddings
from server.tests.constants import TEST_OPENAI_EMBED_KEY

pytestmark = pytest.mark.anyio


def _embedding_response(n: int, dims: int = 4) -> MagicMock:
    """Build a mock litellm EmbeddingResponse with ``n`` embeddings."""
    resp = MagicMock()
    resp.data = [{"embedding": [float(i)] * dims, "index": i, "object": "embedding"} for i in range(n)]
    return resp


@pytest.mark.unit
def test_default_batch_size_is_96():
    """OCI Cohere's per-call cap is 96; default must not exceed it."""
    assert DEFAULT_BATCH_SIZE == 96


@pytest.mark.unit
def test_embed_documents_single_batch():
    """≤batch_size inputs result in one litellm.embedding call."""
    emb = LiteLLMEmbeddings(TEST_OPENAI_EMBED_KEY, api_key="sk-x")
    with patch("server.app.models.litellm_embeddings.litellm.embedding") as mock_embed:
        mock_embed.return_value = _embedding_response(3)
        result = emb.embed_documents(["a", "b", "c"])

    assert mock_embed.call_count == 1
    assert mock_embed.call_args.kwargs["input"] == ["a", "b", "c"]
    assert mock_embed.call_args.kwargs["model"] == TEST_OPENAI_EMBED_KEY
    assert mock_embed.call_args.kwargs["api_key"] == "sk-x"
    assert len(result) == 3


@pytest.mark.unit
def test_embed_documents_chunks_by_batch_size():
    """>batch_size inputs split into multiple calls, order preserved."""
    emb = LiteLLMEmbeddings("oci/cohere.embed-english-v3.0", batch_size=96)
    with patch("server.app.models.litellm_embeddings.litellm.embedding") as mock_embed:
        mock_embed.side_effect = lambda input, **_: _embedding_response(len(input))
        result = emb.embed_documents(["text"] * 200)

    assert mock_embed.call_count == 3
    batch_lens = [len(call.kwargs["input"]) for call in mock_embed.call_args_list]
    assert batch_lens == [96, 96, 8]
    assert len(result) == 200


@pytest.mark.unit
def test_embed_documents_custom_batch_size():
    emb = LiteLLMEmbeddings(TEST_OPENAI_EMBED_KEY, batch_size=10)
    with patch("server.app.models.litellm_embeddings.litellm.embedding") as mock_embed:
        mock_embed.side_effect = lambda input, **_: _embedding_response(len(input))
        emb.embed_documents(["text"] * 25)

    batch_lens = [len(call.kwargs["input"]) for call in mock_embed.call_args_list]
    assert batch_lens == [10, 10, 5]


@pytest.mark.unit
def test_embed_documents_order_preserved_across_batches():
    """Embeddings returned must align with input order, not call order."""
    emb = LiteLLMEmbeddings("openai/x", batch_size=2)

    counter = {"i": 0}

    def fake_embed(input, **_):
        resp = MagicMock()
        resp.data = [{"embedding": [float(counter["i"] + j)]} for j in range(len(input))]
        counter["i"] += len(input)
        return resp

    with patch("server.app.models.litellm_embeddings.litellm.embedding", side_effect=fake_embed):
        result = emb.embed_documents(["a", "b", "c", "d", "e"])

    assert [v[0] for v in result] == [0.0, 1.0, 2.0, 3.0, 4.0]


@pytest.mark.unit
def test_embed_query_one_call():
    emb = LiteLLMEmbeddings("openai/x")
    with patch("server.app.models.litellm_embeddings.litellm.embedding") as mock_embed:
        mock_embed.return_value = _embedding_response(1, dims=3)
        result = emb.embed_query("hello")

    assert mock_embed.call_count == 1
    assert mock_embed.call_args.kwargs["input"] == ["hello"]
    assert result == [0.0, 0.0, 0.0]


@pytest.mark.unit
def test_extra_params_forwarded():
    """OCI auth kwargs (oci_region, oci_compartment_id, oci_signer) flow through."""
    signer = MagicMock(name="signer")
    emb = LiteLLMEmbeddings(
        "oci/cohere.embed-english-v3.0",
        extra_params={
            "oci_region": "us-chicago-1",
            "oci_compartment_id": "ocid1.compartment..test",
            "oci_signer": signer,
        },
    )
    with patch("server.app.models.litellm_embeddings.litellm.embedding") as mock_embed:
        mock_embed.return_value = _embedding_response(1)
        emb.embed_query("x")

    kw = mock_embed.call_args.kwargs
    assert kw["oci_region"] == "us-chicago-1"
    assert kw["oci_compartment_id"] == "ocid1.compartment..test"
    assert kw["oci_signer"] is signer


@pytest.mark.unit
def test_api_base_forwarded():
    emb = LiteLLMEmbeddings("hosted_vllm/bge-m3", api_base="http://vllm:8000/v1")
    with patch("server.app.models.litellm_embeddings.litellm.embedding") as mock_embed:
        mock_embed.return_value = _embedding_response(1)
        emb.embed_query("x")

    assert mock_embed.call_args.kwargs["api_base"] == "http://vllm:8000/v1"


@pytest.mark.unit
def test_no_api_key_when_absent():
    """When api_key is None, it must not be forwarded as a kwarg."""
    emb = LiteLLMEmbeddings("ollama/nomic-embed-text")
    with patch("server.app.models.litellm_embeddings.litellm.embedding") as mock_embed:
        mock_embed.return_value = _embedding_response(1)
        emb.embed_query("x")

    assert "api_key" not in mock_embed.call_args.kwargs


@pytest.mark.unit
def test_invalid_batch_size_rejected():
    with pytest.raises(ValueError, match="batch_size"):
        LiteLLMEmbeddings("openai/x", batch_size=0)


@pytest.mark.unit
def test_empty_input_makes_no_calls():
    emb = LiteLLMEmbeddings("openai/x")
    with patch("server.app.models.litellm_embeddings.litellm.embedding") as mock_embed:
        result = emb.embed_documents([])

    assert mock_embed.call_count == 0
    assert result == []


# ---------------------------------------------------------------------------
# Async paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_aembed_documents_chunks():
    emb = LiteLLMEmbeddings("oci/cohere.embed", batch_size=96)

    async def fake_aembed(input, **_):
        return _embedding_response(len(input))

    with patch("server.app.models.litellm_embeddings.litellm.aembedding", side_effect=fake_aembed):
        result = await emb.aembed_documents(["t"] * 150)

    assert len(result) == 150


@pytest.mark.unit
async def test_aembed_query_one_call():
    emb = LiteLLMEmbeddings("openai/x")

    async def fake_aembed(input, **_):
        return _embedding_response(len(input), dims=3)

    with patch("server.app.models.litellm_embeddings.litellm.aembedding", side_effect=fake_aembed):
        result = await emb.aembed_query("hello")

    assert result == [0.0, 0.0, 0.0]
