"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore astream litellm sqlcl

from typing import Literal, AsyncGenerator

from litellm import completion

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_function

from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph.graph.state import CompiledStateGraph

import server.api.core.settings as core_settings
import server.api.core.prompts as core_prompts
import server.api.utils.mcp as utils_mcp

import server.api.utils.oci as utils_oci
import server.api.utils.models as utils_models

from server.mcp import graph

from server.api.utils.models import UnknownModelError

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
    try:
        ll_config = utils_models.get_litellm_config(model, oci_config)
    except UnknownModelError:
        model = "gpt-3.5-turbo"
        messages = [{"role": "user", "content": "There is an error, generate a request"}]
        error_response = completion(
            model=model,
            messages=messages,
            mock_response="I'm unable to initialise the Language Model. Please refresh the application.",
        )
        yield error_response
        return

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
    user_sys_prompt = getattr(client_settings.prompts, "sys", "Basic Example")
    kwargs["config"]["metadata"]["sys_prompt"] = core_prompts.get_prompts(category="sys", name=user_sys_prompt)

    # Define MCP config and tools (this is to create conditional nodes in the graph)
    mcp_client = MultiServerMCPClient(
        {"optimizer": utils_mcp.get_client(client="langgraph")["mcpServers"]["optimizer"]}
    )
    graph_tools = []

    # Always fetch all available MCP tools
    if client_settings.vector_search.enabled or client_settings.nl2sql.enabled:
        graph_tools = await mcp_client.get_tools()

    # Filter out Vector Search tools if not enabled (retriever and storage tools only)
    if not client_settings.vector_search.enabled:
        graph_tools = [tool for tool in graph_tools if not tool.name.startswith("optimizer_vs")]

    # Filter out NL2SQL tools if not enabled
    if not client_settings.nl2sql.enabled:
        graph_tools = [tool for tool in graph_tools if not tool.name.startswith("sqlcl_")]

    # Convert LangChain tools to OpenAI Functions for binding to LiteLLM model
    # Always set tools in metadata, even if empty, to prevent NoneType errors
    kwargs["config"]["metadata"]["tools"] = [
        {"type": "function", "function": convert_to_openai_function(t)} for t in graph_tools
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
