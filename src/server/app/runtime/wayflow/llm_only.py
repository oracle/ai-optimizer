"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

WayFlow runtime loader and session for the LLM-Only agent.

Takes an AgentSpec definition and loads it into WayFlow for execution.
"""
# spell-checker: ignore agentspec litellm pyagentspec runtimeloader spanprocessor wayflow wayflowcore

import logging
from typing import Optional, Sequence, cast

from wayflowcore.agent import Agent as RuntimeAgent
from wayflowcore.agentspec.runtimeloader import AgentSpecLoader
from wayflowcore.tracing.spanprocessor import SpanProcessor

from server.app.agentspec.agent_llm_only import DEFAULT_INSTRUCTION, build_llm_only_agentspec
from server.app.core.schemas import ClientSettings
from server.app.runtime.common import fetch_prompt_with_fallback
from server.app.runtime.wayflow.adapters.litellm import get_litellm_wayflow_plugin
from server.app.runtime.wayflow.tracing import maybe_trace

LOGGER = logging.getLogger(__name__)

PROMPT_NAME = "optimizer_basic-default"


async def build_llm_only_agent(
    client_settings: ClientSettings,
    server_url: str,
    api_key: str,
) -> RuntimeAgent:
    """Build a WayFlow Agent for LLM-only conversation (no tools).

    Fetches the system prompt from the MCP server, then defines the agent
    via pyagentspec and loads it into WayFlow.

    Parameters
    ----------
    client_settings:
        ClientSettings object containing ll_model config.
    server_url:
        Full URL to the MCP endpoint (e.g. "http://127.0.0.1:8001/mcp").
    api_key:
        API key for the MCP server.

    Returns
    -------
    RuntimeAgent
        A WayFlow Agent ready to be executed.
    """
    prompt = await fetch_prompt_with_fallback(server_url, api_key, PROMPT_NAME, DEFAULT_INSTRUCTION)

    agentspec_agent = build_llm_only_agentspec(client_settings, prompt)

    loader = AgentSpecLoader(plugins=[get_litellm_wayflow_plugin()])
    return cast(RuntimeAgent, loader.load_component(agentspec_agent))


class AgentChatSession:
    """Manages conversation state for an Agent, respecting chat_history toggle.

    When chat_history is True, messages are added to and use persistent history.
    When chat_history is False, the turn is stateless — it doesn't see prior
    history and isn't added to it.

    Parameters
    ----------
    agent:
        A WayFlow Agent instance.
    conversation_id:
        Optional conversation ID for the persistent conversation.
    """

    def __init__(
        self,
        agent: RuntimeAgent,
        conversation_id: Optional[str] = None,
        span_processors: Optional[Sequence[SpanProcessor]] = None,
    ):
        self.agent = agent
        self._conversation = agent.start_conversation(conversation_id=conversation_id)
        self._span_processors = span_processors

    @property
    def conversation(self):
        """The underlying wayflowcore Conversation object."""
        return self._conversation

    @conversation.setter
    def conversation(self, value) -> None:
        self._conversation = value

    @property
    def conversation_id(self) -> str:
        """Return the persistent conversation ID."""
        return self._conversation.conversation_id

    async def chat(self, message: str, chat_history: bool = True) -> str:
        """Send a message and get a response.

        Parameters
        ----------
        message:
            User message text.
        chat_history:
            If True, this turn uses and contributes to persistent history.
            If False, this turn is stateless — no history in, no history out.

        Returns
        -------
        str
            The agent's response text.
        """
        if chat_history:
            msg_count = len(self._conversation.message_list.messages)
            self._conversation.append_user_message(message)
            try:
                with maybe_trace("agent_chat", self._span_processors):
                    await self._conversation.execute_async()
            except Exception:
                # Bypasses MessageList's append-only contract to remove the
                # partial turn; leaving corrupt messages is worse.
                del self._conversation.message_list.messages[msg_count:]
                LOGGER.exception("Agent chat failed for message: %s", message)
                return "An error occurred while processing your request."
            last = self._conversation.get_last_message()
            return (last.content or "") if last else ""

        # Stateless turn: fresh conversation, no history impact
        temp_conv = self.agent.start_conversation()
        temp_conv.append_user_message(message)
        try:
            with maybe_trace("agent_chat", self._span_processors):
                await temp_conv.execute_async()
        except Exception:
            LOGGER.exception("Agent chat failed for message: %s", message)
            return "An error occurred while processing your request."
        last = temp_conv.get_last_message()
        return (last.content or "") if last else ""
