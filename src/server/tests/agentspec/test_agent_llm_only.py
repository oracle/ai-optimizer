"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the LLM-only agent definition (AgentSpec layer only).
"""
# spell-checker: disable

import pytest
from pyagentspec.agent import Agent as AgentSpecAgent

from server.app.agentspec.adapters.litellm import LiteLlmConfig
from server.app.agentspec.agent_llm_only import build_llm_config, build_llm_only_agentspec
from server.app.core.schemas import ClientSettings
from server.app.models.schemas import ModelConfig
from server.tests.conftest import SAMPLE_CLIENT_SETTINGS_OBJ


class TestBuildLlmConfig:
    """Unit tests for build_llm_config (AgentSpec layer)."""

    def test_creates_litellm_config(self):
        """Verify build_llm_config returns a LiteLlmConfig instance."""
        llm = build_llm_config(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert isinstance(llm, LiteLlmConfig)

    def test_provider_and_model_id(self):
        """Verify provider is normalized and model_id is set from client settings."""
        llm = build_llm_config(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert llm.provider == "ollama_chat"
        assert llm.model_id == "qwen3:8b"

    def test_generation_config_set(self):
        """Verify generation parameters like temperature are populated."""
        llm = build_llm_config(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert llm.default_generation_parameters is not None
        assert llm.default_generation_parameters.temperature == 0.1

    def test_max_tokens_on_config(self):
        """Verify max_tokens is carried from client settings."""
        llm = build_llm_config(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert llm.max_tokens == 512

    def test_penalty_params_carried(self):
        """Verify frequency and presence penalties are set on the config."""
        settings = ClientSettings.model_validate(
            {
                "ll_model": {
                    "provider": "openai",
                    "id": "gpt-4o",
                    "frequency_penalty": 0.5,
                    "presence_penalty": 0.3,
                }
            }
        )
        llm = build_llm_config(settings)
        assert llm.frequency_penalty == 0.5
        assert llm.presence_penalty == 0.3

    def test_name_format(self):
        """Verify config name follows the normalized provider/model_id format."""
        llm = build_llm_config(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert llm.name == "ollama_chat/qwen3:8b"

    def test_default_generation_config_when_not_specified(self):
        """Verify generation parameters use defaults when not explicitly provided."""
        settings = ClientSettings.model_validate(
            {
                "ll_model": {
                    "provider": "openai",
                    "id": "gpt-4o",
                }
            }
        )
        llm = build_llm_config(settings)
        # ClientSettings fills defaults (temperature=0.5, top_p=1.0)
        assert llm.default_generation_parameters is not None
        assert llm.default_generation_parameters.temperature == 0.5
        assert llm.default_generation_parameters.top_p == 1.0

    def test_component_type(self):
        """Verify the component type is LiteLlmConfig."""
        llm = build_llm_config(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert str(llm.component_type) == "LiteLlmConfig"

    def test_api_key_from_model_config(self):
        """Verify api_key is resolved from settings.model_configs, not ll_model."""
        from server.app.core.settings import settings as app_settings

        original = app_settings.model_configs[:]
        try:
            app_settings.model_configs = [
                ModelConfig(provider="openai", id="gpt-4o", type="ll", api_key="sk-test-key-123"),
            ]
            cs = ClientSettings.model_validate({"ll_model": {"provider": "openai", "id": "gpt-4o"}})
            llm = build_llm_config(cs)
            assert llm.api_key == "sk-test-key-123"
        finally:
            app_settings.model_configs = original

    def test_api_base_from_model_config(self):
        """Verify api_base is resolved from settings.model_configs, not ll_model."""
        from server.app.core.settings import settings as app_settings

        original = app_settings.model_configs[:]
        try:
            app_settings.model_configs = [
                ModelConfig(provider="ollama", id="qwen3:8b", type="ll", api_base="http://localhost:11434"),
            ]
            cs = ClientSettings.model_validate({"ll_model": {"provider": "ollama", "id": "qwen3:8b"}})
            llm = build_llm_config(cs)
            assert llm.api_base == "http://localhost:11434"
        finally:
            app_settings.model_configs = original

    def test_raises_when_no_model_config(self):
        """Verify build_llm_config raises ValueError when no matching ModelConfig exists."""
        from server.app.core.settings import settings as app_settings

        original = app_settings.model_configs[:]
        try:
            app_settings.model_configs = []
            cs = ClientSettings.model_validate({"ll_model": {"provider": "ollama", "id": "qwen3:8b"}})
            with pytest.raises(ValueError, match="not found"):
                build_llm_config(cs)
        finally:
            app_settings.model_configs = original


class TestBuildLlmOnlyAgentspec:
    """Unit tests for build_llm_only_agentspec (AgentSpec layer)."""

    def test_returns_agentspec_agent(self):
        """Verify the function returns an AgentSpec Agent instance."""
        agent = build_llm_only_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert isinstance(agent, AgentSpecAgent)

    def test_agent_name(self):
        """Verify the agentspec agent is named 'LLM Only Agent'."""
        agent = build_llm_only_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert agent.name == "LLM Only Agent"

    def test_no_tools(self):
        """Verify the agentspec agent has no tools attached."""
        agent = build_llm_only_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert agent.tools == []

    def test_default_instruction(self):
        """Verify the default system prompt mentions helpful assistant."""
        agent = build_llm_only_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert "helpful assistant" in agent.system_prompt

    def test_custom_instruction(self):
        """Verify a custom instruction overrides the default system prompt."""
        agent = build_llm_only_agentspec(
            SAMPLE_CLIENT_SETTINGS_OBJ,
            custom_instruction="You are a pirate.",
        )
        assert agent.system_prompt == "You are a pirate."

    def test_llm_config_is_litellm(self):
        """Verify the agent's LLM config is a LiteLlmConfig with correct model."""
        agent = build_llm_only_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert isinstance(agent.llm_config, LiteLlmConfig)
        assert agent.llm_config.provider == "ollama_chat"
        assert agent.llm_config.model_id == "qwen3:8b"

    def test_human_in_the_loop_enabled(self):
        """Verify human_in_the_loop is enabled on the agent."""
        agent = build_llm_only_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ)
        assert agent.human_in_the_loop is True

