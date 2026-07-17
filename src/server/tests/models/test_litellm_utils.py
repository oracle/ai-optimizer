"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for LiteLLM configuration builder and embedding client factory.
"""
# spell-checker: disable

from unittest.mock import MagicMock, mock_open, patch

import pytest
from pydantic import SecretStr

from server.app.core.settings import settings
from server.app.models.litellm_embeddings import LiteLLMEmbeddings
from server.app.models.litellm_utils import (
    SMALL_MODEL_THRESHOLD_B,
    LiteLlmModelSpec,
    extract_parameter_count,
    find_model,
    get_client_embed,
    is_small_model,
)
from server.app.models.schemas import ModelConfig, ModelIdentity
from server.app.oci.schemas import OciProfileConfig
from server.tests.constants import (
    TEST_OLLAMA_CHAT_KEY,
    TEST_OLLAMA_MODEL_ID,
    TEST_OPENAI_EMBED_ID,
    TEST_OPENAI_EMBED_KEY,
    TEST_OPENAI_MODEL_ID,
    TEST_OPENAI_MODEL_ID_MIXEDCASE,
    TEST_OPENAI_MODEL_KEY,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _restore_model_configs():
    """Save and restore settings.model_configs around each test."""
    original = settings.model_configs
    yield
    settings.model_configs = original


def _oci_profile(**overrides) -> OciProfileConfig:
    defaults = {
        "auth_profile": "TEST",
        "tenancy": "ocid1.tenancy.oc1..test",
        "user": "ocid1.user.oc1..test",
        "fingerprint": "aa:bb:cc",
        "key_file": "/path/to/key",
        "genai_region": "us-chicago-1",
        "genai_compartment_id": "ocid1.compartment.oc1..test",
    }
    return OciProfileConfig(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# find_model
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_find_model_exact_match():
    """Returns a matching ModelConfig when provider and id match."""
    mc = ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=True)
    settings.model_configs = [mc]
    result = find_model("openai", TEST_OPENAI_MODEL_ID)
    assert result is mc


@pytest.mark.unit
def test_find_model_no_match():
    """Returns None when no model matches."""
    settings.model_configs = [ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=True)]
    assert find_model("openai", "nonexistent") is None


@pytest.mark.unit
def test_find_model_type_filter():
    """Filters by model_type when specified."""
    mc = ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=True)
    settings.model_configs = [mc]
    assert find_model("openai", TEST_OPENAI_MODEL_ID, model_type="embed") is None
    assert find_model("openai", TEST_OPENAI_MODEL_ID, model_type="ll") is mc


@pytest.mark.unit
def test_find_model_enabled_only():
    """Disabled models are excluded by default."""
    mc = ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=False)
    settings.model_configs = [mc]
    assert find_model("openai", TEST_OPENAI_MODEL_ID) is None


@pytest.mark.unit
def test_find_model_disabled_included():
    """enabled_only=False includes disabled models."""
    mc = ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=False)
    settings.model_configs = [mc]
    assert find_model("openai", TEST_OPENAI_MODEL_ID, enabled_only=False) is mc


@pytest.mark.unit
def test_find_model_strips_ollama_latest_tag():
    """find_model strips :latest from Ollama model IDs for matching."""
    mc = ModelConfig(id="qwen3-embedding", type="embed", provider="ollama", enabled=True)
    settings.model_configs = [mc]
    assert find_model("ollama", "qwen3-embedding:latest", model_type="embed") is mc


# ---------------------------------------------------------------------------
# LiteLlmModelSpec
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_model_spec_basic():
    """Basic spec has normalized model_key, api_base, and api_key."""
    mc = ModelConfig(
        id=TEST_OPENAI_MODEL_ID,
        type="ll",
        provider="openai",
        api_base="https://api.openai.com/v1",
        api_key=SecretStr("sk-123"),
        temperature=0.7,
        enabled=True,
    )
    settings.model_configs = [mc]
    spec = LiteLlmModelSpec("openai", TEST_OPENAI_MODEL_ID)
    assert spec.model_key == TEST_OPENAI_MODEL_KEY
    assert spec.api_base == "https://api.openai.com/v1"
    assert spec.api_key == "sk-123"
    assert spec.temperature == 0.7  # Falls back to ModelConfig default


@pytest.mark.unit
def test_model_spec_caller_overrides_win():
    """Caller-provided generation params override ModelConfig defaults."""
    mc = ModelConfig(
        id=TEST_OPENAI_MODEL_ID,
        type="ll",
        provider="openai",
        temperature=0.7,
        max_tokens=1000,
        enabled=True,
    )
    settings.model_configs = [mc]
    spec = LiteLlmModelSpec("openai", TEST_OPENAI_MODEL_ID, temperature=0.3, max_tokens=500)
    assert spec.temperature == 0.3
    assert spec.max_tokens == 500


@pytest.mark.unit
def test_model_spec_case_insensitive_provider():
    """Mixed-case provider strings resolve and normalize to canonical casing."""
    mc = ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=True)
    settings.model_configs = [mc]
    spec = LiteLlmModelSpec("OpenAI", TEST_OPENAI_MODEL_ID)
    assert spec.model_key == TEST_OPENAI_MODEL_KEY  # Canonical casing from ModelConfig
    assert spec.original_provider == "OpenAI"  # Raw input preserved
    assert spec.normalized_provider == "openai"


@pytest.mark.unit
def test_model_spec_case_insensitive_model_id():
    """Mixed-case model_id strings resolve and normalize to canonical casing."""
    mc = ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=True)
    settings.model_configs = [mc]
    spec = LiteLlmModelSpec("openai", TEST_OPENAI_MODEL_ID_MIXEDCASE)
    assert spec.model_key == TEST_OPENAI_MODEL_KEY  # Canonical casing from ModelConfig
    assert spec.model_id == TEST_OPENAI_MODEL_ID


@pytest.mark.unit
def test_model_spec_not_found():
    """Raises ValueError when the model is not in settings."""
    settings.model_configs = []
    with pytest.raises(ValueError, match="not found"):
        LiteLlmModelSpec("openai", "missing")


@pytest.mark.unit
def test_model_spec_none_provider_raises_valueerror():
    """None provider/model_id raises ValueError, not AttributeError."""
    settings.model_configs = []
    with pytest.raises(ValueError, match="not found"):
        LiteLlmModelSpec(None, None)


@pytest.mark.unit
def test_model_spec_ollama_ll_keeps_prefix():
    """Ollama 'll' type models are rewritten to ollama_chat for /api/chat support."""
    mc = ModelConfig(id=TEST_OLLAMA_MODEL_ID, type="ll", provider="ollama", enabled=True)
    settings.model_configs = [mc]
    spec = LiteLlmModelSpec("ollama", TEST_OLLAMA_MODEL_ID)
    assert spec.model_key == TEST_OLLAMA_CHAT_KEY
    assert spec.normalized_provider == "ollama_chat"


@pytest.mark.unit
def test_model_spec_ollama_embed_no_rewrite():
    """Ollama 'embed' type models keep the ollama/ prefix."""
    mc = ModelConfig(id="nomic-embed", type="embed", provider="ollama", enabled=True)
    settings.model_configs = [mc]
    spec = LiteLlmModelSpec("ollama", "nomic-embed")
    assert spec.model_key == "ollama/nomic-embed"


@pytest.mark.unit
def test_model_spec_cohere_rewrites_api_base():
    """Cohere models get a rewritten api_base to the compatibility endpoint."""
    mc = ModelConfig(
        id="command-r",
        type="ll",
        provider="cohere",
        api_base="https://original.example.com",
        enabled=True,
    )
    settings.model_configs = [mc]
    spec = LiteLlmModelSpec("cohere", "command-r")
    assert spec.api_base == "https://api.cohere.ai/compatibility/v1"


@pytest.mark.unit
def test_model_spec_cohere_rewrites_api_base_when_none():
    """Cohere models with no api_base still get the compatibility endpoint."""
    mc = ModelConfig(id="command-r", type="ll", provider="cohere", enabled=True)
    settings.model_configs = [mc]
    spec = LiteLlmModelSpec("cohere", "command-r")
    assert spec.api_base == "https://api.cohere.ai/compatibility/v1"


@pytest.mark.unit
def test_model_spec_xai_drops_penalties():
    """xAI models have presence_penalty and frequency_penalty stripped."""
    mc = ModelConfig(
        id="grok-1",
        type="ll",
        provider="xai",
        presence_penalty=0.5,
        frequency_penalty=0.5,
        enabled=True,
    )
    settings.model_configs = [mc]
    spec = LiteLlmModelSpec("xai", "grok-1")
    assert spec.presence_penalty is None
    assert spec.frequency_penalty is None


@pytest.mark.unit
def test_model_spec_ollama_drops_penalties():
    """Ollama models have presence_penalty and frequency_penalty stripped."""
    mc = ModelConfig(
        id=TEST_OLLAMA_MODEL_ID,
        type="ll",
        provider="ollama",
        presence_penalty=0.5,
        frequency_penalty=0.5,
        enabled=True,
    )
    settings.model_configs = [mc]
    spec = LiteLlmModelSpec("ollama", TEST_OLLAMA_MODEL_ID)
    assert spec.presence_penalty is None
    assert spec.frequency_penalty is None


# ---------------------------------------------------------------------------
# LiteLlmModelSpec.to_litellm_kwargs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_to_litellm_kwargs_basic():
    """to_litellm_kwargs produces correct dict with model, api_base, drop_params."""
    mc = ModelConfig(
        id=TEST_OPENAI_MODEL_ID,
        type="ll",
        provider="openai",
        api_base="https://api.openai.com/v1",
        api_key=SecretStr("sk-123"),
        temperature=0.7,
        enabled=True,
    )
    settings.model_configs = [mc]

    with patch("server.app.models.litellm_utils.litellm") as mock_litellm:
        mock_litellm.get_supported_openai_params.return_value = ["temperature", "max_tokens"]
        spec = LiteLlmModelSpec("openai", TEST_OPENAI_MODEL_ID)
        result = spec.to_litellm_kwargs()

    assert result["model"] == TEST_OPENAI_MODEL_KEY
    assert result["base_url"] == "https://api.openai.com/v1"
    assert result["drop_params"] is True
    assert result["api_key"] == "sk-123"
    assert result["temperature"] == 0.7


@pytest.mark.unit
def test_to_litellm_kwargs_ollama():
    """Ollama LL model keeps ollama/ prefix in kwargs."""
    mc = ModelConfig(id=TEST_OLLAMA_MODEL_ID, type="ll", provider="ollama", enabled=True)
    settings.model_configs = [mc]

    with patch("server.app.models.litellm_utils.litellm") as mock_litellm:
        mock_litellm.get_supported_openai_params.return_value = []
        spec = LiteLlmModelSpec("ollama", TEST_OLLAMA_MODEL_ID)
        result = spec.to_litellm_kwargs()

    assert result["model"] == TEST_OLLAMA_CHAT_KEY


@pytest.mark.unit
def test_to_litellm_kwargs_no_supported_params():
    """Handles None from litellm.get_supported_openai_params gracefully."""
    mc = ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=True, temperature=0.7)
    settings.model_configs = [mc]

    with patch("server.app.models.litellm_utils.litellm") as mock_litellm:
        mock_litellm.get_supported_openai_params.return_value = None
        spec = LiteLlmModelSpec("openai", TEST_OPENAI_MODEL_ID)
        result = spec.to_litellm_kwargs()

    assert result["model"] == TEST_OPENAI_MODEL_KEY
    assert result["drop_params"] is True
    assert "temperature" not in result  # Not in supported_params


@pytest.mark.unit
def test_to_litellm_kwargs_oci_with_signer():
    """OCI provider with signer includes oci_signer in kwargs."""
    mc = ModelConfig(id="cohere.command-r", type="ll", provider="oci", enabled=True)
    settings.model_configs = [mc]
    profile = _oci_profile()
    mock_signer = MagicMock()

    with (
        patch("server.app.models.litellm_utils.litellm") as mock_litellm,
        patch("server.app.models.litellm_utils.get_signer", return_value=mock_signer),
    ):
        mock_litellm.get_supported_openai_params.return_value = []
        spec = LiteLlmModelSpec("oci", "cohere.command-r", oci_profile=profile)
        result = spec.to_litellm_kwargs()

    assert result["oci_region"] == "us-chicago-1"
    assert result["oci_compartment_id"] == "ocid1.compartment.oc1..test"
    assert result["oci_signer"] is mock_signer


@pytest.mark.unit
def test_to_litellm_kwargs_oci_without_signer():
    """OCI provider without signer falls back to API key auth fields."""
    mc = ModelConfig(id="cohere.command-r", type="ll", provider="oci", enabled=True)
    settings.model_configs = [mc]
    profile = _oci_profile()

    with (
        patch("server.app.models.litellm_utils.litellm") as mock_litellm,
        patch("server.app.models.litellm_utils.get_signer", return_value=None),
    ):
        mock_litellm.get_supported_openai_params.return_value = []
        spec = LiteLlmModelSpec("oci", "cohere.command-r", oci_profile=profile)
        result = spec.to_litellm_kwargs()

    assert result["oci_tenancy"] == "ocid1.tenancy.oc1..test"
    assert result["oci_user"] == "ocid1.user.oc1..test"
    assert result["oci_fingerprint"] == "aa:bb:cc"
    assert result["oci_key_file"] == "/path/to/key"
    assert "oci_signer" not in result


@pytest.mark.unit
def test_to_litellm_kwargs_oci_security_token_forwards_signer():
    """OCI security-token profile yields ``oci_signer`` in chat-completion kwargs.

    Regression-pin for the chat path. Both ``LiteLlmModelSpec`` (chat) and
    ``get_client_embed`` (embed) route through ``build_oci_litellm_params`` →
    ``get_signer``; this asserts the chat side gets the same security-token
    coverage as the embed side, not API-key fields.
    """
    mc = ModelConfig(id="cohere.command-r", type="ll", provider="oci", enabled=True)
    settings.model_configs = [mc]
    profile = _oci_profile(
        authentication="security_token",
        security_token_file="/path/to/token",
    )
    mock_sec_signer = MagicMock(name="SecurityTokenSigner")
    mock_private_key = MagicMock(name="PrivateKey")

    with (
        patch("server.app.models.litellm_utils.litellm") as mock_litellm,
        patch("builtins.open", mock_open(read_data="token-data")),
        patch(
            "server.app.oci.client.oci.signer.load_private_key_from_file",
            return_value=mock_private_key,
        ),
        patch(
            "server.app.oci.client.oci.auth.signers.SecurityTokenSigner",
            return_value=mock_sec_signer,
        ),
    ):
        mock_litellm.get_supported_openai_params.return_value = []
        spec = LiteLlmModelSpec("oci", "cohere.command-r", oci_profile=profile)
        result = spec.to_litellm_kwargs()

    assert result["oci_signer"] is mock_sec_signer
    assert "oci_user" not in result
    assert "oci_fingerprint" not in result
    assert "oci_key_file" not in result


# ---------------------------------------------------------------------------
# LiteLlmModelSpec class methods
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_from_ll_model_settings():
    """from_ll_model_settings extracts fields correctly."""
    mc = ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", enabled=True)
    settings.model_configs = [mc]
    ll_model = MagicMock()
    ll_model.provider = "openai"
    ll_model.id = TEST_OPENAI_MODEL_ID
    ll_model.temperature = 0.5
    ll_model.top_p = 0.9
    ll_model.max_tokens = 100
    ll_model.frequency_penalty = 0.1
    ll_model.presence_penalty = 0.2

    spec = LiteLlmModelSpec.from_ll_model_settings(ll_model)
    assert spec.temperature == 0.5
    assert spec.top_p == 0.9
    assert spec.max_tokens == 100
    assert spec.frequency_penalty == 0.1
    assert spec.presence_penalty == 0.2


@pytest.mark.unit
def test_litellm_model_spec_normalizes_provider_casing():
    """Provider stored with non-lowercase casing still routes to the OCI branch.

    Regression-pin: ``find_model`` is case-insensitive but the stored
    ``model_cfg.provider`` casing was being adopted verbatim, so a 'OCI' (or
    'Cohere') entry would skip every downstream lowercase-comparison and
    produce a model_key LiteLLM cannot route.
    """
    mc = ModelConfig(id="cohere.command-r", type="ll", provider="OCI", enabled=True)
    settings.model_configs = [mc]
    profile = _oci_profile()
    mock_signer = MagicMock()

    with (
        patch("server.app.models.litellm_utils.litellm") as mock_litellm,
        patch("server.app.models.litellm_utils.get_signer", return_value=mock_signer),
    ):
        mock_litellm.get_supported_openai_params.return_value = []
        spec = LiteLlmModelSpec("oci", "cohere.command-r", oci_profile=profile)

    assert spec.model_key == "oci/cohere.command-r"
    assert spec.oci_params.get("oci_signer") is mock_signer


@pytest.mark.unit
def test_from_model_identity():
    """from_model_identity creates a spec with no generation overrides."""
    mc = ModelConfig(id=TEST_OPENAI_MODEL_ID, type="ll", provider="openai", temperature=0.7, enabled=True)
    settings.model_configs = [mc]
    identity = ModelIdentity(provider="openai", id=TEST_OPENAI_MODEL_ID)

    spec = LiteLlmModelSpec.from_model_identity(identity)
    assert spec.model_key == TEST_OPENAI_MODEL_KEY
    assert spec.temperature == 0.7  # Falls back to ModelConfig


# ---------------------------------------------------------------------------
# get_client_embed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_client_embed_oci():
    """OCI provider builds a LiteLLMEmbeddings with OCI auth params."""
    mc = ModelConfig(id="cohere.embed-english", type="embed", provider="oci", enabled=True)
    settings.model_configs = [mc]
    profile = _oci_profile()
    mock_signer = MagicMock()

    with patch("server.app.models.litellm_utils.get_signer", return_value=mock_signer):
        result = get_client_embed(ModelIdentity(provider="oci", id="cohere.embed-english"), oci_profile=profile)

    assert isinstance(result, LiteLLMEmbeddings)
    assert result.model_key == "oci/cohere.embed-english"
    assert result.extra_params["oci_region"] == "us-chicago-1"
    assert result.extra_params["oci_compartment_id"] == "ocid1.compartment.oc1..test"
    assert result.extra_params["oci_signer"] is mock_signer


@pytest.mark.unit
def test_get_client_embed_oci_preserves_batch_chunking():
    """End-to-end: 200 inputs through get_client_embed(OCI) chunk to ≤96/call.

    Pins the chunking guarantee preserved from the prior OCIGenAIEmbeddings
    implementation through the LiteLLM swap.
    """
    mc = ModelConfig(id="cohere.embed-english-v3.0", type="embed", provider="oci", enabled=True)
    settings.model_configs = [mc]
    profile = _oci_profile()

    def fake_embed(input, **_):
        resp = MagicMock()
        resp.data = [{"embedding": [0.0] * 4} for _ in input]
        return resp

    with (
        patch("server.app.models.litellm_utils.get_signer", return_value=MagicMock()),
        patch("server.app.models.litellm_embeddings.litellm.embedding", side_effect=fake_embed) as mock_embed,
    ):
        client = get_client_embed(
            ModelIdentity(provider="oci", id="cohere.embed-english-v3.0"),
            oci_profile=profile,
        )
        result = client.embed_documents(["text"] * 200)

    assert len(result) == 200
    assert mock_embed.call_count == 3
    batch_sizes = [len(call.kwargs["input"]) for call in mock_embed.call_args_list]
    assert batch_sizes == [96, 96, 8]
    assert all(size <= 96 for size in batch_sizes)


@pytest.mark.unit
def test_get_client_embed_oci_security_token_forwards_signer():
    """OCI security-token profile yields a LiteLLMEmbeddings carrying ``oci_signer``.

    Regression-pin: ``build_oci_litellm_params`` previously did not handle
    ``authentication == "security_token"`` and fell through to API-key kwargs,
    which would fail authentication against OCI. The fix lives in
    ``get_signer``; this test proves the wired-through behavior.
    """
    mc = ModelConfig(id="cohere.embed-english-v3.0", type="embed", provider="oci", enabled=True)
    settings.model_configs = [mc]
    profile = _oci_profile(
        authentication="security_token",
        security_token_file="/path/to/token",
    )
    mock_sec_signer = MagicMock(name="SecurityTokenSigner")
    mock_private_key = MagicMock(name="PrivateKey")

    with (
        patch("builtins.open", mock_open(read_data="token-data")),
        patch(
            "server.app.oci.client.oci.signer.load_private_key_from_file",
            return_value=mock_private_key,
        ),
        patch(
            "server.app.oci.client.oci.auth.signers.SecurityTokenSigner",
            return_value=mock_sec_signer,
        ),
    ):
        result = get_client_embed(
            ModelIdentity(provider="oci", id="cohere.embed-english-v3.0"),
            oci_profile=profile,
        )

    assert isinstance(result, LiteLLMEmbeddings)
    assert result.extra_params.get("oci_signer") is mock_sec_signer
    # API-key fields must NOT leak in when a signer is constructed —
    # OCI would otherwise see a mixed auth payload.
    assert "oci_user" not in result.extra_params
    assert "oci_fingerprint" not in result.extra_params
    assert "oci_key_file" not in result.extra_params


@pytest.mark.unit
def test_get_client_embed_normalizes_provider_casing():
    """Provider stored as 'OCI' (uppercase) still attaches OCI auth.

    Regression-pin: ``find_model`` matched case-insensitively but the stored
    casing was being adopted verbatim, so an 'OCI' entry would skip the
    ``provider == "oci"`` branch and produce a model_key (``OCI/...``) that
    LiteLLM cannot route.
    """
    mc = ModelConfig(id="cohere.embed-english-v3.0", type="embed", provider="OCI", enabled=True)
    settings.model_configs = [mc]
    profile = _oci_profile()
    mock_signer = MagicMock()

    with patch("server.app.models.litellm_utils.get_signer", return_value=mock_signer):
        result = get_client_embed(
            ModelIdentity(provider="oci", id="cohere.embed-english-v3.0"),
            oci_profile=profile,
        )

    assert isinstance(result, LiteLLMEmbeddings)
    assert result.model_key == "oci/cohere.embed-english-v3.0"
    assert result.extra_params.get("oci_signer") is mock_signer
    assert result.batch_size == 96


@pytest.mark.unit
def test_get_client_embed_hosted_vllm():
    """hosted_vllm builds a LiteLLMEmbeddings keyed on hosted_vllm/<model>."""
    mc = ModelConfig(
        id="bge-m3",
        type="embed",
        provider="hosted_vllm",
        api_base="http://vllm:8000/v1",
        enabled=True,
    )
    settings.model_configs = [mc]

    result = get_client_embed(ModelIdentity(provider="hosted_vllm", id="bge-m3"))

    assert isinstance(result, LiteLLMEmbeddings)
    assert result.model_key == "hosted_vllm/bge-m3"
    assert result.api_base == "http://vllm:8000/v1"
    assert result.extra_params == {}


@pytest.mark.unit
def test_get_client_embed_cohere_does_not_rewrite_to_compatibility_endpoint():
    """Cohere-direct embed forwards the configured api_base verbatim.

    Regression-pin: a previous iteration mirrored the chat-path rewrite to
    ``/compatibility/v1`` for embed too — but litellm's cohere embed transform
    posts Cohere v2 embed payloads at the URL as-is, and the OpenAI-compat
    endpoint rejects them. The wrapper must hand litellm an embed-shaped URL
    (``…/v2/embed``), not the chat compatibility URL.
    """
    mc = ModelConfig(
        id="embed-english-light-v3.0",
        type="embed",
        provider="cohere",
        api_base="https://api.cohere.ai/v2/embed",
        api_key=SecretStr("co-key"),
        enabled=True,
    )
    settings.model_configs = [mc]

    result = get_client_embed(ModelIdentity(provider="cohere", id="embed-english-light-v3.0"))

    assert isinstance(result, LiteLLMEmbeddings)
    assert result.api_base == "https://api.cohere.ai/v2/embed"
    assert "/compatibility/v1" not in (result.api_base or "")


@pytest.mark.unit
def test_get_client_embed_default():
    """Default OpenAI provider builds a LiteLLMEmbeddings with api_key."""
    mc = ModelConfig(
        id=TEST_OPENAI_EMBED_ID,
        type="embed",
        provider="openai",
        api_key=SecretStr("sk-123"),
        enabled=True,
    )
    settings.model_configs = [mc]

    result = get_client_embed(ModelIdentity(provider="openai", id=TEST_OPENAI_EMBED_ID))

    assert isinstance(result, LiteLLMEmbeddings)
    assert result.model_key == TEST_OPENAI_EMBED_KEY
    assert result.api_key == "sk-123"


@pytest.mark.unit
def test_get_client_embed_not_found():
    """Raises ValueError when the embedding model is not found."""
    settings.model_configs = []
    with pytest.raises(ValueError, match="not found"):
        get_client_embed(ModelIdentity(provider="openai", id="missing"))


# ---------------------------------------------------------------------------
# extract_parameter_count / is_small_model / SMALL_MODEL_THRESHOLD_B
# ---------------------------------------------------------------------------


class TestExtractParameterCount:
    """Tests for extract_parameter_count function."""

    def test_simple_1b_model(self):
        """extract_parameter_count should extract 1B from simple model name."""
        assert extract_parameter_count("llama3.2:1b") == 1.0

    def test_simple_8b_model(self):
        """extract_parameter_count should extract 8B from model name."""
        assert extract_parameter_count("granite4.1:8b") == 8.0

    def test_uppercase_b(self):
        """extract_parameter_count should handle uppercase B."""
        assert extract_parameter_count("gemma3:1B") == 1.0

    def test_decimal_parameter_count(self):
        """extract_parameter_count should handle decimal parameter counts."""
        assert extract_parameter_count("phi4-mini:3.8b") == 3.8

    def test_8b_model(self):
        """extract_parameter_count should extract 8B from model name."""
        assert extract_parameter_count("llama3.1:8b") == 8.0

    def test_70b_model(self):
        """extract_parameter_count should extract 70B from model name."""
        assert extract_parameter_count("llama3:70b") == 70.0

    def test_no_parameter_count(self):
        """extract_parameter_count should return None for models without parameter count."""
        assert extract_parameter_count(TEST_OPENAI_MODEL_ID) is None

    def test_empty_string(self):
        """extract_parameter_count should return None for empty string."""
        assert extract_parameter_count("") is None

    def test_none_input(self):
        """extract_parameter_count should return None for None input."""
        assert extract_parameter_count(None) is None

    def test_provider_prefix(self):
        """extract_parameter_count should extract from provider/model format."""
        assert extract_parameter_count("ollama/llama3.2:1b") == 1.0

    def test_model_without_colon(self):
        """extract_parameter_count should extract from models without colon."""
        assert extract_parameter_count("gemma-7b") == 7.0

    def test_does_not_match_base_in_model_name(self):
        """extract_parameter_count should not match 'base' in model names."""
        assert extract_parameter_count("mxbai-embed-large") is None

    def test_does_not_match_bytes_notation(self):
        """extract_parameter_count should not match byte notations like '512b'."""
        assert extract_parameter_count("model-512bytes") is None


class TestIsSmallModel:
    """Tests for is_small_model function."""

    def test_1b_is_small(self):
        """is_small_model should return True for 1B models."""
        assert is_small_model("llama3.2:1b") is True

    def test_3b_is_small(self):
        """is_small_model should return True for 4B models."""
        assert is_small_model("granite4.1:8b") is False

    def test_3_8b_is_small(self):
        """is_small_model should return True for 3.8B models."""
        assert is_small_model("phi4-mini:3.8b") is True

    def test_7b_is_not_small(self):
        """is_small_model should return False for exactly 7B models (threshold)."""
        assert is_small_model("gemma-7b") is False

    def test_8b_is_not_small(self):
        """is_small_model should return False for 8B models."""
        assert is_small_model("llama3.1:8b") is False

    def test_70b_is_not_small(self):
        """is_small_model should return False for 70B models."""
        assert is_small_model("llama3:70b") is False

    def test_unknown_model_is_not_small(self):
        """is_small_model should return False for models without detectable param count."""
        assert is_small_model(TEST_OPENAI_MODEL_ID) is False

    def test_empty_string_is_not_small(self):
        """is_small_model should return False for empty string."""
        assert is_small_model("") is False

    def test_none_is_not_small(self):
        """is_small_model should return False for None input."""
        assert is_small_model(None) is False

    def test_with_provider_prefix(self):
        """is_small_model should work with provider/model format."""
        assert is_small_model("ollama/llama3.2:1b") is True
        assert is_small_model("ollama/llama3.1:8b") is False

    def test_gemma_1b(self):
        """is_small_model should detect gemma 1b as small."""
        assert is_small_model("gemma3:1b") is True

    def test_threshold_boundary(self):
        """is_small_model should correctly handle values near threshold."""
        assert is_small_model("model:6.9b") is True
        assert is_small_model("model:7b") is False
        assert is_small_model("model:7.1b") is False


class TestSmallModelThreshold:
    """Tests for SMALL_MODEL_THRESHOLD_B constant."""

    def test_threshold_is_7(self):
        """SMALL_MODEL_THRESHOLD_B should be 7."""
        assert SMALL_MODEL_THRESHOLD_B == 7

    def test_threshold_is_integer(self):
        """SMALL_MODEL_THRESHOLD_B should be an integer."""
        assert isinstance(SMALL_MODEL_THRESHOLD_B, int)
