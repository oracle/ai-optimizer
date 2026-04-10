"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

WayFlow runtime tests for the LLM-only agent: AgentSpec → WayFlow loading,
chat session, and live ollama integration.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from wayflowcore.agent import Agent
from wayflowcore.conversation import Conversation

from server.app.runtime.wayflow.adapters.litellm import LiteLlmModel
from server.app.runtime.wayflow.llm_only import AgentChatSession, build_llm_only_agent
from server.tests.conftest import MOCK_API_KEY, MOCK_SERVER_URL, SAMPLE_CLIENT_SETTINGS_OBJ
from server.tests.runtime.shared_helpers import ollama_available


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

        await session.chat("My name is Alice.", chat_history=True)
        r = await session.chat("What is my name? Reply with just the name.", chat_history=True)
        assert "Alice" in r

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

        await session.chat("My name is Alice.", chat_history=True)
        await session.chat("My name is Bob.", chat_history=False)

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
