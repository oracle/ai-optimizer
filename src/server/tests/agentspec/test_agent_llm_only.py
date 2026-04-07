"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the LLM-only agent definition, WayFlow loading, and chat session.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyagentspec.agent import Agent as AgentSpecAgent
from wayflowcore.agent import Agent
from wayflowcore.conversation import Conversation

from server.app.agentspec.adapters.litellm import LiteLlmConfig
from server.app.agentspec.agent_llm_only import build_llm_config, build_llm_only_agentspec
from server.app.core.schemas import ClientSettings
from server.app.models.schemas import ModelConfig
from server.app.runtime.wayflow.adapters.litellm import LiteLlmModel
from server.app.runtime.wayflow.llm_only import AgentChatSession, build_llm_only_agent
from server.tests.conftest import MOCK_API_KEY, MOCK_SERVER_URL, SAMPLE_CLIENT_SETTINGS_OBJ
from server.tests.runtime.wayflow.helpers import ollama_available


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


class TestBuildLlmOnlyAgent:
    """Unit tests for build_llm_only_agent (AgentSpec → WayFlow)."""

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_agent_basics(self, mock_fetch):
        """Verify the loaded WayFlow agent has the correct type, name, and no tools."""
        mock_fetch.return_value = "You are a test assistant."
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert isinstance(agent, Agent)
        assert agent.name == "LLM Only Agent"
        assert agent.tools == []

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_uses_mcp_prompt(self, mock_fetch):
        """Verify the WayFlow agent uses the prompt fetched from MCP."""
        mock_fetch.return_value = "You are an MCP-provided assistant."
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert agent.custom_instruction == "You are an MCP-provided assistant."
        mock_fetch.assert_awaited_once_with(MOCK_SERVER_URL, MOCK_API_KEY, "optimizer_basic-default")

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_fallback_on_mcp_failure(self, mock_fetch):
        """Verify the agent falls back to DEFAULT_INSTRUCTION when MCP fails."""
        mock_fetch.side_effect = ConnectionError("MCP server unreachable")
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert agent.custom_instruction is not None
        assert "helpful assistant" in agent.custom_instruction

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_llm_is_litellm_model(self, mock_fetch):
        """Verify the WayFlow agent uses a LiteLlmModel with the correct model string."""
        mock_fetch.return_value = "You are a test assistant."
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert isinstance(agent.llm, LiteLlmModel)
        assert agent.llm.litellm_model == "ollama_chat/qwen3:8b"


class TestAgentChatSession:
    """Unit tests for AgentChatSession."""

    def test_session_conversation_ids(self):
        """Verify auto-generated and custom conversation IDs work."""

        def _mock_agent():
            agent = MagicMock(spec=Agent)

            def _start_conv(**kwargs):
                conv = MagicMock(spec=Conversation)
                conv.conversation_id = kwargs.get("conversation_id") or "auto-id"
                return conv

            agent.start_conversation = _start_conv
            return agent

        session = AgentChatSession(_mock_agent())
        assert session.conversation_id == "auto-id"

        session2 = AgentChatSession(_mock_agent(), conversation_id="my-session")
        assert session2.conversation_id == "my-session"

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_chat_returns_empty_string_on_empty_response(self, mock_fetch):
        """If the LLM returns a message with no contents, chat() must not crash."""
        from wayflowcore.messagelist import Message, MessageList

        mock_fetch.return_value = "You are a test assistant."
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        session = AgentChatSession(agent)

        mock_conv = MagicMock(spec=Conversation)
        mock_conv.execute_async = AsyncMock()
        mock_conv.message_list = MessageList()
        mock_conv.status = None
        mock_conv.append_user_message = mock_conv.message_list.append_user_message
        # Simulate empty contents from the LLM
        mock_conv.get_last_message.return_value = Message(role="assistant")
        session._conversation = mock_conv

        result = await session.chat("hello", chat_history=True)
        assert result == ""

    async def test_chat_returns_error_on_failure(self):
        """Stateful chat returns error string when execute_async raises."""
        from server.tests.conftest import mock_agent_conv

        agent, _ = mock_agent_conv(execute_side_effect=RuntimeError("LLM down"))
        session = AgentChatSession(agent)
        result = await session.chat("hello", chat_history=True)
        assert result == "An error occurred while processing your request."

    async def test_chat_rolls_back_message_on_failure(self):
        """Failed stateful turn must not leave a stale user message in history."""
        from server.tests.conftest import mock_agent_conv

        agent, conv = mock_agent_conv(execute_side_effect=RuntimeError("LLM down"))
        session = AgentChatSession(agent)

        assert len(conv.message_list.get_messages()) == 0
        await session.chat("should be rolled back", chat_history=True)
        assert len(conv.message_list.get_messages()) == 0

    async def test_chat_rolls_back_all_messages_on_mid_execution_failure(self):
        """If execute_async adds messages before failing, all are rolled back."""
        from wayflowcore.messagelist import Message

        from server.tests.conftest import mock_agent_conv

        agent, conv = mock_agent_conv()

        async def _add_partial_then_fail():
            conv.message_list.append_message(Message(role="assistant", content="partial"))
            raise RuntimeError("tool call failed mid-execution")

        conv.execute_async = _add_partial_then_fail

        session = AgentChatSession(agent)

        # Pre-populate one successful turn
        conv.message_list.append_message(Message(role="user", content="prior question"))
        conv.message_list.append_message(Message(role="assistant", content="prior answer"))
        assert len(conv.message_list.get_messages()) == 2

        result = await session.chat("this will fail", chat_history=True)
        assert result == "An error occurred while processing your request."
        assert len(conv.message_list.get_messages()) == 2
        assert conv.message_list.get_messages()[-1].role == "assistant"

    async def test_stateless_chat_returns_error_on_failure(self):
        """Stateless chat returns error string when execute_async raises."""
        from server.tests.conftest import mock_agent_conv

        agent, _ = mock_agent_conv(execute_side_effect=RuntimeError("LLM down"))
        session = AgentChatSession(agent)
        result = await session.chat("hello", chat_history=False)
        assert result == "An error occurred while processing your request."


