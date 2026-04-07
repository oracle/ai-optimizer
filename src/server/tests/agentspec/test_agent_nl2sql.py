"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the NL2SQL agent definition, WayFlow loading, and session.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

from pyagentspec.agent import Agent as AgentSpecAgent
from pyagentspec.mcp import MCPToolBox, StreamableHTTPTransport
from wayflowcore.agent import Agent as RuntimeAgent

from server.app.agentspec.adapters.litellm import LiteLlmConfig
from server.app.agentspec.agent_nl2sql import build_nl2sql_agentspec
from server.app.runtime.wayflow.adapters.litellm import LiteLlmModel
from server.app.runtime.wayflow.nl2sql import NL2SQLAgentSession, build_nl2sql_agent
from server.tests.conftest import (
    MOCK_API_KEY,
    MOCK_SERVER_URL,
    MOCK_SYSTEM_PROMPT,
    SAMPLE_CLIENT_SETTINGS_OBJ,
    mock_agent_conv,
)


class TestBuildNl2sqlAgentspec:
    """Unit tests for build_nl2sql_agentspec (AgentSpec layer)."""

    def test_returns_agentspec_agent(self):
        """Verify the function returns an AgentSpec Agent instance."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        assert isinstance(agent, AgentSpecAgent)

    def test_agent_id_and_name(self):
        """Verify the agent has the correct id and name."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        assert agent.id == "nl2sql-agent"
        assert agent.name == "NL2SQL Agent"

    def test_system_prompt_embedded(self):
        """Verify the system prompt is set on the agent."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        assert agent.system_prompt == MOCK_SYSTEM_PROMPT

    def test_no_hard_coded_tools(self):
        """Verify the agent has no hard-coded tools — all come from MCPToolBox."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        assert agent.tools == []

    def test_has_mcp_toolbox(self):
        """Verify the agent has exactly one MCPToolBox for dynamic tool discovery."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        assert len(agent.toolboxes) == 1
        assert isinstance(agent.toolboxes[0], MCPToolBox)

    def test_toolbox_transport(self):
        """Verify the MCPToolBox uses a StreamableHTTPTransport with the correct URL."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        toolbox = agent.toolboxes[0]
        assert isinstance(toolbox, MCPToolBox)
        assert isinstance(toolbox.client_transport, StreamableHTTPTransport)
        assert toolbox.client_transport.url == MOCK_SERVER_URL

    def test_toolbox_transport_api_key(self):
        """Verify the MCPToolBox transport has the API key in sensitive_headers."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        toolbox = agent.toolboxes[0]
        assert isinstance(toolbox, MCPToolBox)
        transport = toolbox.client_transport
        assert isinstance(transport, StreamableHTTPTransport)
        assert transport.sensitive_headers == {"X-API-Key": MOCK_API_KEY}

    def test_llm_config_is_litellm(self):
        """Verify the agent's LLM config is a LiteLlmConfig with correct model."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        assert isinstance(agent.llm_config, LiteLlmConfig)
        assert agent.llm_config.provider == "ollama_chat"
        assert agent.llm_config.model_id == "qwen3:8b"

    def test_human_in_the_loop_enabled(self):
        """Verify human_in_the_loop is enabled on the agent."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        assert agent.human_in_the_loop is True


class TestBuildNl2sqlAgent:
    """Unit tests for build_nl2sql_agent (AgentSpec → WayFlow)."""

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_returns_runtime_agent(self, mock_fetch):
        """Verify the loaded WayFlow agent is a RuntimeAgent."""
        mock_fetch.return_value = MOCK_SYSTEM_PROMPT
        agent = await build_nl2sql_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert isinstance(agent, RuntimeAgent)

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_agent_name(self, mock_fetch):
        """Verify the WayFlow agent has the correct name."""
        mock_fetch.return_value = MOCK_SYSTEM_PROMPT
        agent = await build_nl2sql_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert agent.name == "NL2SQL Agent"

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_uses_mcp_prompt(self, mock_fetch):
        """Verify the WayFlow agent uses the prompt fetched from MCP."""
        mock_fetch.return_value = "Custom NL2SQL prompt."
        agent = await build_nl2sql_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert agent.custom_instruction == "Custom NL2SQL prompt."
        mock_fetch.assert_awaited_once_with(MOCK_SERVER_URL, MOCK_API_KEY, "optimizer_nl2sql-tools-default")

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_fallback_on_mcp_failure(self, mock_fetch):
        """Verify the agent falls back to DEFAULT_NL2SQL_INSTRUCTION when MCP fails."""
        mock_fetch.side_effect = ConnectionError("MCP server unreachable")
        agent = await build_nl2sql_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert agent.custom_instruction is not None
        assert "database assistant" in agent.custom_instruction

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_llm_is_litellm_model(self, mock_fetch):
        """Verify the WayFlow agent uses a LiteLlmModel."""
        mock_fetch.return_value = MOCK_SYSTEM_PROMPT
        agent = await build_nl2sql_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert isinstance(agent.llm, LiteLlmModel)
        assert agent.llm.litellm_model == "ollama_chat/qwen3:8b"


class TestNL2SQLAgentSession:
    """Unit tests for NL2SQLAgentSession."""

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_connection_context_injected(self, mock_fetch):
        """Verify the session injects connection_name, model, and thread_id into the system prompt."""
        mock_fetch.return_value = "Base prompt."
        agent = await build_nl2sql_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        _session = NL2SQLAgentSession(agent, SAMPLE_CLIENT_SETTINGS_OBJ, thread_id="client-123")
        instruction = agent.custom_instruction
        assert instruction is not None
        assert "model: ollama/qwen3:8b" in instruction
        assert "thread_id: client-123" in instruction
        assert "connection_name: CORE" in instruction

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_base_prompt_preserved(self, mock_fetch):
        """Verify the original prompt text is preserved before the injected context."""
        mock_fetch.return_value = "Base prompt."
        agent = await build_nl2sql_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        _session = NL2SQLAgentSession(agent, SAMPLE_CLIENT_SETTINGS_OBJ)
        assert agent.custom_instruction is not None
        assert agent.custom_instruction.startswith("Base prompt.")

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_no_connection_name_when_empty(self, mock_fetch):
        """Verify connection_name is omitted when database alias is empty."""
        mock_fetch.return_value = "Base prompt."
        from server.app.core.schemas import DatabaseSettings

        settings_no_db = SAMPLE_CLIENT_SETTINGS_OBJ.model_copy(update={"database": DatabaseSettings(alias="")})
        agent = await build_nl2sql_agent(settings_no_db, MOCK_SERVER_URL, MOCK_API_KEY)
        _session = NL2SQLAgentSession(agent, settings_no_db)
        assert agent.custom_instruction is not None
        assert "connection_name" not in agent.custom_instruction

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_no_thread_id_when_empty(self, mock_fetch):
        """Verify thread_id is omitted when not provided."""
        mock_fetch.return_value = "Base prompt."
        agent = await build_nl2sql_agent(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        _session = NL2SQLAgentSession(agent, SAMPLE_CLIENT_SETTINGS_OBJ)
        assert agent.custom_instruction is not None
        assert "thread_id" not in agent.custom_instruction

    async def test_chat_delegates_to_parent(self):
        """Verify chat() delegates to the AgentChatSession parent."""
        agent, _conv = mock_agent_conv(content="42 rows found")
        agent.custom_instruction = "Base prompt."
        agent._update_internal_state = MagicMock()
        session = NL2SQLAgentSession(agent, SAMPLE_CLIENT_SETTINGS_OBJ)
        result = await session.chat("list connections", chat_history=True)
        assert result == "42 rows found"

    async def test_chat_returns_error_on_failure(self):
        """Verify chat returns error string when execute_async raises."""
        agent, _ = mock_agent_conv(execute_side_effect=RuntimeError("MCP down"))
        agent.custom_instruction = "Base prompt."
        agent._update_internal_state = MagicMock()
        session = NL2SQLAgentSession(agent, SAMPLE_CLIENT_SETTINGS_OBJ)
        result = await session.chat("hello", chat_history=True)
        assert result == "An error occurred while processing your request."
