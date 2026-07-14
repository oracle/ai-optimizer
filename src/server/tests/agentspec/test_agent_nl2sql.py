"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the NL2SQL agent definition (AgentSpec layer only).
"""
# spell-checker: disable

from pyagentspec.agent import Agent as AgentSpecAgent
from pyagentspec.mcp import MCPToolBox, StreamableHTTPTransport

from server.app.agentspec.adapters.litellm import LiteLlmConfig
from server.app.agentspec.agent_nl2sql import build_nl2sql_agentspec
from server.tests.conftest import (
    MOCK_API_KEY,
    MOCK_SERVER_URL,
    MOCK_SYSTEM_PROMPT,
    SAMPLE_CLIENT_SETTINGS_OBJ,
)
from server.tests.constants import TEST_OLLAMA_MODEL_ID


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

    def test_toolbox_uses_unrestricted_discovery(self):
        """Verify the toolbox discovers every tool exposed by the MCP server."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        toolbox = agent.toolboxes[0]
        assert isinstance(toolbox, MCPToolBox)
        assert toolbox.tool_filter is None
        assert not toolbox.metadata

    def test_toolbox_transport(self):
        """Verify the MCPToolBox uses a StreamableHTTPTransport with the correct URL."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        toolbox = agent.toolboxes[0]
        assert isinstance(toolbox, MCPToolBox)
        assert isinstance(toolbox.client_transport, StreamableHTTPTransport)
        assert toolbox.client_transport.url == MOCK_SERVER_URL + "/"

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
        assert agent.llm_config.model_id == TEST_OLLAMA_MODEL_ID

    def test_human_in_the_loop_enabled(self):
        """Verify human_in_the_loop is enabled on the agent."""
        agent = build_nl2sql_agentspec(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)
        assert agent.human_in_the_loop is True
