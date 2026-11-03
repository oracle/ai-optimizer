"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Custom AgentSpec → LangGraph loader with LiteLLM and MCP auth support.

Provides:
- LiteLlmAgentSpecLoader: combines the loader and converter roles, handling
  LiteLlmConfig → OracleChatLiteLLM and AgentSpec MCP → LangChain MCP conversion.
"""
# spell-checker: ignore ollama agenerate agentspec agentspecloader ainvoke astream checkpointer
# spell-checker: ignore clienttransport fastmcp httpx langgraphconverter litellm pyagentspec serialises

import ssl
from typing import Any, Optional, cast

import httpx2
from anyio.to_thread import run_sync
from fastmcp import Client as FastMCPClient
from fastmcp.client.transports import ClientTransport as FastMCPClientTransport
from fastmcp.client.transports import SSETransport as FastMCPSSETransport
from fastmcp.client.transports import StdioTransport as FastMCPStdioTransport
from fastmcp.client.transports import StreamableHttpTransport as FastMCPStreamableHttpTransport
from langchain.mcp import MCPAdapter
from langchain_core.callbacks import BaseCallbackHandler, BaseCallbackManager
from langchain_core.tools import BaseTool
from langgraph.prebuilt.tool_node import ToolNode
from pyagentspec.adapters.langgraph._langgraphconverter import AgentSpecToLangGraphConverter
from pyagentspec.adapters.langgraph._types import LangGraphComponent
from pyagentspec.adapters.langgraph.agentspecloader import AgentSpecLoader as LangGraphAgentSpecLoader
from pyagentspec.adapters.langgraph.mcp_utils import run_async_in_sync
from pyagentspec.adapters.langgraph.tracing import AgentSpecToolCallbackHandler
from pyagentspec.mcp import MCPTool, MCPToolBox, MCPToolSpec
from pyagentspec.mcp.clienttransport import ClientTransport, RemoteTransport
from pyagentspec.mcp.clienttransport import SSEmTLSTransport as AgentSpecSSEmTLSTransport
from pyagentspec.mcp.clienttransport import SSETransport as AgentSpecSSETransport
from pyagentspec.mcp.clienttransport import StdioTransport as AgentSpecStdioTransport
from pyagentspec.mcp.clienttransport import StreamableHTTPmTLSTransport as AgentSpecStreamableHTTPmTLSTransport
from pyagentspec.mcp.clienttransport import StreamableHTTPTransport as AgentSpecStreamableHTTPTransport
from pyagentspec.property import Property as AgentSpecProperty
from pyagentspec.property import StringProperty as AgentSpecStringProperty
from pyagentspec.property import json_schemas_have_same_type

from server.app.agentspec.adapters.litellm import LiteLlmConfig, get_litellm_deserialization_plugin
from server.app.core.secrets import reveal
from server.app.mcp.tools.schemas import get_oci_profile
from server.app.models.litellm_utils import (
    build_oci_litellm_params,
    strip_unsupported_penalties,
)
from server.app.oci.registry import find_oci_profile_by_name
from server.app.runtime.langgraph.adapters.litellm import OracleChatLiteLLM
from server.app.runtime.ollama_tools import normalize_ollama_provider


def _mcp_httpx2_client_factory(
    *,
    read_timeout_seconds: float,
    ca_file: str | None = None,
    cert_file: str | None = None,
    key_file: str | None = None,
):
    """Build HTTPX2 clients with AgentSpec TLS and timeout settings."""
    if (cert_file is None) != (key_file is None):
        raise ValueError("MCP mutual TLS requires both cert_file and key_file")

    ssl_context = ssl.create_default_context(cafile=ca_file)
    if cert_file and key_file:
        ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        **kwargs: Any,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            headers=headers,
            timeout=timeout or httpx2.Timeout(30.0, read=read_timeout_seconds),
            auth=auth,
            verify=ssl_context,
            **kwargs,
        )

    return factory


def _agentspec_transport_to_fastmcp(transport: ClientTransport) -> FastMCPClientTransport:
    """Convert an AgentSpec MCP transport without mutating its configuration."""
    read_timeout = transport.session_parameters.read_timeout_seconds
    if isinstance(transport, AgentSpecStdioTransport):
        return FastMCPStdioTransport(
            command=transport.command,
            args=list(transport.args),
            env=dict(transport.env) if transport.env else None,
            cwd=transport.cwd,
        )

    if not isinstance(transport, RemoteTransport):
        raise ValueError(f"Unsupported AgentSpec MCP transport: {transport.__class__.__name__}")
    if transport.auth is not None:
        raise ValueError(f"Unsupported AgentSpec MCP auth mode: {transport.auth.__class__.__name__}")

    headers = {**(transport.headers or {}), **(transport.sensitive_headers or {})}
    tls: dict[str, str] = {}
    if isinstance(transport, AgentSpecSSEmTLSTransport | AgentSpecStreamableHTTPmTLSTransport):
        tls = {
            "ca_file": transport.ca_file,
            "cert_file": transport.cert_file,
            "key_file": transport.key_file,
        }
    client_factory = _mcp_httpx2_client_factory(read_timeout_seconds=read_timeout, **tls)

    if isinstance(transport, AgentSpecSSETransport):
        return FastMCPSSETransport(
            url=transport.url,
            headers=headers,
            sse_read_timeout=read_timeout,
            httpx_client_factory=client_factory,
        )
    if isinstance(transport, AgentSpecStreamableHTTPTransport):
        return FastMCPStreamableHttpTransport(
            url=transport.url,
            headers=headers,
            httpx_client_factory=client_factory,
        )
    raise ValueError(f"Unsupported AgentSpec MCP transport: {transport.__class__.__name__}")


def _registry_tools(tool_registry: dict[str, Any], prefix: str) -> dict[str, BaseTool]:
    """Return cached MCP tools for one AgentSpec transport."""
    return {
        key.removeprefix(prefix): cast(BaseTool, tool) for key, tool in tool_registry.items() if key.startswith(prefix)
    }


def _normalize_schema_title(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(schema)
    if isinstance(normalized.get("title"), str):
        normalized["title"] = normalized["title"].lower()
    return normalized


def _mcp_tool_spec_matches(spec: MCPToolSpec, tool: BaseTool) -> bool:
    if not isinstance(tool.args_schema, dict):
        raise ValueError(f"Expected LangChain tool args_schema to be a dict, got {type(tool.args_schema)}")
    local = {prop.json_schema["title"]: _normalize_schema_title(prop.json_schema) for prop in (spec.inputs or [])}
    remote = {name: _normalize_schema_title(schema) for name, schema in tool.args_schema.get("properties", {}).items()}
    return json_schemas_have_same_type(local, remote)


def _enable_tool_error_handling(graph):
    """Patch ToolNode instances to return errors as messages instead of raising.

    This lets the LLM see tool errors (e.g. ORA-17008 closed connection) and
    respond gracefully instead of crashing the agent invocation.
    """
    for node in graph.nodes.values():
        if isinstance(getattr(node, "bound", None), ToolNode):
            setattr(node.bound, "_handle_tool_errors", True)


def _unwrap_tool_content_blocks(tool):
    """Wrap a LangChain MCP tool to extract text from content blocks.

    LangChain's MCP adapter wraps text results in content blocks:
    ``[{"type": "text", "text": "<payload>"}]``. When
    pyagentspec's ``ToolNodeExecutor`` receives this list it JSON-serialises
    it into a string, so downstream nodes (LlmNode, EndNode) see the
    wrapper instead of the actual payload.

    This wraps the tool's async coroutine so the ``content_and_artifact``
    return value yields the raw text string instead of the content-block
    list, which ``ToolNodeExecutor`` then passes through unchanged.
    """
    original = tool.coroutine

    async def _unwrapping_coroutine(*args, **kwargs):
        """Call the original coroutine and unwrap a single-text content block."""
        result = await original(*args, **kwargs)
        if not isinstance(result, tuple) or len(result) != 2:
            return result
        content, artifact = result
        if isinstance(content, list) and len(content) == 1:
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text" and "text" in first:
                return first["text"], artifact
        return result

    tool.coroutine = _unwrapping_coroutine
    return tool


class LiteLlmAgentSpecLoader(LangGraphAgentSpecLoader, AgentSpecToLangGraphConverter):
    """AgentSpec loader with LiteLlmConfig deserialization and custom converter.

    Combines the loader and converter roles: handles LiteLlmConfig → OracleChatLiteLLM
    and merges sensitive_headers into transport headers for MCP auth.
    """

    def __init__(self, checkpointer=None, config=None, auth_profile=None, **kwargs):
        LangGraphAgentSpecLoader.__init__(
            self,
            plugins=[get_litellm_deserialization_plugin()],
            checkpointer=checkpointer,
            config=config,
            **kwargs,
        )
        self._auth_profile = auth_profile

    def load_component(self, agentspec_component):
        """Use self as converter so LiteLlmConfig is handled."""
        return self.convert(
            agentspec_component=agentspec_component,
            tool_registry=self.tool_registry,
            checkpointer=self.checkpointer,
            config=self.config,
        )

    def convert(
        self,
        agentspec_component,
        tool_registry,
        converted_components=None,
        checkpointer=None,
        config=None,
        middleware=None,
        **kwargs,
    ):
        """Route MCP components around PyAgentSpec 26.3.1's archived adapter."""
        if isinstance(agentspec_component, MCPTool | MCPToolBox):
            if converted_components is None:
                converted_components = {}
            if agentspec_component.id not in converted_components:
                if isinstance(agentspec_component, MCPTool):
                    if agentspec_component.requires_confirmation and checkpointer is None:
                        raise ValueError(
                            f"A Checkpointer is required for tool '{agentspec_component.name}' "
                            "because requires_confirmation=True"
                        )
                    converted = self._mcp_tool_convert_to_langgraph(
                        agentspec_component,
                        tool_registry,
                        converted_components,
                    )
                else:
                    converted = self._mcp_toolbox_convert_to_langgraph(
                        agentspec_component,
                        tool_registry,
                        converted_components,
                    )
                converted_components[agentspec_component.id] = converted
            return converted_components[agentspec_component.id]
        return super().convert(
            agentspec_component,
            tool_registry,
            converted_components=converted_components,
            checkpointer=checkpointer,
            config=config,
            middleware=middleware,
            **kwargs,
        )

    def _resolve_oci_profile(self):
        """Resolve the pinned profile, or fall back to CONFIGURED if unpinned."""
        if self._auth_profile is None:
            return get_oci_profile()
        return find_oci_profile_by_name(self._auth_profile)

    def _llm_convert_to_langgraph(self, llm_config, config):
        if isinstance(llm_config, LiteLlmConfig):
            provider = llm_config.provider
            if provider is None:
                raise ValueError(f"LiteLlmConfig '{llm_config.id}' is missing a provider to route the model")
            model_kwargs: dict = {}
            if provider == "oci":
                oci_profile = self._resolve_oci_profile()
                if oci_profile:
                    model_kwargs.update(build_oci_litellm_params(oci_profile))
            provider = normalize_ollama_provider(provider)
            model_key = f"{provider}/{llm_config.model_id}"
            freq, pres = strip_unsupported_penalties(
                model_key,
                llm_config.frequency_penalty,
                llm_config.presence_penalty,
            )
            if freq is not None:
                model_kwargs["frequency_penalty"] = freq
            if pres is not None:
                model_kwargs["presence_penalty"] = pres
            return OracleChatLiteLLM(
                model=model_key,
                api_key=reveal(llm_config.api_key),
                api_base=llm_config.api_base,
                max_tokens=llm_config.max_tokens,
                model_kwargs=model_kwargs,
                # ``streaming=True`` makes ``_agenerate`` route through ``_astream`` when
                # graph nodes call ``await llm.ainvoke(...)`` under ``astream_events``.
                # Without it, ``should_stream = stream if stream is not None else self.streaming``
                # falls to ``False`` and no ``on_chat_model_stream`` events fire — the
                # ``session.execute`` no-stream fallback then emits the answer as a single chunk.
                streaming=True,
            )
        return super()._llm_convert_to_langgraph(llm_config, config)

    def _create_react_agent_with_given_info(self, **kwargs):
        """Override to enable graceful tool error handling on the compiled graph."""
        graph = super()._create_react_agent_with_given_info(**kwargs)
        _enable_tool_error_handling(graph)
        return graph

    def _get_or_create_mcp_tools(
        self,
        client_transport: ClientTransport,
        fastmcp_transport: FastMCPClientTransport,
        tool_registry: dict[str, Any],
    ) -> dict[str, BaseTool]:
        prefix = f"{client_transport.id}::"
        existing = _registry_tools(tool_registry, prefix)
        if existing:
            return existing

        client = FastMCPClient(
            fastmcp_transport,
            timeout=client_transport.session_parameters.read_timeout_seconds,
        )
        adapter = MCPAdapter(client)
        tools = run_async_in_sync(adapter.list_tools, method_name="MCPAdapter.list_tools")
        staged: dict[str, BaseTool] = {}
        for tool in tools:
            agentspec_tool = MCPTool(
                name=tool.name,
                description=tool.description,
                client_transport=client_transport,
                inputs=[AgentSpecProperty(title=name, json_schema=schema) for name, schema in tool.args.items()],
                outputs=[AgentSpecStringProperty(title="tool_output")],
            )
            configured_callbacks = tool.callbacks
            callbacks: list[BaseCallbackHandler]
            if isinstance(configured_callbacks, list):
                callbacks = list(configured_callbacks)
            elif isinstance(configured_callbacks, BaseCallbackManager):
                callbacks = list(configured_callbacks.handlers)
            elif isinstance(configured_callbacks, BaseCallbackHandler):
                callbacks = [configured_callbacks]
            else:
                callbacks = []
            callbacks.append(AgentSpecToolCallbackHandler(tool=agentspec_tool))
            tool.callbacks = callbacks
            _unwrap_tool_content_blocks(tool)
            key = f"{prefix}{tool.name}"
            if key in tool_registry or key in staged:
                raise ValueError(f"MCP tool '{tool.name}' is already registered for transport '{client_transport.id}'")
            staged[key] = tool
        tool_registry.update(staged)
        return _registry_tools(tool_registry, prefix)

    def _mcp_tool_convert_to_langgraph(self, agentspec_mcp_tool, tool_registry, converted_components):
        fastmcp_transport = self.convert(
            agentspec_mcp_tool.client_transport,
            tool_registry=tool_registry,
            converted_components=converted_components,
        )
        tools = self._get_or_create_mcp_tools(
            agentspec_mcp_tool.client_transport,
            fastmcp_transport,
            tool_registry,
        )
        try:
            return tools[agentspec_mcp_tool.name]
        except KeyError as exc:
            raise ValueError(f"Missing MCP tool: {agentspec_mcp_tool.name}") from exc

    def _mcp_toolbox_convert_to_langgraph(self, agentspec_mcp_toolbox, tool_registry, converted_components):
        fastmcp_transport = self.convert(
            agentspec_mcp_toolbox.client_transport,
            tool_registry=tool_registry,
            converted_components=converted_components,
        )
        tools = self._get_or_create_mcp_tools(
            agentspec_mcp_toolbox.client_transport,
            fastmcp_transport,
            tool_registry,
        )
        filters = {
            item if isinstance(item, str) else item.name: None if isinstance(item, str) else item
            for item in (agentspec_mcp_toolbox.tool_filter or [])
        }
        if not filters:
            return list(tools.values())
        missing = sorted(name for name in filters if name not in tools)
        if missing:
            raise ValueError("Missing tools: " + ", ".join(missing))
        for name, spec in filters.items():
            if spec is not None and not _mcp_tool_spec_matches(spec, tools[name]):
                raise ValueError(f"Input descriptors mismatch for tool '{name}'")
        return [tools[name] for name in filters]

    def _client_transport_convert_to_langgraph(self, agentspec_component: ClientTransport):
        return _agentspec_transport_to_fastmcp(agentspec_component)


async def load_langgraph_component(
    agentspec_component: Any,
    checkpointer=None,
    config=None,
    auth_profile: Optional[str] = None,
) -> Any:
    """Load an AgentSpec component into LangGraph with LiteLLM support.

    Runs the synchronous loader in a worker thread so the event loop stays
    free to accept inbound MCP connections from pyagentspec's tool discovery.

    *auth_profile* selects which OCI profile the loader bakes into the
    LLM's ``model_kwargs``. When omitted, falls back to CONFIGURED.
    """
    loader = LiteLlmAgentSpecLoader(checkpointer=checkpointer, config=config, auth_profile=auth_profile)
    return await run_sync(lambda: cast(LangGraphComponent, loader.load_component(agentspec_component)))
