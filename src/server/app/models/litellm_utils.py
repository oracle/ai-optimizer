"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LiteLLM configuration builder and embedding client factory.
"""
# spell-checker:ignore ollama genai litellm ocigenai vllm acompletion qwen

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import litellm
from langchain_core.embeddings import Embeddings

from server.app.core.secrets import reveal
from server.app.core.settings import settings
from server.app.models.connectivity import _normalize_ollama_name as _strip_latest
from server.app.models.litellm_embeddings import LiteLLMEmbeddings
from server.app.models.schemas import ModelConfig, ModelIdentity
from server.app.oci.client import get_signer
from server.app.oci.schemas import OciProfileConfig
from server.app.runtime.ollama_tools import normalize_ollama_provider

LOGGER = logging.getLogger(__name__)

#############################################################################
# CPU OPTIMIZATION
#############################################################################
# Pattern to extract parameter count from model names (e.g., "llama3.2:1b" -> 1.0)
PARAM_PATTERN = re.compile(r"(\d+(?:\.\d+)?)[bB](?![a-zA-Z])")
SMALL_MODEL_THRESHOLD_B = 7


def extract_parameter_count(model_id: Optional[str]) -> Optional[float]:
    """Extract parameter count from model name.

    Parses model identifiers to find parameter counts indicated by patterns
    like '1b', '4b', '7b', etc.

    Returns:
        Parameter count in billions as a float, or None if not found.
    """
    if not model_id:
        return None

    match = PARAM_PATTERN.search(model_id)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def is_small_model(model_id: Optional[str]) -> bool:
    """Check if model is a small model based on parameter count.

    A model is considered "small" if its parameter count can be extracted
    from the model name and is less than SMALL_MODEL_THRESHOLD_B (7B).
    """
    param_count = extract_parameter_count(model_id)
    if param_count is None:
        return False
    return param_count < SMALL_MODEL_THRESHOLD_B


def find_model(
    provider: str,
    model_id: str,
    model_type: Optional[str] = None,
    enabled_only: bool = True,
    case_insensitive: bool = False,
) -> Optional[ModelConfig]:
    """Search ``settings.model_configs`` for a matching model.

    For Ollama models the ``':latest'`` tag is stripped before comparison so that
    a vector store recorded as ``ollama/qwen3-embedding:latest`` still resolves to
    the discovered model ``ollama/qwen3-embedding``.
    """
    is_ollama = provider.lower() in ("ollama", "ollama_chat")
    lookup_id = _strip_latest(model_id) if is_ollama else model_id

    for mc in settings.model_configs:
        mc_id = _strip_latest(mc.id or "") if is_ollama else (mc.id or "")
        if case_insensitive:
            if (mc.provider or "").lower() != provider.lower() or mc_id.lower() != lookup_id.lower():
                continue
        elif mc.provider != provider or mc_id != lookup_id:
            continue
        if model_type and mc.type != model_type:
            continue
        if enabled_only and not mc.enabled:
            continue
        return mc
    return None


# Providers/models where frequency_penalty and presence_penalty cause errors.
# OCI forwards these to the upstream model which may reject them;
# litellm's drop_params does not catch provider-level rejections.
_PENALTY_UNSUPPORTED_PATTERNS = ("xai", "ollama")


def strip_unsupported_penalties(
    model_key: str,
    frequency_penalty: Optional[float],
    presence_penalty: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """Return (frequency_penalty, presence_penalty), zeroing out values for models that reject them."""
    model_lower = model_key.lower()
    if any(p in model_lower for p in _PENALTY_UNSUPPORTED_PATTERNS):
        return None, None
    return frequency_penalty, presence_penalty


def build_oci_litellm_params(oci_profile: OciProfileConfig) -> dict:
    """Build OCI auth params dict for litellm calls.

    Returns a dict containing ``oci_region``, ``oci_compartment_id``, and
    either an ``oci_signer`` (for instance principal / workload identity) or
    individual API-key fields (``oci_tenancy``, ``oci_user``, ``oci_fingerprint``,
    and either ``oci_key`` for inline PEM content or ``oci_key_file`` for a
    filesystem path). LiteLLM's OCI provider accepts either key form.
    """
    params: dict[str, object] = {
        "oci_region": oci_profile.genai_region,
        "oci_compartment_id": oci_profile.genai_compartment_id,
    }
    signer = get_signer(oci_profile)
    if signer:
        params["oci_signer"] = signer
    else:
        params.update(
            {
                "oci_tenancy": oci_profile.tenancy,
                "oci_user": oci_profile.user,
                "oci_fingerprint": oci_profile.fingerprint,
            }
        )
        if oci_profile.key_content:
            params["oci_key"] = reveal(oci_profile.key_content)
        elif oci_profile.key_file:
            params["oci_key_file"] = oci_profile.key_file
    return params


class LiteLlmModelSpec:
    """Unified LiteLLM model configuration with provider normalization.

    Single source of truth for resolving a provider/model_id pair against
    settings, applying provider-specific adjustments (ollama→ollama_chat,
    cohere api_base, penalty stripping), and producing kwargs for
    ``litellm.acompletion()``.

    The AgentSpec layer (``build_llm_config``) reads the normalized
    attributes to construct a ``LiteLlmConfig`` for serialization.

    Parameters
    ----------
    provider:
        Raw provider string (e.g. "openai", "ollama", "oci").
    model_id:
        Model name within the provider (e.g. "gpt-5.4-mini", "granite4.1:8b").
    temperature, top_p, max_tokens, frequency_penalty, presence_penalty:
        Caller-provided overrides.  When ``None``, the value from the
        matching ``ModelConfig`` in settings is used as the default.
    oci_profile:
        Optional OCI profile for auth parameter injection.
    """

    def __init__(
        self,
        provider: Optional[str],
        model_id: Optional[str],
        *,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        oci_profile: Optional[OciProfileConfig] = None,
    ) -> None:
        provider = provider or ""
        model_id = model_id or ""
        # Accept ollama_chat as alias so round-trips through normalized_provider work
        if provider == "ollama_chat":
            provider = "ollama"
        model_cfg = find_model(provider, model_id, enabled_only=False, case_insensitive=True)
        if model_cfg is None:
            raise ValueError(f"Model {provider}/{model_id} not found in model_configs")

        self.original_provider = provider
        # Use canonical provider from settings for LiteLLM routing.
        # Lowercase because find_model matched case-insensitively but stored
        # casing may differ from LiteLLM's lowercase provider strings, and
        # every downstream check (normalize_ollama_provider, cohere/oci
        # branches) is case-sensitive.
        provider = (model_cfg.provider or provider).lower()
        model_id = model_cfg.id or model_id
        self.model_id = model_id
        self.model_type = model_cfg.type
        self.api_key: Optional[str] = reveal(model_cfg.api_key)
        self.api_base: Optional[str] = model_cfg.api_base

        # ── Provider normalization ──────────────────────────────────

        provider = normalize_ollama_provider(provider, self.model_type)
        self.model_key = f"{provider}/{model_id}"

        # Cohere (direct, not OCI Cohere): rewrite api_base to the compatibility endpoint
        if self.model_key.startswith("cohere/"):
            parsed = urlparse(self.api_base or "")
            self.api_base = f"{parsed.scheme or 'https'}://api.cohere.ai/compatibility/v1"

        # ── Generation params (caller wins, fall back to ModelConfig) ─
        self.temperature = temperature if temperature is not None else model_cfg.temperature
        self.top_p = top_p if top_p is not None else model_cfg.top_p
        self.max_tokens = max_tokens if max_tokens is not None else model_cfg.max_tokens

        raw_freq = frequency_penalty if frequency_penalty is not None else model_cfg.frequency_penalty
        raw_pres = presence_penalty if presence_penalty is not None else model_cfg.presence_penalty
        self.frequency_penalty, self.presence_penalty = strip_unsupported_penalties(self.model_key, raw_freq, raw_pres)

        # ── OCI auth ────────────────────────────────────────────────
        self.oci_params: dict = {}
        if provider == "oci" and oci_profile:
            self.oci_params = build_oci_litellm_params(oci_profile)

        LOGGER.info("LiteLlmModelSpec: model_key=%s api_base=%s", self.model_key, self.api_base)

    # ── Class methods ───────────────────────────────────────────────

    @classmethod
    def from_ll_model_settings(cls, ll_model, oci_profile: Optional[OciProfileConfig] = None) -> "LiteLlmModelSpec":
        """Build from an ``LLModelSettings`` (or any object with the same fields)."""
        return cls(
            provider=ll_model.provider,
            model_id=ll_model.id,
            temperature=ll_model.temperature,
            top_p=ll_model.top_p,
            max_tokens=ll_model.max_tokens,
            frequency_penalty=ll_model.frequency_penalty,
            presence_penalty=ll_model.presence_penalty,
            oci_profile=oci_profile,
        )

    @classmethod
    def from_model_identity(
        cls, identity: ModelIdentity, oci_profile: Optional[OciProfileConfig] = None
    ) -> "LiteLlmModelSpec":
        """Build from a ``ModelIdentity`` (provider + id only, no overrides)."""
        return cls(provider=identity.provider or "", model_id=identity.id or "", oci_profile=oci_profile)

    # ── Output methods ──────────────────────────────────────────────

    @property
    def normalized_provider(self) -> str:
        """Provider extracted from the normalized ``model_key``."""
        return self.model_key.split("/", 1)[0]

    def to_litellm_kwargs(self) -> dict:
        """Build a kwargs dict for ``litellm.acompletion()``."""
        supported_params = litellm.get_supported_openai_params(model=self.model_key)
        if not supported_params:
            LOGGER.warning("No supported params for model=%s — generation params will not be forwarded", self.model_key)
            supported_params = []

        kwargs: dict = {}
        for param_name, value in [
            ("temperature", self.temperature),
            ("top_p", self.top_p),
            ("max_tokens", self.max_tokens),
            ("frequency_penalty", self.frequency_penalty),
            ("presence_penalty", self.presence_penalty),
        ]:
            if value is not None and param_name in supported_params:
                kwargs[param_name] = value

        kwargs["model"] = self.model_key
        # LiteLLM's ollama provider breaks tool call parsing when api_base is
        # passed as a call parameter; base_url works correctly for all providers.
        if self.api_base:
            kwargs["base_url"] = self.api_base
        kwargs["drop_params"] = True
        if self.api_key:
            kwargs["api_key"] = self.api_key
        kwargs.update(self.oci_params)

        LOGGER.info(
            "LiteLLM kwargs: %s",
            {k: v for k, v in kwargs.items() if k != "api_key"},
        )
        return kwargs


# OCI custom-trained endpoints are addressed by OCID rather than model name.
# litellm.embedding's OCI provider needs ``oci_serving_mode=DEDICATED`` +
# ``oci_endpoint_id`` for these — without it OCI rejects the request.
_OCI_CUSTOM_ENDPOINT_PREFIX = "ocid1.generativeaiendpoint"

# Per-provider per-call input caps. OCI Cohere hard-caps at 96; OpenAI/Cohere-
# direct allow far more, so a universal 96 floor wastes round-trips for them.
_EMBED_BATCH_SIZES = {
    "oci": 96,
    "cohere": 96,
    "openai": 1024,
    "hosted_vllm": 1024,
    "huggingface": 256,
}


def get_client_embed(
    embedding_model: ModelIdentity,
    oci_profile: Optional[OciProfileConfig] = None,
) -> Embeddings:
    """Create a LangChain Embeddings client for the given model.

    All providers route through ``litellm.embedding`` via ``LiteLLMEmbeddings``.
    For OCI, auth params from the profile are forwarded as litellm kwargs, and
    custom-trained endpoint OCIDs are auto-routed via DEDICATED serving mode.
    """
    provider = embedding_model.provider or ""
    model_id = embedding_model.id or ""

    model_cfg = find_model(
        provider, model_id, model_type="embed", enabled_only=False, case_insensitive=True
    )
    if model_cfg is None:
        raise ValueError(f"Embedding model {provider}/{model_id} not found in model_configs")
    # Lowercase because find_model matched case-insensitively but stored casing
    # may differ from LiteLLM's lowercase provider strings; every downstream
    # check (oci/cohere branches, batch-size lookup, model_key) is
    # case-sensitive.
    provider = (model_cfg.provider or provider).lower()
    model_id = model_cfg.id or model_id

    extra_params: dict = {}
    if provider == "oci":
        if oci_profile is None:
            raise ValueError(f"OCI embedding model {provider}/{model_id} requires an oci_profile")
        extra_params = build_oci_litellm_params(oci_profile)
        if model_id.startswith(_OCI_CUSTOM_ENDPOINT_PREFIX):
            extra_params["oci_serving_mode"] = "DEDICATED"
            extra_params["oci_endpoint_id"] = model_id

    return LiteLLMEmbeddings(
        model_key=f"{provider}/{model_id}",
        api_key=reveal(model_cfg.api_key) if model_cfg.api_key else None,
        api_base=model_cfg.api_base,
        batch_size=_EMBED_BATCH_SIZES.get(provider, 96),
        extra_params=extra_params,
    )
