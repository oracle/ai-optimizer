"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for LiteLlmAgentSpecLoader — ensures load_component routes through
our _llm_convert_to_langgraph override so LiteLlmConfig is handled.
"""
# spell-checker: ignore agentspec litellm langgraph pyagentspec afunc genai ocid ollama

import contextlib
from unittest.mock import MagicMock, patch

from pyagentspec.agent import Agent as AgentSpecAgent

from server.app.agentspec.adapters.litellm import LiteLlmConfig
from server.app.runtime.langgraph.adapters.litellm import ChatLiteLLMBridge
from server.app.runtime.langgraph.loader import LiteLlmAgentSpecLoader


class TestLiteLlmAgentSpecLoader:
    """Verify LiteLlmAgentSpecLoader.load_component uses the LiteLlm-aware converter."""

    def _make_agent(self, provider="ollama", model_id="qwen3:8b", **kwargs):
        config = LiteLlmConfig(
            id=f"{provider}/{model_id}",
            name=f"{provider}/{model_id}",
            provider=provider,
            model_id=model_id,
            **kwargs,
        )
        return AgentSpecAgent(
            id="test-agent",
            name="Test Agent",
            llm_config=config,
            system_prompt="You are helpful.",
            tools=[],
            toolboxes=[],
            human_in_the_loop=False,
        )

    def test_load_component_uses_litellm_bridge(self):
        """load_component must produce a graph whose LLM is ChatLiteLLMBridge, not raise NotImplementedError."""
        loader = LiteLlmAgentSpecLoader()
        agent = self._make_agent()
        graph = loader.load_component(agent)
        bridge = _find_litellm_bridge(graph)
        assert bridge is not None, (
            "Expected ChatLiteLLMBridge in the compiled graph — "
            "load_component may be using the base converter instead of the LiteLlm-aware one"
        )
        assert bridge.model == "ollama_chat/qwen3:8b"

    def test_load_component_with_penalty_params(self):
        """Verify frequency/presence penalty survive the loader pipeline."""
        loader = LiteLlmAgentSpecLoader()
        agent = self._make_agent(
            provider="openai",
            model_id="gpt-4o",
            max_tokens=200,
            frequency_penalty=0.5,
            presence_penalty=0.3,
        )
        graph = loader.load_component(agent)
        bridge = _find_litellm_bridge(graph)
        assert bridge is not None
        assert bridge.model == "openai/gpt-4o"
        assert bridge.max_tokens == 200
        assert bridge.frequency_penalty == 0.5
        assert bridge.presence_penalty == 0.3

    def test_oci_provider_injects_extra_params(self):
        """OCI provider must resolve OCI profile and inject auth params."""
        fake_profile = MagicMock()
        fake_profile.genai_region = "us-chicago-1"
        fake_profile.genai_compartment_id = "ocid1.compartment.oc1..test"
        fake_profile.tenancy = "ocid1.tenancy.oc1..test"
        fake_profile.user = "ocid1.user.oc1..test"
        fake_profile.fingerprint = "aa:bb:cc"
        fake_profile.key_file = "/path/to/key.pem"

        with (
            patch("server.app.runtime.langgraph.loader.get_oci_profile", return_value=fake_profile),
            patch("server.app.models.litellm_utils.get_signer", return_value=None),
        ):
            loader = LiteLlmAgentSpecLoader()
            agent = self._make_agent(provider="oci", model_id="cohere.command-a-03-2025")
            graph = loader.load_component(agent)

        bridge = _find_litellm_bridge(graph)
        assert bridge is not None
        assert bridge.model == "oci/cohere.command-a-03-2025"
        assert bridge.extra_params["oci_region"] == "us-chicago-1"
        assert bridge.extra_params["oci_compartment_id"] == "ocid1.compartment.oc1..test"
        assert bridge.extra_params["oci_tenancy"] == "ocid1.tenancy.oc1..test"

    def test_oci_provider_with_signer(self):
        """OCI with signer-based auth passes oci_signer instead of API key fields."""
        fake_profile = MagicMock()
        fake_profile.genai_region = "us-chicago-1"
        fake_profile.genai_compartment_id = "ocid1.compartment.oc1..test"
        fake_signer = MagicMock()

        with (
            patch("server.app.runtime.langgraph.loader.get_oci_profile", return_value=fake_profile),
            patch("server.app.models.litellm_utils.get_signer", return_value=fake_signer),
        ):
            loader = LiteLlmAgentSpecLoader()
            agent = self._make_agent(provider="oci", model_id="cohere.command-a-03-2025")
            graph = loader.load_component(agent)

        bridge = _find_litellm_bridge(graph)
        assert bridge is not None
        assert bridge.extra_params["oci_signer"] is fake_signer
        assert "oci_tenancy" not in bridge.extra_params

    def test_non_oci_provider_has_empty_extra_params(self):
        """Non-OCI providers should have empty extra_params."""
        loader = LiteLlmAgentSpecLoader()
        agent = self._make_agent(provider="ollama", model_id="qwen3:8b")
        graph = loader.load_component(agent)
        bridge = _find_litellm_bridge(graph)
        assert bridge is not None
        assert bridge.extra_params == {}


class TestUnwrapToolContentBlocks:
    """Tests for _unwrap_tool_content_blocks patching."""

    def test_unwraps_single_text_block(self):
        """Content blocks with a single text entry are unwrapped to raw text."""
        import asyncio

        from server.app.runtime.langgraph.loader import _unwrap_tool_content_blocks

        tool = MagicMock()
        content_blocks = [{"type": "text", "text": '{"documents": []}', "id": "lc_123"}]

        async def fake_coroutine(**_kwargs):
            return content_blocks, None

        tool.coroutine = fake_coroutine
        _unwrap_tool_content_blocks(tool)

        result = asyncio.run(tool.coroutine())
        assert result == ('{"documents": []}', None)

    def test_passthrough_non_content_blocks(self):
        """Non-content-block results pass through unchanged."""
        import asyncio

        from server.app.runtime.langgraph.loader import _unwrap_tool_content_blocks

        tool = MagicMock()
        plain_result = ({"key": "value"}, None)

        async def fake_coroutine(**_kwargs):
            return plain_result

        tool.coroutine = fake_coroutine
        _unwrap_tool_content_blocks(tool)

        result = asyncio.run(tool.coroutine())
        assert result == plain_result

    def test_passthrough_non_tuple(self):
        """A non-tuple result passes through unchanged."""
        import asyncio

        from server.app.runtime.langgraph.loader import _unwrap_tool_content_blocks

        tool = MagicMock()

        async def fake_coroutine(**_kwargs):
            return "plain string"

        tool.coroutine = fake_coroutine
        _unwrap_tool_content_blocks(tool)

        result = asyncio.run(tool.coroutine())
        assert result == "plain string"


def _find_litellm_bridge(graph):
    """Walk a compiled LangGraph to find a ChatLiteLLMBridge instance.

    The bridge lives inside closures of the ``call_model`` function that
    LangGraph's ``create_react_agent`` generates, so we need to inspect
    function closures in addition to object attributes.
    """
    visited = set()
    queue = list(graph.nodes.values())
    while queue:
        obj = queue.pop()
        obj_id = id(obj)
        if obj_id in visited:
            continue
        visited.add(obj_id)
        if isinstance(obj, ChatLiteLLMBridge):
            return obj
        # Walk common LangGraph/LangChain wrapper attributes
        for attr in ("bound", "first", "middle", "last", "default", "func", "afunc"):
            child = getattr(obj, attr, None)
            if child is None:
                continue
            if isinstance(child, (list, tuple)):
                queue.extend(child)
            else:
                queue.append(child)
        # Walk function closures (create_react_agent stores the model in a closure)
        if callable(obj) and hasattr(obj, "__closure__") and obj.__closure__:
            for cell in obj.__closure__:
                with contextlib.suppress(ValueError):
                    queue.append(cell.cell_contents)
    return None
