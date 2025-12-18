"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore astream litellm sqlcl ollama

from typing import Literal, AsyncGenerator

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_function

from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph.graph.state import CompiledStateGraph

import litellm

import server.api.utils.settings as utils_settings
import server.api.utils.mcp as utils_mcp

import server.api.utils.oci as utils_oci
import server.api.utils.models as utils_models

from server.mcp import graph
import server.mcp.prompts.defaults as default_prompts

from common import schema
from common import logging_config

logger = logging_config.logging.getLogger("api.utils.chat")

# Configuration constants
GRAPH_RECURSION_LIMIT = 50  # Maximum depth for LangGraph execution
STREAM_FINISHED_MARKER = "[stream_finished]"  # Marker to signal end of streaming


def _get_system_prompt(tools_enabled: list) -> str:
    """Get appropriate system prompt based on enabled tools"""
    if not tools_enabled:
        return default_prompts.get_prompt_with_override("optimizer_basic-default")

    has_vs = "Vector Search" in tools_enabled
    has_nl2sql = "NL2SQL" in tools_enabled

    # Select prompt based on which tools are enabled
    if has_vs and has_nl2sql:
        return default_prompts.get_prompt_with_override("optimizer_tools-default")
    if has_vs:
        return default_prompts.get_prompt_with_override("optimizer_vs_tools-default")
    if has_nl2sql:
        return default_prompts.get_prompt_with_override("optimizer_nl2sql_tools-default")

    # Fallback for unknown tool combinations
    return default_prompts.get_prompt_with_override("optimizer_tools-default")


def _check_model_tool_support(model_config: dict, tools: list, tools_enabled: list) -> str | None:
    """Check if model supports function calling when tools are enabled"""
    if not tools:
        return None

    model_name = model_config.get("model", "unknown")
    if not litellm.supports_function_calling(model=model_name):
        error_msg = (
            f"The model '{model_name}' does not support tool/function calling. "
            f"Tools enabled: {', '.join(tools_enabled)}. "
            "Please either disable tools in settings or select a model that supports function calling."
        )
        logger.warning(error_msg)
        return error_msg

    return None


def _filter_tools_by_enabled(tools: list, tools_enabled: list) -> list:
    """Filter out tools that are not enabled and internal-only tools"""
    filtered = tools
    if "Vector Search" not in tools_enabled:
        filtered = [tool for tool in filtered if not tool.name.startswith("optimizer_vs")]
    else:
        # Filter out internal-only VS tools (grade/rephrase called by vs_orchestrate)
        # Only retriever and storage are exposed to the LLM
        internal_tools = {"optimizer_vs-grade", "optimizer_vs-rephrase"}
        filtered = [tool for tool in filtered if tool.name not in internal_tools]
    if "NL2SQL" not in tools_enabled:
        filtered = [tool for tool in filtered if not tool.name.startswith("sqlcl_")]
    return filtered


async def completion_generator(
    client: schema.ClientIdType, request: schema.ChatRequest, call: Literal["completions", "streams"]
) -> AsyncGenerator[str, None]:
    """Generate a completion from agent, stream the results"""

    client_settings = utils_settings.get_client(client)
    model = request.model_dump()
    logger.debug("Settings: %s", client_settings)
    logger.debug("Request: %s", model)

    # Establish LL Model Params (if the request specs a model, otherwise override from settings)
    if not model["model"]:
        model = client_settings.ll_model.model_dump()

    oci_config = utils_oci.get(client=client)

    # Setup Client Model
    ll_config = utils_models.get_litellm_config(model, oci_config)

    # Start to establish our LangGraph Args
    kwargs = {
        "stream_mode": "custom",
        "input": {"messages": [HumanMessage(content=request.messages[0].content)]},
        "config": RunnableConfig(
            recursion_limit=GRAPH_RECURSION_LIMIT,
            configurable={"thread_id": client, "ll_config": ll_config},
            metadata={
                "use_history": client_settings.ll_model.chat_history,
                "vector_search": client_settings.vector_search,
            },
        ),
    }

    # Get System Prompt
    kwargs["config"]["metadata"]["sys_prompt"] = _get_system_prompt(client_settings.tools_enabled)

    # Define MCP config and tools (this is to create conditional nodes in the graph)
    mcp_client = MultiServerMCPClient(
        {"optimizer": utils_mcp.get_client(client="langgraph")["mcpServers"]["optimizer"]}
    )

    # Fetch and filter MCP Tools
    graph_tools = await mcp_client.get_tools()
    graph_tools = _filter_tools_by_enabled(graph_tools, client_settings.tools_enabled)

    # Convert LangChain tools to OpenAI Functions for binding to LiteLLM model
    kwargs["config"]["metadata"]["tools"] = [
        {"type": "function", "function": convert_to_openai_function(t)} for t in graph_tools
    ]

    # Force VS retriever tool only when Vector Search is the ONLY enabled tool
    # When both VS and NL2SQL are enabled, let the LLM choose based on the prompt
    # This prevents forcing VS for administrative queries (connect, disconnect, etc.)
    forced_tool = None
    if len(client_settings.tools_enabled) == 1 and "Vector Search" in client_settings.tools_enabled:
        forced_tool = "optimizer_vs-retriever"
        logger.info("VS-only mode: Will force optimizer_vs-retriever when documents empty")

    kwargs["config"]["metadata"]["forced_tool"] = forced_tool
    logger.debug("Completion Kwargs: %s", kwargs)

    # Establish the graph
    agent: CompiledStateGraph = graph.main(graph_tools)

    final_response = None

    try:
        async for output in agent.astream(**kwargs):
            if "stream" in output:
                yield output["stream"].encode("utf-8")
            elif "completion" in output:
                final_response = output["completion"]
            elif "vs_metadata" in output or "token_usage" in output:
                # Log metadata emissions (automatically stored in AIMessage.response_metadata by graph.py)
                logger.debug("Metadata emitted: %s", {k: v for k, v in output.items() if k != "stream"})

        if call == "streams":
            yield STREAM_FINISHED_MARKER  # This will break the Chatbot loop
        elif call == "completions" and final_response is not None:
            yield final_response  # This will be captured for ChatResponse
    except Exception as ex:
        logger.exception("Graph execution failed")
        error_text = (
            f"I'm sorry, I've run into a problem: {str(ex)}\n\n"
            "Please raise an issue at: https://github.com/oracle/ai-optimizer/issues"
        )
        if call == "streams":
            yield error_text.encode("utf-8")
            yield STREAM_FINISHED_MARKER
        else:
            yield {"choices": [{"message": {"role": "assistant", "content": error_text}}]}
