"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the LiteLlm WayFlow plugin (AgentSpec → wayflowcore bridge).
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

from pyagentspec.agent import Agent as AgentSpecAgent
from pyagentspec.llms import LlmGenerationConfig
from wayflowcore.agent import Agent as RuntimeAgent
from wayflowcore.agentspec.runtimeloader import AgentSpecLoader

from server.app.agentspec.adapters.litellm import (
    LiteLlmConfig,
    get_litellm_serialization_plugin,
)
from server.app.runtime.wayflow.adapters.litellm import LiteLlmModel, get_litellm_wayflow_plugin


class TestLiteLlmWayflowPlugin:
    """Tests for the WayFlow deserialization plugin."""

    def test_plugin_metadata(self):
        """Verify plugin name, version, and supported types."""
        plugin = get_litellm_wayflow_plugin()
        assert plugin.plugin_name == "litellm"
        assert plugin.plugin_version == "1.0.0"
        assert "LiteLlmConfig" in plugin.supported_component_types

    def test_load_component_produces_runtime_agent(self):
        """Verify loading an AgentSpec agent produces a WayFlow RuntimeAgent with LiteLlmModel."""
        config = LiteLlmConfig(
            id="ollama/qwen3:8b",
            name="ollama/qwen3:8b",
            provider="ollama",
            model_id="qwen3:8b",
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
        loader = AgentSpecLoader(plugins=[get_litellm_wayflow_plugin()])
        runtime_agent = loader.load_component(agent)

        assert isinstance(runtime_agent, RuntimeAgent)
        assert runtime_agent.name == "Test Agent"
        llm = runtime_agent.llm
        assert isinstance(llm, LiteLlmModel)
        assert llm.litellm_model == "ollama_chat/qwen3:8b"
        assert llm.provider == "ollama"

    def test_load_component_with_generation_config(self):
        """Verify generation config and penalty params survive the AgentSpec-to-WayFlow bridge."""
        gen = LlmGenerationConfig(temperature=0.3)
        config = LiteLlmConfig(
            id="openai/gpt-4o",
            name="openai/gpt-4o",
            provider="openai",
            model_id="gpt-4o",
            default_generation_parameters=gen,
            max_tokens=200,
            frequency_penalty=0.5,
            presence_penalty=0.3,
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
        loader = AgentSpecLoader(plugins=[get_litellm_wayflow_plugin()])
        runtime_agent = loader.load_component(agent)

        assert isinstance(runtime_agent, RuntimeAgent)
        llm = runtime_agent.llm
        assert isinstance(llm, LiteLlmModel)
        assert llm.generation_config is not None
        gen_dict = llm.generation_config.to_dict()
        assert gen_dict["max_tokens"] == 200
        assert gen_dict["temperature"] == 0.3
        assert gen_dict["frequency_penalty"] == 0.5
        assert gen_dict["presence_penalty"] == 0.3

    def test_stop_sequences_survive_bridge(self):
        """Stop sequences in AgentSpec generation config must reach the WayFlow runtime."""
        gen = LlmGenerationConfig.model_validate({"max_tokens": 100, "stop": ["\n\n", "END"]})
        config = LiteLlmConfig(
            id="openai/gpt-4o",
            name="openai/gpt-4o",
            provider="openai",
            model_id="gpt-4o",
            default_generation_parameters=gen,
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
        loader = AgentSpecLoader(plugins=[get_litellm_wayflow_plugin()])
        runtime_agent = loader.load_component(agent)

        assert isinstance(runtime_agent, RuntimeAgent)
        llm = runtime_agent.llm
        assert isinstance(llm, LiteLlmModel)
        assert llm.generation_config is not None
        gen_dict = llm.generation_config.to_dict()
        assert gen_dict["stop"] == ["\n\n", "END"]

    def test_full_roundtrip_serialize_load(self):
        """Full AgentSpec pipeline: define → serialize → deserialize → load → runtime."""
        from pyagentspec.serialization import AgentSpecSerializer

        gen = LlmGenerationConfig(max_tokens=50, temperature=0.1)
        config = LiteLlmConfig(
            id="ollama/qwen3:8b",
            name="ollama/qwen3:8b",
            provider="ollama",
            model_id="qwen3:8b",
            default_generation_parameters=gen,
        )
        agent = AgentSpecAgent(
            id="llm-only",
            name="LLM Only Agent",
            llm_config=config,
            system_prompt="You are helpful.",
            tools=[],
            toolboxes=[],
            human_in_the_loop=False,
        )

        ser_plugin = get_litellm_serialization_plugin()
        serializer = AgentSpecSerializer(plugins=[ser_plugin])
        json_str = serializer.to_json(agent)

        wayflow_plugin = get_litellm_wayflow_plugin()
        loader = AgentSpecLoader(plugins=[wayflow_plugin])
        runtime_agent = loader.load_json(json_str)

        assert isinstance(runtime_agent, RuntimeAgent)
        assert runtime_agent.name == "LLM Only Agent"
        llm = runtime_agent.llm
        assert isinstance(llm, LiteLlmModel)
        assert llm.litellm_model == "ollama_chat/qwen3:8b"
        assert llm.generation_config is not None
        gen_dict = llm.generation_config.to_dict()
        assert gen_dict["max_tokens"] == 50

    def test_oci_provider_injects_extra_kwargs(self):
        """OCI provider must resolve OCI profile and inject auth params into extra_kwargs."""
        fake_profile = MagicMock()
        fake_profile.genai_region = "us-chicago-1"
        fake_profile.genai_compartment_id = "ocid1.compartment.oc1..test"
        fake_profile.tenancy = "ocid1.tenancy.oc1..test"
        fake_profile.user = "ocid1.user.oc1..test"
        fake_profile.fingerprint = "aa:bb:cc"
        fake_profile.key_file = "/path/to/key.pem"

        config = LiteLlmConfig(
            id="oci/cohere.command-a-03-2025",
            name="oci/cohere.command-a-03-2025",
            provider="oci",
            model_id="cohere.command-a-03-2025",
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

        with (
            patch("server.app.runtime.wayflow.adapters.litellm.get_oci_profile", return_value=fake_profile),
            patch("server.app.models.litellm_utils.get_signer", return_value=None),
        ):
            loader = AgentSpecLoader(plugins=[get_litellm_wayflow_plugin()])
            runtime_agent = loader.load_component(agent)

        assert isinstance(runtime_agent, RuntimeAgent)
        llm = runtime_agent.llm
        assert isinstance(llm, LiteLlmModel)
        assert llm.extra_kwargs["oci_region"] == "us-chicago-1"
        assert llm.extra_kwargs["oci_compartment_id"] == "ocid1.compartment.oc1..test"
        assert llm.extra_kwargs["oci_tenancy"] == "ocid1.tenancy.oc1..test"
