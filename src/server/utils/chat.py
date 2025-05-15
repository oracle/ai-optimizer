"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import time
from typing import Literal, AsyncGenerator
from common.schema import ChatRequest

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.utils.chat")


async def completion_generator(
    client: schema.ClientIdType, request: ChatRequest, call: Literal["completions", "streams"]
) -> AsyncGenerator[str, None]:
    """Generate a completion from agent, stream the results"""
    client_settings = get_client_settings(client)
    logger.debug("Settings: %s", client_settings)
    logger.debug("Request: %s", request.model_dump())

    # Establish LL schema.Model Params (if the request specs a model, otherwise override from settings)
    model = request.model_dump()
    if not model["model"]:
        model = client_settings.ll_model.model_dump()

    oci_config = get_client_oci(client)
    # Setup Client schema.Model
    ll_client = await models.get_client(MODEL_OBJECTS, model, oci_config)
    if not ll_client:
        error_response = {
            "id": "error",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "I'm sorry, I'm unable to initialise the Language Model. Please refresh the application.",
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
        sys_prompt = next(
            (prompt for prompt in PROMPT_OBJECTS if prompt.category == "sys" and prompt.name == user_sys_prompt),
            None,
        )
    except AttributeError as ex:
        # schema.Settings not on server-side
        logger.error("A settings exception occurred: %s", ex)
        raise HTTPException(status_code=500, detail="Unexpected Error.") from ex

    # Setup RAG
    embed_client, ctx_prompt, db_conn = None, None, None
    if client_settings.rag.rag_enabled or client_settings.selectai.selectai_enabled:
        db_conn = get_client_db(client).connection

        embed_client = await models.get_client(MODEL_OBJECTS, client_settings.rag.model_dump(), oci_config)

        user_ctx_prompt = getattr(client_settings.prompts, "ctx", "Basic Example")
        ctx_prompt = next(
            (prompt for prompt in PROMPT_OBJECTS if prompt.category == "ctx" and prompt.name == user_ctx_prompt),
            None,
        )
        db_conn = get_client_db(client).connection

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
                "rag_settings": client_settings.rag,
                "selectai_settings": client_settings.selectai,
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
        raise HTTPException(status_code=500, detail="Unexpected Error.") from ex
