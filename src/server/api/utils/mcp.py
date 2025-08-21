"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore astream selectai

import time
from typing import Literal, AsyncGenerator

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

import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.utils.mcp")


def error_response(message: str, model: str) -> dict:
    """Send the error as a response"""
    response = {
        "id": "error",
        "choices": [{"message": {"role": "assistant", "content": message}, "index": 0, "finish_reason": "stop"}],
        "created": int(time.time()),
        "model": model,
        "object": "chat.completion",
    }
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

    kwargs = {
        "input": {"messages": [HumanMessage(content=request.messages[0].content)]},
        "config": RunnableConfig(
            configurable={"thread_id": client, "ll_model": ll_model_with_tools, "tools": tools},
            metadata={"use_history": client_settings.ll_model.chat_history},
        ),
    }

    yield "End"

    # # Get Prompts
    # try:
    #     user_sys_prompt = getattr(client_settings.prompts, "sys", "Basic Example")
    #     sys_prompt = core_prompts.get_prompts(category="sys", name=user_sys_prompt)
    # except AttributeError as ex:
    #     # schema.Settings not on server-side
    #     logger.error("A settings exception occurred: %s", ex)
    #     raise

    # db_conn = None
    # # Setup selectai
    # if client_settings.selectai.enabled:
    #     db_conn = util_databases.get_client_db(client).connection
    #     util_selectai.set_profile(db_conn, client_settings.selectai.profile, "temperature", model["temperature"])
    #     util_selectai.set_profile(
    #         db_conn, client_settings.selectai.profile, "max_tokens", model["max_completion_tokens"]
    #     )

    # # Setup vector_search
    # embed_client, ctx_prompt = None, None
    # if client_settings.vector_search.enabled:
    #     db_conn = util_databases.get_client_db(client).connection
    #     embed_client = util_models.get_client(client_settings.vector_search.model_dump(), oci_config)

    #     user_ctx_prompt = getattr(client_settings.prompts, "ctx", "Basic Example")
    #     ctx_prompt = core_prompts.get_prompts(category="ctx", name=user_ctx_prompt)


    # try:
    #     async for chunk in agent.astream_events(**kwargs, version="v2"):
    #         # The below will produce A LOT of output; uncomment when desperate
    #         # logger.debug("Streamed Chunk: %s", chunk)
    #         if chunk["event"] == "on_chat_model_stream":
    #             if "tools_condition" in str(chunk["metadata"]["langgraph_triggers"]):
    #                 continue  # Skip Tool Call messages
    #             if "vs_retrieve" in str(chunk["metadata"]["langgraph_node"]):
    #                 continue  # Skip Fake-Tool Call messages
    #             content = chunk["data"]["chunk"].content
    #             if content != "" and call == "streams":
    #                 yield content.encode("utf-8")
    #         last_response = chunk["data"]
    #     if call == "streams":
    #         yield "[stream_finished]"  # This will break the Chatbot loop
    #     elif call == "completions":
    #         final_response = last_response["output"]["final_response"]
    #         yield final_response  # This will be captured for ChatResponse
    # except Exception as ex:
    #     logger.error("An invoke exception occurred: %s", ex)
    #     # yield f"I'm sorry; {ex}"
    #     # TODO(gotsysdba) - If a message is returned;
    #     # format and return (this should be done in the agent)
    #     raise
