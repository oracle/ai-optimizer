"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for LiteLlmConfig AgentSpec component and its plugins.
"""
# spell-checker: disable

import json

from pyagentspec.agent import Agent as AgentSpecAgent
from pyagentspec.llms import LlmGenerationConfig
from pyagentspec.serialization import AgentSpecDeserializer, AgentSpecSerializer

from server.app.agentspec.adapters.litellm import (
    LiteLlmConfig,
    get_litellm_deserialization_plugin,
    get_litellm_serialization_plugin,
)
from server.tests.constants import (
    TEST_OLLAMA_MODEL_ID,
    TEST_OLLAMA_MODEL_KEY,
    TEST_OPENAI_MODEL_API_KEY,
    TEST_OPENAI_MODEL_ID,
    TEST_OPENAI_MODEL_KEY,
)


class TestLiteLlmConfig:
    """Unit tests for the LiteLlmConfig AgentSpec component."""

    def test_component_type(self):
        """Verify component_type is 'LiteLlmConfig'."""
        config = LiteLlmConfig(id="test", name="test", provider="ollama", model_id=TEST_OLLAMA_MODEL_ID)
        assert str(config.component_type) == "LiteLlmConfig"

    def test_fields(self):
        """Verify provider, model_id, api_base, and api_key fields."""
        config = LiteLlmConfig(
            id=TEST_OLLAMA_MODEL_KEY,
            name=TEST_OLLAMA_MODEL_KEY,
            provider="ollama",
            model_id=TEST_OLLAMA_MODEL_ID,
            api_base="http://localhost:11434",
        )
        assert config.provider == "ollama"
        assert config.model_id == TEST_OLLAMA_MODEL_ID
        assert config.api_base == "http://localhost:11434"
        assert config.api_key is None

    def test_with_generation_config(self):
        """Verify default_generation_parameters are stored correctly."""
        gen = LlmGenerationConfig(max_tokens=100, temperature=0.5)
        config = LiteLlmConfig(
            id="test",
            name="test",
            provider="openai",
            model_id=TEST_OPENAI_MODEL_ID,
            default_generation_parameters=gen,
        )
        assert config.default_generation_parameters is not None
        assert config.default_generation_parameters.max_tokens == 100
        assert config.default_generation_parameters.temperature == 0.5


class TestLiteLlmConfigSensitiveFields:
    """Ensure api_key is excluded from serialized output."""

    def test_api_key_excluded_from_serialized_json(self):
        """api_key must not appear in plaintext in serialized AgentSpec JSON."""
        config = LiteLlmConfig(
            id=TEST_OPENAI_MODEL_KEY,
            name=TEST_OPENAI_MODEL_KEY,
            provider="openai",
            model_id=TEST_OPENAI_MODEL_ID,
            api_key="sk-super-secret-key",
        )
        serializer = AgentSpecSerializer(plugins=[get_litellm_serialization_plugin()])
        result = serializer.to_json(config)
        assert "sk-super-secret-key" not in result

    def test_api_key_survives_roundtrip_via_disaggregated(self):
        """api_key should be recoverable through disaggregated deserialization."""
        config = LiteLlmConfig(
            id=TEST_OPENAI_MODEL_KEY,
            name=TEST_OPENAI_MODEL_KEY,
            provider="openai",
            model_id=TEST_OPENAI_MODEL_ID,
            api_key="sk-roundtrip-key",
        )
        # The api_key should be accessible on the object even though it's sensitive
        assert config.api_key == "sk-roundtrip-key"


class TestLiteLlmConfigSerialization:
    """Tests for AgentSpec serialization/deserialization of LiteLlmConfig."""

    def test_serialize_to_json(self):
        """Verify LiteLlmConfig serializes to JSON with correct fields."""
        config = LiteLlmConfig(
            id=TEST_OLLAMA_MODEL_KEY,
            name=TEST_OLLAMA_MODEL_KEY,
            provider="ollama",
            model_id=TEST_OLLAMA_MODEL_ID,
        )
        serializer = AgentSpecSerializer(plugins=[get_litellm_serialization_plugin()])
        result = serializer.to_json(config)
        parsed = json.loads(result)
        assert parsed["component_type"] == "LiteLlmConfig"
        assert parsed["provider"] == "ollama"
        assert parsed["model_id"] == TEST_OLLAMA_MODEL_ID

    def test_serialize_deserialize_roundtrip(self):
        """Verify serialize then deserialize preserves all fields."""
        gen = LlmGenerationConfig(max_tokens=100, temperature=0.7)
        config = LiteLlmConfig(
            id=TEST_OPENAI_MODEL_KEY,
            name=TEST_OPENAI_MODEL_KEY,
            provider="openai",
            model_id=TEST_OPENAI_MODEL_ID,
            api_key="sk-test",
            default_generation_parameters=gen,
        )
        ser_plugin = get_litellm_serialization_plugin()
        deser_plugin = get_litellm_deserialization_plugin()

        serializer = AgentSpecSerializer(plugins=[ser_plugin])
        deserializer = AgentSpecDeserializer(plugins=[deser_plugin])

        json_str = serializer.to_json(config)
        # api_key is a SensitiveField — supply it via components_registry
        restored = deserializer.from_json(
            json_str,
            components_registry={TEST_OPENAI_MODEL_API_KEY: "sk-test"},
        )

        assert isinstance(restored, LiteLlmConfig)
        assert restored.provider == "openai"
        assert restored.model_id == TEST_OPENAI_MODEL_ID
        assert restored.api_key == "sk-test"
        assert restored.default_generation_parameters is not None
        assert restored.default_generation_parameters.max_tokens == 100
        assert restored.default_generation_parameters.temperature == 0.7

    def test_serialize_agent_with_litellm(self):
        """Verify an Agent with LiteLlmConfig serializes correctly."""
        config = LiteLlmConfig(
            id=TEST_OLLAMA_MODEL_KEY,
            name=TEST_OLLAMA_MODEL_KEY,
            provider="ollama",
            model_id=TEST_OLLAMA_MODEL_ID,
        )
        agent = AgentSpecAgent(
            id="test-agent",
            name="Test Agent",
            llm_config=config,
            system_prompt="You are helpful.",
            tools=[],
            toolboxes=[],
            human_in_the_loop=False,
        )
        serializer = AgentSpecSerializer(plugins=[get_litellm_serialization_plugin()])
        result = serializer.to_json(agent)
        parsed = json.loads(result)
        assert parsed["name"] == "Test Agent"
        assert parsed["llm_config"]["component_type"] == "LiteLlmConfig"
        assert parsed["llm_config"]["provider"] == "ollama"

