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
from pyagentspec.serialization.pydanticdeserializationplugin import (
    PydanticComponentDeserializationPlugin,
)
from pyagentspec.serialization.pydanticserializationplugin import (
    PydanticComponentSerializationPlugin,
)
from pyagentspec.versioning import AgentSpecVersionEnum
from pydantic import BaseModel


class LiteLlmConfig(LlmConfig):
    """AgentSpec LLM configuration for LiteLLM-backed models.

    When serialized to YAML/JSON, produces a portable config with
    component_type "LiteLlmConfig".  At load time, a runtime-specific
    plugin converts this into the engine's native LLM instance.

    The connection fields (``provider``, ``model_id``, ``api_key``) are inherited
    from :class:`LlmConfig`.  ``provider`` is required to route the model; the
    loader enforces its presence (see runtime/langgraph/loader.py).

    Parameters
    ----------
    api_base:
        Optional base URL override.
    max_tokens:
        Maximum tokens for generation.
    frequency_penalty:
        Frequency penalty for generation.
    presence_penalty:
        Presence penalty for generation.
    """

    api_base: Optional[str] = None
    max_tokens: Optional[int] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None

    def _infer_min_agentspec_version_from_configuration(self) -> AgentSpecVersionEnum:
        # provider/model_id/api_key live on the base LlmConfig only from Agent
        # Spec 26.1.2 onward, so this component cannot be represented faithfully
        # by any earlier spec version.
        min_version = super()._infer_min_agentspec_version_from_configuration()
        return max(min_version, AgentSpecVersionEnum.v26_1_2)


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
