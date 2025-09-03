"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore astream selectai

import os
import time
from typing import Literal, AsyncGenerator
import json
import oci

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph.state import CompiledStateGraph

import server.api.core.settings as core_settings
import server.api.core.oci as core_oci
import server.api.core.prompts as core_prompts
import server.api.utils.models as util_models
import server.api.utils.databases as util_databases
import server.api.utils.selectai as util_selectai
import server.api.core.mcp as core_mcp
import server.mcp.graph as graph

from common import logging_config, schema

logger = logging_config.logging.getLogger("api.utils.mcp")

def get_client(server: str = "http://127.0.0.1", port: int = 8000) -> dict:
    """Get the MCP Client Configuration"""
    mcp_client = {
        "mcpServers": {
            "optimizer": {
                "type": "streamableHttp",
                "transport": "streamable_http",
                "url": f"{server}:{port}/mcp/",
                "headers": {"Authorization": f"Bearer {os.getenv('API_SERVER_KEY')}"},
            }
        }
    }

    return mcp_client

def error_response(call: str, message: str, model: dict) -> dict:
    """Send the error as a response"""
    response = message
    if call != "streams":
        response = {
            "id": "error",
            "choices": [{"message": {"role": "assistant", "content": message}, "index": 0, "finish_reason": "stop"}],
            "created": int(time.time()),
            "model": model["model"],
            "object": "chat.completion",
        }
    logger.debug("Returning Error Response: %s", response)
    return response


async def completion_generator(
    client: schema.ClientIdType, request: schema.ChatRequest, call: Literal["completions", "streams"]
) -> AsyncGenerator[str, None]:
    """MCP Completion Requests"""
    client_settings = core_settings.get_client_settings(client)
    model = request.model_dump()
    logger.debug("Settings: %s", client_settings)
    logger.debug("Request: %s", model)

    # Establish LL Model Params (if the request specs a model, otherwise override from settings)
    if not model["model"]:
        model = client_settings.ll_model.model_dump()

    # Get OCI Settings
    oci_config = core_oci.get_oci(client=client)

    # Setup Language Model
    ll_model = util_models.get_client(model, oci_config)
    if not ll_model:
        yield error_response("I'm unable to initialise the Language Model. Please refresh the application.", model)
        return

    # Setup MCP and bind tools
    mcp_client = MultiServerMCPClient({"optimizer": core_mcp.get_client()["mcpServers"]["optimizer"]})
    tools = await mcp_client.get_tools()
    ll_model_with_tools = model.bind_tools(tools)

    # Build our Graph
    graph.set_node("tools_node", ToolNode(tools))
    agent: CompiledStateGraph = graph.mcp_graph
    # Setup MCP and bind tools
    mcp_client = MultiServerMCPClient(
        {"optimizer": core_mcp.get_client(client="langgraph")["mcpServers"]["optimizer"]}
    )
    tools = await mcp_client.get_tools()
    try:
        ll_model_with_tools = ll_model.bind_tools(tools)
    except NotImplementedError as ex:
        yield error_response(call, str(ex), model)
        raise

    # Build our Graph
    agent: CompiledStateGraph = graph.main(tools)

    kwargs = {
        "input": {"messages": [HumanMessage(content=request.messages[0].content)]},
        "config": RunnableConfig(
            configurable={"thread_id": client, "ll_model": ll_model_with_tools, "tools": tools},

            metadata={"use_history": client_settings.ll_model.chat_history},
        ),
    }

    yield "End"


    try:
        async for chunk in agent.astream_events(**kwargs, version="v2"):
            # The below will produce A LOT of output; uncomment when desperate
            # logger.debug("Streamed Chunk: %s", chunk)
            if chunk["event"] == "on_chat_model_stream":
                if "tools_condition" in str(chunk["metadata"]["langgraph_triggers"]):
                    continue  # Skip Tool Call messages
                if "vs_retrieve" in str(chunk["metadata"]["langgraph_node"]):
                    continue  # Skip Fake-Tool Call messages
                content = chunk["data"]["chunk"].content
                if content != "" and call == "streams":
                    yield content.encode("utf-8")
            last_response = chunk["data"]
    except oci.exceptions.ServiceError as ex:
        error_details = json.loads(ex.message).get("message", "")
        yield error_response(call, error_details, model)
        raise

    # Clean Up
    if call == "streams":
        yield "[stream_finished]"  # This will break the Chatbot loop
    elif call == "completions":
        final_response = last_response["output"]["final_response"]
        yield final_response  # This will be captured for ChatResponse
