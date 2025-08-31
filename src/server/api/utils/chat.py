"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore astream selectai

import time
from typing import Literal, AsyncGenerator

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

import server.api.core.settings as core_settings
import server.api.core.oci as core_oci
import server.api.core.prompts as core_prompts
import server.api.utils.models as util_models
import server.api.utils.databases as util_databases
from server.agents.chatbot import chatbot_graph
import server.api.utils.selectai as util_selectai

import common.schema as schema
import common.logging_config as logging_config

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

    oci_config = core_oci.get_oci(client=client)

    # Setup Client Model
    ll_config = util_models.get_litellm_config(model, oci_config)

    # Start to establish our LangGraph Args
    kwargs = {
        "stream_mode": "custom",
        "input": {"messages": [HumanMessage(content=request.messages[0].content)]},
        "config": RunnableConfig(
            configurable={"thread_id": client, "ll_config": ll_config},
            metadata={
                "use_history": client_settings.ll_model.chat_history,
                "vector_search": client_settings.vector_search,
                "selectai": client_settings.selectai,
            },
        ),
    }

    # Get System Prompt
    user_sys_prompt = getattr(client_settings.prompts, "sys", "Basic Example")
    kwargs["config"]["metadata"]["sys_prompt"] = core_prompts.get_prompts(category="sys", name=user_sys_prompt)

    # Setup Vector Search
    if client_settings.vector_search.enabled:
        kwargs["config"]["configurable"]["db_conn"] = util_databases.get_client_db(client, False).connection
        kwargs["config"]["configurable"]["embed_client"] = util_models.get_embed_client(
            client_settings.vector_search.model_dump(), oci_config
        )
        # Get Context Prompt
        user_ctx_prompt = getattr(client_settings.prompts, "ctx", "Basic Example")
        kwargs["config"]["metadata"]["ctx_prompt"] = core_prompts.get_prompts(category="ctx", name=user_ctx_prompt)

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

    # kwargs = {
    #     "stream_mode": "custom",
    #     "input": {"messages": [HumanMessage(content=request.messages[0].content)]},
    #     "config": RunnableConfig(
    #         configurable={
    #             "thread_id": client,
    #             "ll_config": ll_client,
    #             "embed_client": embed_client,
    #             "db_conn": db_conn,
    #         },
    #         metadata={
    #             "model_id": model["model"],
    #             "use_history": client_settings.ll_model.chat_history,
    #             "vector_search": client_settings.vector_search,
    #             "selectai": client_settings.selectai,
    #             "sys_prompt": sys_prompt,
    #             "ctx_prompt": ctx_prompt,
    #         },
    #     ),
    # }
    logger.debug("Completion Kwargs: %s", kwargs)
    final_response = None
    async for output in chatbot_graph.astream(**kwargs):
        if "stream" in output:
            yield output["stream"].encode("utf-8")
        if "completion" in output:
            final_response = output["completion"]
    if call == "streams":
        yield "[stream_finished]"  # This will break the Chatbot loop
    if call == "completions" and final_response is not None:
        yield final_response  # This will be captured for ChatResponse

        # print(f"********** output: {output["stream"][]}")
        # for chunk in output["llm"]["messages"]:
        #     print(f"********** chunk: {chunk}")
        #     print(f"********** yield: {chunk.content}")
        #     yield chunk.content.encode("utf-8")

    # result = await graph.ainvoke(**kwargs)
    # print("\n\nFinal result:", result)

    # try:
    #     async for chunk in agent.astream_events(**kwargs, version="v2", stream=True):
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
