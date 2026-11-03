"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for LiteLlmAgentSpecLoader — ensures load_component routes through
our _llm_convert_to_langgraph override so LiteLlmConfig is handled.
"""
# spell-checker: disable

import contextlib
from typing import Any, cast
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from fastmcp import FastMCP
from fastmcp.client.transports import SSETransport as FastMCPSSETransport
from fastmcp.client.transports import StdioTransport as FastMCPStdioTransport
from fastmcp.client.transports import StreamableHttpTransport
from pyagentspec.adapters.langgraph.tracing import AgentSpecToolCallbackHandler
from pyagentspec.agent import Agent as AgentSpecAgent
from pyagentspec.auth import OAuthClientConfig, OAuthConfig
from pyagentspec.mcp import MCPTool, MCPToolBox, MCPToolSpec
from pyagentspec.mcp.clienttransport import (
    ClientTransport,
    SessionParameters,
    StreamableHTTPmTLSTransport,
    StreamableHTTPTransport,
)
from pyagentspec.mcp.clienttransport import SSETransport as AgentSpecSSETransport
from pyagentspec.mcp.clienttransport import StdioTransport as AgentSpecStdioTransport
from pyagentspec.serialization import AgentSpecSerializer

from server.app.agentspec.adapters.litellm import LiteLlmConfig
from server.app.agentspec.agent_nl2sql import NL2SQL_SQLCL_TOOLS, build_nl2sql_agentspec
from server.app.agentspec.flow_vecsearch import build_vecsearch_flow
from server.app.runtime.langgraph import loader as loader_module
from server.app.runtime.langgraph.adapters.litellm import OracleChatLiteLLM
from server.app.runtime.langgraph.loader import (
    LiteLlmAgentSpecLoader,
    _agentspec_transport_to_fastmcp,
    _mcp_httpx2_client_factory,
)
from server.tests.conftest import MOCK_API_KEY, MOCK_SERVER_URL, MOCK_SYSTEM_PROMPT, SAMPLE_CLIENT_SETTINGS_OBJ
from server.tests.constants import (
    TEST_OLLAMA_CHAT_KEY,
    TEST_OLLAMA_MODEL_ID,
    TEST_OPENAI_MODEL_ID,
    TEST_OPENAI_MODEL_KEY,
)


class TestLiteLlmAgentSpecLoader:
    """Verify LiteLlmAgentSpecLoader.load_component uses the LiteLlm-aware converter."""

    def _make_agent(self, provider="ollama", model_id=TEST_OLLAMA_MODEL_ID, **kwargs):
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
        """load_component must produce a graph whose LLM is OracleChatLiteLLM, not raise NotImplementedError."""
        loader = LiteLlmAgentSpecLoader()
        agent = self._make_agent()
        graph = loader.load_component(agent)
        bridge = _find_litellm_bridge(graph)
        assert bridge is not None, (
            "Expected OracleChatLiteLLM in the compiled graph — "
            "load_component may be using the base converter instead of the LiteLlm-aware one"
        )
        assert bridge.model == TEST_OLLAMA_CHAT_KEY

    def test_load_component_with_penalty_params(self):
        """Verify frequency/presence penalty survive the loader pipeline."""
        loader = LiteLlmAgentSpecLoader()
        agent = self._make_agent(
            provider="openai",
            model_id=TEST_OPENAI_MODEL_ID,
            max_tokens=200,
            frequency_penalty=0.5,
            presence_penalty=0.3,
        )
        graph = loader.load_component(agent)
        bridge = _find_litellm_bridge(graph)
        assert bridge is not None
        assert bridge.model == TEST_OPENAI_MODEL_KEY
        assert bridge.max_tokens == 200
        assert bridge.model_kwargs.get("frequency_penalty") == 0.5
        assert bridge.model_kwargs.get("presence_penalty") == 0.3

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
        assert bridge.model_kwargs["oci_region"] == "us-chicago-1"
        assert bridge.model_kwargs["oci_compartment_id"] == "ocid1.compartment.oc1..test"
        assert bridge.model_kwargs["oci_tenancy"] == "ocid1.tenancy.oc1..test"

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
        assert bridge.model_kwargs["oci_signer"] is fake_signer
        assert "oci_tenancy" not in bridge.model_kwargs

    def test_non_oci_provider_has_no_oci_kwargs(self):
        """Non-OCI providers should not have OCI auth keys in model_kwargs."""
        loader = LiteLlmAgentSpecLoader()
        agent = self._make_agent(provider="ollama", model_id=TEST_OLLAMA_MODEL_ID)
        graph = loader.load_component(agent)
        bridge = _find_litellm_bridge(graph)
        assert bridge is not None
        assert "oci_region" not in bridge.model_kwargs
        assert "oci_signer" not in bridge.model_kwargs

    def test_oci_loader_resolves_caller_auth_profile_not_configured(self):
        """The loader must bake the *caller's* OCI profile into model_kwargs.

        Per-client OCI pinning (e.g. server pinned to PROFILE_B while
        CONFIGURED stays on PROFILE_A) must produce a graph whose LLM
        carries PROFILE_B's compartment/region. Otherwise the cache
        identity (which already follows the caller's selection) and the
        baked OCI auth params would describe different profiles, and a
        change to the caller's profile would not affect the live graph.
        """
        from server.app.oci.schemas import OciProfileConfig
        from server.tests.runtime.shared_helpers import temporary_oci_configs

        profile_a = OciProfileConfig(
            auth_profile="PROFILE_A",
            genai_compartment_id="ocid1.compartment.oc1..a",
            genai_region="us-ashburn-1",
        )
        profile_b = OciProfileConfig(
            auth_profile="PROFILE_B",
            genai_compartment_id="ocid1.compartment.oc1..b",
            genai_region="us-chicago-1",
        )
        with temporary_oci_configs([profile_a, profile_b], client_auth_profile="PROFILE_A"):
            with patch("server.app.models.litellm_utils.get_signer", return_value=None):
                loader = LiteLlmAgentSpecLoader(auth_profile="PROFILE_B")
                agent = self._make_agent(provider="oci", model_id="cohere.command-a-03-2025")
                graph = loader.load_component(agent)

            bridge = _find_litellm_bridge(graph)
            assert bridge is not None
            assert bridge.model_kwargs["oci_compartment_id"] == "ocid1.compartment.oc1..b"
            assert bridge.model_kwargs["oci_region"] == "us-chicago-1"


class TestMcpTransportConversion:
    """AgentSpec MCP transports convert through FastMCP 4 public transports."""

    async def test_streamable_http_merges_headers_without_mutating_source(self):
        source = StreamableHTTPTransport(
            name="remote",
            url="https://mcp.example.test/",
            headers={"Accept": "application/json"},
            sensitive_headers={"X-API-Key": "secret"},
            session_parameters=SessionParameters(read_timeout_seconds=12.5),
        )

        converted = _agentspec_transport_to_fastmcp(source)

        assert isinstance(converted, StreamableHttpTransport)
        assert converted.headers == {"Accept": "application/json", "X-API-Key": "secret"}
        assert source.headers == {"Accept": "application/json"}
        assert source.sensitive_headers == {"X-API-Key": "secret"}
        assert "secret" not in AgentSpecSerializer().to_json(source)
        assert converted.httpx_client_factory is not None
        client = converted.httpx_client_factory(headers=converted.headers)
        assert isinstance(client, httpx2.AsyncClient)
        assert client.timeout.read == 12.5
        await client.aclose()

    def test_stdio_uses_fastmcp_transport(self):
        source = AgentSpecStdioTransport(
            name="stdio",
            command="example-mcp",
            args=["--stdio"],
            env={"MODE": "test"},
            cwd="/tmp",
        )

        converted = _agentspec_transport_to_fastmcp(source)

        assert isinstance(converted, FastMCPStdioTransport)
        assert converted.command == "example-mcp"
        assert converted.args == ["--stdio"]
        assert converted.env == {"MODE": "test"}
        assert str(converted.cwd) == "/tmp"

    def test_sse_uses_fastmcp_transport_and_read_timeout(self):
        source = AgentSpecSSETransport(
            name="sse",
            url="https://mcp.example.test/sse",
            headers={"Accept": "text/event-stream"},
            session_parameters=SessionParameters(read_timeout_seconds=45),
        )

        converted = _agentspec_transport_to_fastmcp(source)

        assert isinstance(converted, FastMCPSSETransport)
        assert converted.headers == {"Accept": "text/event-stream"}
        assert converted.sse_read_timeout is not None
        assert converted.sse_read_timeout.total_seconds() == 45

    def test_mtls_uses_configured_ca_and_client_certificate(self):
        ssl_context = MagicMock(check_hostname=True)
        source = StreamableHTTPmTLSTransport(
            name="mtls",
            url="https://mcp.example.test/",
            ca_file="/certs/ca.pem",
            cert_file="/certs/client.pem",
            key_file="/certs/client.key",
        )

        with patch(
            "server.app.runtime.langgraph.loader.ssl.create_default_context", return_value=ssl_context
        ) as create:
            converted = _agentspec_transport_to_fastmcp(source)

        assert isinstance(converted, StreamableHttpTransport)
        create.assert_called_once_with(cafile="/certs/ca.pem")
        ssl_context.load_cert_chain.assert_called_once_with(
            certfile="/certs/client.pem",
            keyfile="/certs/client.key",
        )
        assert ssl_context.check_hostname is True

    def test_partial_mtls_configuration_is_rejected(self):
        with pytest.raises(ValueError, match="requires both cert_file and key_file"):
            _mcp_httpx2_client_factory(read_timeout_seconds=60, cert_file="client.pem")

    def test_agent_spec_auth_mode_is_rejected(self):
        auth = OAuthConfig(
            name="oauth",
            client=OAuthClientConfig(name="client", type="pre_registered", client_id="client-id"),
            redirect_uri="https://app.example.test/callback",
        )
        source = StreamableHTTPTransport(
            name="remote",
            url="https://mcp.example.test/",
            auth=auth,
        )

        with pytest.raises(ValueError, match="Unsupported AgentSpec MCP auth mode: OAuthConfig"):
            _agentspec_transport_to_fastmcp(source)

    def test_unknown_transport_is_rejected(self):
        class UnsupportedTransport(ClientTransport):
            pass

        source = UnsupportedTransport(name="unknown")

        with pytest.raises(ValueError, match="Unsupported AgentSpec MCP transport: UnsupportedTransport"):
            _agentspec_transport_to_fastmcp(source)


class TestMcpAdapterConversion:
    """AgentSpec MCP components use LangChain's first-party MCP adapter."""

    @staticmethod
    def _source_transport() -> StreamableHTTPTransport:
        return StreamableHTTPTransport(
            name="in-process",
            url="https://unused.example.test/mcp",
            sensitive_headers={"X-API-Key": "secret"},
        )

    @staticmethod
    def _use_in_process_server(monkeypatch: pytest.MonkeyPatch, server: FastMCP) -> None:
        monkeypatch.setattr(
            loader_module,
            "_agentspec_transport_to_fastmcp",
            lambda _transport: cast(Any, server),
        )

    async def test_mcp_tool_discovery_and_call(self, monkeypatch: pytest.MonkeyPatch):
        server = FastMCP("loader-test")

        @server.tool
        async def echo(value: str) -> str:
            """Echo one value."""
            return f"echo:{value}"

        @server.tool
        async def other() -> str:
            return "other"

        self._use_in_process_server(monkeypatch, server)
        source = self._source_transport()
        tool_registry: dict[str, Any] = {}
        loader = LiteLlmAgentSpecLoader()

        tool = loader.convert(MCPTool(name="echo", client_transport=source), tool_registry=tool_registry)
        content, artifact = await tool.coroutine(value="hello")

        assert tool.name == "echo"
        assert tool.description == "Echo one value."
        assert tool.args["value"]["type"] == "string"
        assert content == "echo:hello"
        assert artifact == {"structured_content": {"result": "echo:hello"}}
        assert isinstance(tool.callbacks, list)
        assert any(isinstance(callback, AgentSpecToolCallbackHandler) for callback in tool.callbacks)
        assert f"{source.id}::echo" in tool_registry
        assert f"{source.id}::other" in tool_registry

    async def test_mcp_toolbox_filters_nl2sql_allowlist(self, monkeypatch: pytest.MonkeyPatch):
        server = FastMCP("toolbox-test")
        allowlist: list[MCPToolSpec | str] = [
            "sqlcl_connect",
            "sqlcl_schema_information",
            "sqlcl_sql_run",
            "sqlcl_request_status",
        ]

        for name in [*allowlist, "sqlcl_disconnect"]:

            async def tool_impl(value: str = "ok", _name: str = name) -> str:
                return f"{_name}:{value}"

            server.tool(tool_impl, name=name)

        self._use_in_process_server(monkeypatch, server)
        source = self._source_transport()
        toolbox = MCPToolBox(name="sqlcl", client_transport=source, tool_filter=allowlist)

        tools = LiteLlmAgentSpecLoader().convert(toolbox, tool_registry={})

        assert [tool.name for tool in tools] == allowlist

    def test_nl2sql_agent_loads_with_first_party_adapter(self, monkeypatch: pytest.MonkeyPatch):
        server = FastMCP("nl2sql-loader-test")
        for name in NL2SQL_SQLCL_TOOLS:

            async def tool_impl(_name: str = name) -> str:
                return _name

            server.tool(tool_impl, name=name)

        self._use_in_process_server(monkeypatch, server)
        agent = build_nl2sql_agentspec(
            SAMPLE_CLIENT_SETTINGS_OBJ,
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )
        loader = LiteLlmAgentSpecLoader()

        graph = loader.load_component(agent)

        assert graph is not None
        toolbox = agent.toolboxes[0]
        assert isinstance(toolbox, MCPToolBox)
        transport = toolbox.client_transport
        assert {key.removeprefix(f"{transport.id}::") for key in loader.tool_registry} == set(NL2SQL_SQLCL_TOOLS)

    def test_vecsearch_flow_loads_with_first_party_adapter(self, monkeypatch: pytest.MonkeyPatch):
        server = FastMCP("vecsearch-loader-test")

        @server.tool(name="optimizer_vs_rephrase")
        async def rephrase(thread_id: str, question: str, chat_history: list[str] | None = None) -> str:
            return question

        @server.tool(name="optimizer_vs_discovery")
        async def discovery(thread_id: str, filter_enabled_models: bool = True) -> str:
            return thread_id

        @server.tool(name="optimizer_vs_retriever")
        async def retriever(thread_id: str, question: str, collection_alias: str | None = None) -> str:
            return question

        @server.tool(name="optimizer_vs_grade")
        async def grade(thread_id: str, question: str, documents: list[dict]) -> str:
            return question

        self._use_in_process_server(monkeypatch, server)
        flow = build_vecsearch_flow(
            SAMPLE_CLIENT_SETTINGS_OBJ,
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )
        loader = LiteLlmAgentSpecLoader()

        graph = loader.load_component(flow)

        assert graph is not None
        expected = {
            "optimizer_vs_rephrase",
            "optimizer_vs_discovery",
            "optimizer_vs_retriever",
            "optimizer_vs_grade",
        }
        assert {key.rsplit("::", 1)[1] for key in loader.tool_registry} == expected

    def test_requires_confirmation_still_requires_checkpointer(self, monkeypatch: pytest.MonkeyPatch):
        server = FastMCP("confirmation-test")
        self._use_in_process_server(monkeypatch, server)
        tool = MCPTool(name="confirm", client_transport=self._source_transport(), requires_confirmation=True)

        with pytest.raises(ValueError, match="A Checkpointer is required"):
            LiteLlmAgentSpecLoader().convert(tool, tool_registry={})


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
    """Walk a compiled LangGraph to find a OracleChatLiteLLM instance.

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
        if isinstance(obj, OracleChatLiteLLM):
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
