"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Live OCI GenAI completion tests, parametrized over the models discovered
through the ``/v1/oci/genai/{profile}`` endpoint.

OCI's documented OpenAI offerings are ``openai.gpt-oss-120b`` and
``openai.gpt-oss-20b`` (open-weight reasoning models). Tests parametrize
over the real lineup discovered at runtime rather than guess, so the
results reflect whatever OCI actually serves in the configured region.

Skipped unless ``AIO_GENAI_COMPARTMENT_ID`` and ``AIO_GENAI_REGION`` are
set (typically via ``.env.pytest`` at the repo root).
"""

import os

import litellm
import pytest
from litellm import ModelResponse

pytestmark = [pytest.mark.live_oci, pytest.mark.integration]

_USER_MESSAGE = [{"role": "user", "content": "Reply with one word: ok"}]


def _complete_or_fail(**kwargs) -> ModelResponse:
    """Run a non-streaming completion; return the response on success.

    For these tests the diagnostic question is "does OCI reject this combination
    of params?", not "did the model produce visible output". gpt-oss models can
    burn the entire ``max_tokens`` budget on reasoning content with nothing left
    over for ``message.content`` — empty content is not a failure, only an
    exception is.
    """
    response = litellm.completion(**kwargs)
    if not isinstance(response, ModelResponse):
        raise TypeError(f"expected non-streaming response, got {type(response).__name__}")
    if not response.choices:
        raise AssertionError("no choices in response")
    return response


@pytest.fixture
def openai_ll_models(live_oci_genai_models) -> list[str]:
    """OpenAI-family CHAT models discovered in the configured region.

    Same ``model_name`` can appear across regions; restrict to
    ``AIO_GENAI_REGION`` (the region completion calls target) and dedupe.
    """
    region = os.environ["AIO_GENAI_REGION"]
    models = sorted({
        m["model_name"]
        for m in live_oci_genai_models
        if (m.get("vendor") or "").lower() == "openai"
        and "CHAT" in (m.get("capabilities") or [])
        and m.get("region") == region
    })
    if not models:
        pytest.skip(
            f"no OpenAI-family CHAT models in region {region} "
            "(OCI's lineup in this region exposes none, or the model_name/vendor shape changed)"
        )
    return models


def _litellm_id(model_id: str) -> str:
    """LiteLLM expects the ``oci/`` provider prefix on the model name."""
    return f"oci/{model_id}"


# (label, call-kwargs, stream) — every row exercises OCI's acceptance of a
# specific parameter combination against every discovered OpenAI-family model.
_COMPLETION_CASES = [
    ("max_tokens", {"max_tokens": 20}, False),
    ("max_completion_tokens", {"max_completion_tokens": 20}, False),
    (
        "sampling_controls",
        {
            "max_tokens": 20,
            "temperature": 0.5,
            "top_p": 0.9,
            "frequency_penalty": 0.1,
            "presence_penalty": 0.2,
        },
        False,
    ),
    ("streaming", {"max_tokens": 20}, True),
]


@pytest.mark.parametrize("label,call_kwargs,stream", _COMPLETION_CASES, ids=[c[0] for c in _COMPLETION_CASES])
def test_openai_lineup_accepts(label, call_kwargs, stream, openai_ll_models, live_oci_litellm_kwargs):
    """OCI accepts the parameter combination for each discovered OpenAI-family model.

    Per-model outcome is accumulated into a single ``pytest.fail`` so that one
    rejecting model doesn't mask the others — useful when OCI's lineup grows.
    Pass means LiteLLM's OCI transform forwards the params and OCI returns a
    response; fail with a parameter-specific error means either upstream
    LiteLLM or OCI itself needs a fix (this layer trusts both).
    """
    failures: list[str] = []
    for model_id in openai_ll_models:
        try:
            if stream:
                chunks = list(
                    litellm.completion(
                        model=_litellm_id(model_id),
                        messages=_USER_MESSAGE,
                        stream=True,
                        **call_kwargs,
                        **live_oci_litellm_kwargs,
                    )
                )
                if not chunks:
                    raise AssertionError("no chunks yielded")
            else:
                _complete_or_fail(
                    model=_litellm_id(model_id),
                    messages=_USER_MESSAGE,
                    **call_kwargs,
                    **live_oci_litellm_kwargs,
                )
        except Exception as exc:  # noqa: BLE001 — surface per-model outcome
            failures.append(f"{model_id}: {exc!r}")
    if failures:
        pytest.fail(f"{label} rejected for: " + "; ".join(failures))
