"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

LiteLLM AgentSpec configuration component.

Defines `LiteLlmConfig` — a pyagentspec LlmConfig subclass that represents
a LiteLLM-backed LLM in portable AgentSpec YAML/JSON configurations.
"""
# spell-checker: ignore pyagentspec litellm llms ollama pydanticdeserializationplugin pydanticserializationplugin

from typing import Dict, Optional, Type

from pyagentspec.llms import LlmConfig
from pyagentspec.sensitive_field import SensitiveField
from pyagentspec.serialization.pydanticdeserializationplugin import (
    PydanticComponentDeserializationPlugin,
)
from pyagentspec.serialization.pydanticserializationplugin import (
    PydanticComponentSerializationPlugin,
)
from pydantic import BaseModel


class LiteLlmConfig(LlmConfig):
    """AgentSpec LLM configuration for LiteLLM-backed models.

    When serialized to YAML/JSON, produces a portable config with
    component_type "LiteLlmConfig".  At load time, the WayFlow plugin
    converts this into a `LiteLlmModel` runtime instance.

    Parameters
    ----------
    provider:
        LiteLLM provider prefix (e.g. "openai", "ollama", "oci").
    model_id:
        Model name within the provider (e.g. "gpt-4o", "qwen3:8b").
    api_base:
        Optional base URL override.
    api_key:
        Optional API key (prefer env vars in production).
    max_tokens:
        Maximum tokens for generation.
    frequency_penalty:
        Frequency penalty for generation.
    presence_penalty:
        Presence penalty for generation.
    """

    provider: str
    model_id: str
    api_base: Optional[str] = None
    api_key: SensitiveField[Optional[str]] = None
    max_tokens: Optional[int] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None


LITELLM_COMPONENT_TYPE = "LiteLlmConfig"
LITELLM_PLUGIN_TYPES: Dict[str, Type[BaseModel]] = {
    LITELLM_COMPONENT_TYPE: LiteLlmConfig,
}


def get_litellm_serialization_plugin():
    """Return the AgentSpec serialization plugin for LiteLlmConfig."""
    return PydanticComponentSerializationPlugin(LITELLM_PLUGIN_TYPES)


def get_litellm_deserialization_plugin():
    """Return the AgentSpec deserialization plugin for LiteLlmConfig."""
    return PydanticComponentDeserializationPlugin(LITELLM_PLUGIN_TYPES)
