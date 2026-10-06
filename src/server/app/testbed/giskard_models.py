"""
Copyright (c) 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Giskard model adapters for configured Testbed LiteLLM calls.
"""
# spell-checker:ignore giskard litellm

from collections.abc import Sequence
from typing import Any, cast, override

import litellm
from giskard.agents.generators import BaseGenerator, GenerationParams, LiteLLMGenerator
from giskard.llm.types import ChatMessage, Choice, CompletionResponse
from pydantic import Field


@BaseGenerator.register("testbed_litellm")
class TestbedLiteLLMGenerator(LiteLLMGenerator):
    """Pass the selected client's LiteLLM credentials through Giskard."""

    request_config: dict[str, Any] = Field(default_factory=dict, exclude=True, repr=False)

    @override
    async def _call_model(
        self,
        messages: Sequence[ChatMessage],
        params: GenerationParams,
        metadata: dict[str, Any] | None = None,
    ) -> CompletionResponse:
        wire_params = params.model_dump(exclude={"tools"}, exclude_unset=True)
        if params.tools:
            wire_params["tools"] = self._serialize_tools(params.tools)
        if metadata:
            wire_params["metadata"] = metadata
        self._normalize_response_format(litellm, wire_params)
        request = {
            **self.request_config,
            **wire_params,
            "model": self.model,
            "messages": self._serialize_messages(messages),
        }
        response = cast(litellm.ModelResponse, await litellm.acompletion(**request))
        return CompletionResponse(
            choices=[
                Choice(
                    message=self._deserialize_response(choice.message),
                    finish_reason=choice.finish_reason,
                )
                for choice in response.choices
            ]
        )


def giskard_generator(config: dict[str, Any]) -> TestbedLiteLLMGenerator:
    """Create a Giskard generator from a Testbed LiteLLM config."""
    options = dict(config)
    model = options.pop("model")
    temperature = options.pop("temperature", None)
    max_tokens = options.pop("max_tokens", None)
    generator = TestbedLiteLLMGenerator(model=model, request_config=options)
    params = {}
    if temperature is not None:
        params["temperature"] = temperature
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    return generator.with_params(**params) if params else generator