@pytest.mark.integration
@pytest.mark.skipif(not ollama_available(), reason="ollama not running at 127.0.0.1:11434")
class TestLlmOnlyAgentConversation:
    """Integration tests requiring a running ollama instance."""

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_single_turn(self, mock_fetch):
        """Verify a single-turn chat returns a correct response."""
        mock_fetch.return_value = "You are a helpful assistant."
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        session = AgentChatSession(agent)
        response = await session.chat("What is 2+2? Reply with just the number.")
        assert "4" in response

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_multi_turn_memory(self, mock_fetch):
        """Verify the agent remembers context across turns with chat history enabled."""
        mock_fetch.return_value = "You are a helpful assistant."
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        session = AgentChatSession(agent)

        await session.chat("My name is Alice.", chat_history=True)

        response = await session.chat("What is my name? Reply with just the name.", chat_history=True)
        assert "Alice" in response

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_chat_history_false_is_stateless(self, mock_fetch):
        """Verify chat_history=False produces a stateless turn with no prior context."""
        mock_fetch.return_value = "You are a helpful assistant."
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        session = AgentChatSession(agent)

        # Establish context with history on
        await session.chat("My name is Alice.", chat_history=True)
        r = await session.chat("What is my name? Reply with just the name.", chat_history=True)
        assert "Alice" in r

        # History off — should not know the name
        r = await session.chat(
            "What is my name? Reply with just the name, or say you don't know.",
            chat_history=False,
        )
        assert "Alice" not in r

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_chat_history_false_does_not_pollute_history(self, mock_fetch):
        """Verify a stateless turn does not alter the persistent conversation history."""
        mock_fetch.return_value = "You are a helpful assistant."
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        session = AgentChatSession(agent)

        # Establish context
        await session.chat("My name is Alice.", chat_history=True)

        # Stateless turn — should not affect persistent history
        await session.chat("My name is Bob.", chat_history=False)

        # History on — should still know Alice, not Bob
        r = await session.chat("What is my name? Reply with just the name.", chat_history=True)
        assert "Alice" in r

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_chat_history_toggle_full_scenario(self, mock_fetch):
        """Tests the exact scenario from requirements:
        me (true): Hi I'm Alice → bot knows
        me (true): What's my name → Alice
        me (false): What's my name → don't know
        me (true): What's my name → Alice
        """
        mock_fetch.return_value = "You are a helpful assistant."
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        session = AgentChatSession(agent)

        await session.chat("Hi I'm Alice", chat_history=True)

        r = await session.chat("What is my name? Reply with just the name.", chat_history=True)
        assert "Alice" in r

        r = await session.chat(
            "What is my name? Reply with just the name, or say you don't know.",
            chat_history=False,
        )
        assert "Alice" not in r

        r = await session.chat("What is my name? Reply with just the name.", chat_history=True)
        assert "Alice" in r

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_custom_instruction_affects_behavior(self, mock_fetch):
        """Verify a custom instruction influences the agent's response behavior."""
        mock_fetch.return_value = "You must always respond in exactly one word."
        agent = await build_llm_only_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        session = AgentChatSession(agent)
        response = await session.chat("Say hello.")
        assert len(response.split()) <= 3
