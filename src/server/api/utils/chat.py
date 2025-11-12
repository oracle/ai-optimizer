"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore astream litellm sqlcl

from typing import Literal, AsyncGenerator

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_function

from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph.graph.state import CompiledStateGraph

import server.api.core.settings as core_settings
import server.api.utils.mcp as utils_mcp

import server.api.utils.oci as utils_oci
import server.api.utils.models as utils_models

from server.mcp import graph
import server.mcp.prompts.defaults as default_prompts

from common import schema
from common import logging_config

logger = logging_config.logging.getLogger("api.utils.chat")


async def completion_generator(
    client: schema.ClientIdType, request: schema.ChatRequest, call: Literal["completions", "streams"]
) -> AsyncGenerator[str, None]:
    """Generate a completion from agent, stream the results"""

    client_settings = core_settings.get_client_settings(client)
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
            recursion_limit=50,
            configurable={"thread_id": client, "ll_config": ll_config},
            metadata={
                "use_history": client_settings.ll_model.chat_history,
                "vector_search": client_settings.vector_search,
            },
        ),
    }

    # Get System Prompt
    kwargs["config"]["metadata"]["sys_prompt"] = default_prompts.get_prompt_with_override("optimizer_basic-default")

    # Define MCP config and tools (this is to create conditional nodes in the graph)
    mcp_client = MultiServerMCPClient(
        {"optimizer": utils_mcp.get_client(client="langgraph")["mcpServers"]["optimizer"]}
    )

    # Fetch all MCP Tools
    graph_tools = await mcp_client.get_tools()

    # Filter out Vector Search tools if not enabled (retriever and storage tools only)
    if "Vector Search" not in client_settings.tools_enabled:
        graph_tools = [tool for tool in graph_tools if not tool.name.startswith("optimizer_vs")]

    # Filter out NL2SQL tools if not enabled
    if "NL2SQL" not in client_settings.tools_enabled:
        graph_tools = [tool for tool in graph_tools if not tool.name.startswith("sqlcl_")]

    # Convert LangChain tools to OpenAI Functions for binding to LiteLLM model
    # Always set tools in metadata, even if empty, to prevent NoneType errors
    # Filter out internal parameters that should not be exposed to LLM
    def clean_tool_schema(tool_schema):
        """Remove internal parameters from tool schema and descriptions"""
        params_to_exclude = {"thread_id", "mcp_client", "model"}

        # Remove parameters from schema
        if "parameters" in tool_schema and "properties" in tool_schema["parameters"]:
            tool_schema["parameters"]["properties"] = {
                k: v for k, v in tool_schema["parameters"]["properties"].items() if k not in params_to_exclude
            }
            if "required" in tool_schema["parameters"]:
                tool_schema["parameters"]["required"] = [
                    r for r in tool_schema["parameters"]["required"] if r not in params_to_exclude
                ]

        # Remove parameter mentions from description
        if "description" in tool_schema:
            desc = tool_schema["description"]
            # Remove lines mentioning model/mcp_client arguments
            lines = desc.split("\n")
            cleaned_lines = [
                line
                for line in lines
                if not any(
                    phrase in line
                    for phrase in ["The `model` argument", "The `mcp_client` argument", "mcp_client:", "model:"]
                )
            ]
            tool_schema["description"] = "\n".join(cleaned_lines).strip()

        return tool_schema

    kwargs["config"]["metadata"]["tools"] = [
        {"type": "function", "function": clean_tool_schema(convert_to_openai_function(t))} for t in graph_tools
    ]
    logger.debug("Completion Kwargs: %s", kwargs)

    # Establish the graph
    agent: CompiledStateGraph = graph.main(graph_tools)

    final_response = None
    async for output in agent.astream(**kwargs):
        if "stream" in output:
            yield output["stream"].encode("utf-8")
        if "completion" in output:
            final_response = output["completion"]
    if call == "streams":
        yield "[stream_finished]"  # This will break the Chatbot loop
    if call == "completions" and final_response is not None:
        yield final_response  # This will be captured for ChatResponse
