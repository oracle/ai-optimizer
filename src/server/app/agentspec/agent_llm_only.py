"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LLM-Only Agent — pure conversation with no tools.

Defines the AgentSpec configuration only. No runtime imports.
"""
# spell-checker: ignore agentspec litellm llms pyagentspec

from pyagentspec.agent import Agent as AgentSpecAgent
from pyagentspec.llms import LlmGenerationConfig

from server.app.agentspec.adapters.litellm import LiteLlmConfig
from server.app.core.schemas import ClientSettings
from server.app.models.litellm_utils import LiteLlmModelSpec


def build_llm_config(client_settings: ClientSettings) -> LiteLlmConfig:
    """Build a LiteLlmConfig (AgentSpec component) from client_settings.ll_model.

    Delegates to ``LiteLlmModelSpec`` for settings lookup and provider
    normalization, then converts the resolved attributes into an AgentSpec
    ``LiteLlmConfig`` suitable for serialization or runtime loading.
    """
    spec = LiteLlmModelSpec.from_ll_model_settings(client_settings.ll_model)

    gen_params = {}
    if spec.temperature is not None:
        gen_params["temperature"] = spec.temperature
    if spec.top_p is not None:
        gen_params["top_p"] = spec.top_p
    gen_config = LlmGenerationConfig(**gen_params) if gen_params else None

    return LiteLlmConfig(
        id=spec.model_key,
        name=spec.model_key,
        provider=spec.normalized_provider,
        model_id=spec.model_id,
        default_generation_parameters=gen_config,
        api_key=spec.api_key,
        api_base=spec.api_base,
        max_tokens=spec.max_tokens,
        frequency_penalty=spec.frequency_penalty,
        presence_penalty=spec.presence_penalty,
    )


def build_llm_only_agentspec(
    client_settings: ClientSettings,
    system_prompt: str,
) -> AgentSpecAgent:
    """Build a pyagentspec Agent definition for LLM-only conversation."""
    llm_config = build_llm_config(client_settings)
    return AgentSpecAgent(
        id="llm-only-agent",
        name="LLM Only Agent",
        llm_config=llm_config,
        system_prompt=system_prompt,
        tools=[],
        toolboxes=[],
        human_in_the_loop=True,
    )
