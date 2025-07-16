"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore astream selectai

import time
from typing import Literal, AsyncGenerator

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from server.api.core import selectai, settings, oci, models, prompts, databases

import common.schema as schema
import common.logging_config as logging_config
import server.agents.chatbot as chatbot

logger = logging_config.logging.getLogger("api.core.chat")


async def completion_generator(
    client: schema.ClientIdType, request: schema.ChatRequest, call: Literal["completions", "streams"]
) -> AsyncGenerator[str, None]:
    """Generate a completion from agent, stream the results"""
    client_settings = settings.get_client_settings(client)
    model = request.model_dump()
    logger.debug("Settings: %s", client_settings)
    logger.debug("Request: %s", model)

    # Establish LL schema.Model Params (if the request specs a model, otherwise override from settings)
    if not model["model"]:
        model = client_settings.ll_model.model_dump()

    oci_config = oci.get_oci(client=client)

    # Setup Client schema.Model
    ll_client = models.get_client({"model": model, "enabled": True}, oci_config)
    if not ll_client:
        error_response = {
            "id": "error",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "I'm unable to initialise the Language Model. Please refresh the application.",
                    },
                    "index": 0,
                    "finish_reason": "stop",
                }
            ],
            "created": int(time.time()),
            "model": model.get("model", "unknown"),
            "object": "chat.completion",
        }
        yield error_response
        return

    # Get Prompts
    try:
        user_sys_prompt = getattr(client_settings.prompts, "sys", "Basic Example")
        sys_prompt = prompts.get_prompts(category="sys", name=user_sys_prompt)
    except AttributeError as ex:
        # schema.Settings not on server-side
        logger.error("A settings exception occurred: %s", ex)
        raise

    db_conn = None
    # Setup selectai
    if client_settings.selectai.enabled:
        db_conn = databases.get_client_db(client).connection
        selectai.set_profile(db_conn, client_settings.selectai.profile, "temperature", model["temperature"])
        selectai.set_profile(db_conn, client_settings.selectai.profile, "max_tokens", model["max_completion_tokens"])

    # Setup vector_search
    embed_client, ctx_prompt = None, None
    if client_settings.vector_search.enabled:
        db_conn = databases.get_client_db(client).connection
        embed_client = models.get_client(client_settings.vector_search.model_dump(), oci_config)

        user_ctx_prompt = getattr(client_settings.prompts, "ctx", "Basic Example")
        ctx_prompt = prompts.get_prompts(category="ctx", name=user_ctx_prompt)

    kwargs = {
        "input": {"messages": [HumanMessage(content=request.messages[0].content)]},
        "config": RunnableConfig(
            configurable={
                "thread_id": client,
                "ll_client": ll_client,
                "embed_client": embed_client,
                "db_conn": db_conn,
            },
            metadata={
                "model_name": model["model"],
                "use_history": client_settings.ll_model.chat_history,
                "vector_search": client_settings.vector_search,
                "selectai": client_settings.selectai,
                "sys_prompt": sys_prompt,
                "ctx_prompt": ctx_prompt,
            },
        ),
    }
    logger.debug("Completion Kwargs: %s", kwargs)
    agent: CompiledStateGraph = chatbot.chatbot_graph
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
        if call == "streams":
            yield "[stream_finished]"  # This will break the Chatbot loop
        elif call == "completions":
            final_response = last_response["output"]["final_response"]
            yield final_response  # This will be captured for ChatResponse
    except Exception as ex:
        logger.error("An invoke exception occurred: %s", ex)
        # yield f"I'm sorry; {ex}"
        # TODO(gotsysdba) - If a message is returned;
        # format and return (this should be done in the agent)
        raise
