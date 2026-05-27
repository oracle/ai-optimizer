"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Custom AgentSpec → LangGraph loader with LiteLLM and MCP auth support.

Provides:
- LiteLlmAgentSpecLoader: combines the loader and converter roles, handling
  LiteLlmConfig → OracleChatLiteLLM and merging sensitive_headers into MCP connection headers.
"""
# spell-checker: ignore ollama agenerate agentspec agentspecloader ainvoke astream checkpointer
# spell-checker: ignore clienttransport langgraphconverter litellm pyagentspec serialises

import logging
import threading as _threading
from typing import Any, Optional, cast

import anyio as _anyio
import pyagentspec.adapters.langgraph.mcp_utils as _mcp_utils
from anyio.to_thread import run_sync
from langgraph.prebuilt.tool_node import ToolNode
from pyagentspec.adapters.langgraph._langgraphconverter import AgentSpecToLangGraphConverter
from pyagentspec.adapters.langgraph._types import LangGraphComponent
from pyagentspec.adapters.langgraph.agentspecloader import AgentSpecLoader as LangGraphAgentSpecLoader
from pyagentspec.mcp.clienttransport import ClientTransport, RemoteTransport

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

# ---------------------------------------------------------------------------
# Monkey-patch: pyagentspec's get_execution_context() catches only
# sniffio.AsyncLibraryNotFoundError, but anyio ≥ 4.x raises its own
# anyio.NoEventLoopError from get_current_task().  Patch the except clause
# so MCP tool loading works correctly inside anyio worker threads.
# ---------------------------------------------------------------------------
_orig_get_execution_context = _mcp_utils.get_execution_context


def _patched_get_execution_context() -> _mcp_utils.AsyncContext:
    try:
        return _orig_get_execution_context()
    except _anyio.NoEventLoopError:
        worker_name = _threading.current_thread().name.lower()
        if "worker" in worker_name and "anyio" in worker_name:
            return _mcp_utils.AsyncContext.SYNC_WORKER
        return _mcp_utils.AsyncContext.SYNC


_mcp_utils.get_execution_context = _patched_get_execution_context
# ---------------------------------------------------------------------------

LOGGER = logging.getLogger(__name__)


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

    ``langchain_mcp_adapters`` wraps every MCP text result in LangChain
    content blocks: ``[{"type": "text", "text": "<payload>"}]``.  When
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
        if isinstance(content, list) and content:
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

    def _resolve_oci_profile(self):
        """Resolve the pinned profile, or fall back to CONFIGURED if unpinned."""
        if self._auth_profile is None:
            return get_oci_profile()
        return find_oci_profile_by_name(self._auth_profile)

    def _llm_convert_to_langgraph(self, llm_config, config):
        if isinstance(llm_config, LiteLlmConfig):
            model_kwargs: dict = {}
            if llm_config.provider == "oci":
                oci_profile = self._resolve_oci_profile()
                if oci_profile:
                    model_kwargs.update(build_oci_litellm_params(oci_profile))
            provider = normalize_ollama_provider(llm_config.provider)
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

    def _mcp_tool_convert_to_langgraph(self, agentspec_mcp_tool, tool_registry, converted_components=None):
        """Override to unwrap content blocks from MCP tool results.

        ``langchain_mcp_adapters`` wraps MCP text results in content blocks
        which breaks pyagentspec's data-edge pipeline in flow graphs. This
        wraps each tool so downstream nodes receive the raw text payload.
        """
        if converted_components is None:
            converted_components = {}
        tool = super()._mcp_tool_convert_to_langgraph(agentspec_mcp_tool, tool_registry, converted_components)
        return _unwrap_tool_content_blocks(tool)

    def _client_transport_convert_to_langgraph(self, agentspec_component: ClientTransport):
        """Merge sensitive_headers into headers before conversion.

        The base implementation only passes ``headers`` to the LangGraph
        connection objects, dropping ``sensitive_headers``. Our MCP auth
        uses ``sensitive_headers`` for the API key, so we merge them.
        """
        if isinstance(agentspec_component, RemoteTransport):
            sensitive = agentspec_component.sensitive_headers
            if sensitive:
                merged = {**(agentspec_component.headers or {}), **sensitive}
                agentspec_component = agentspec_component.model_copy(update={"headers": merged})
        return super()._client_transport_convert_to_langgraph(agentspec_component)


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
