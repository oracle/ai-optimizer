"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# spell-checker:ignore astream selectai litellm
from typing import Literal, AsyncGenerator

from litellm import completion
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

import server.api.core.settings as core_settings
import server.api.core.oci as core_oci
import server.api.core.prompts as core_prompts
import server.api.utils.models as utils_models
import server.api.utils.databases as utils_databases
import server.api.utils.selectai as utils_selectai

from server.agents.chatbot import chatbot_graph

from server.api.core.models import UnknownModelError

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

    oci_config = core_oci.get_oci(client=client)

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

    # Add DB Conn to KWargs when needed
    if client_settings.vector_search.enabled or client_settings.selectai.enabled:
        db_conn = utils_databases.get_client_db(client, False).connection
        kwargs["config"]["configurable"]["db_conn"] = db_conn

    # Setup Vector Search
    if client_settings.vector_search.enabled:
        kwargs["config"]["configurable"]["embed_client"] = utils_models.get_client_embed(
            client_settings.vector_search.model_dump(), oci_config
        )
        # Get Context Prompt
        user_ctx_prompt = getattr(client_settings.prompts, "ctx", "Basic Example")
        kwargs["config"]["metadata"]["ctx_prompt"] = core_prompts.get_prompts(category="ctx", name=user_ctx_prompt)

    if client_settings.selectai.enabled:
        utils_selectai.set_profile(db_conn, client_settings.selectai.profile, "temperature", model["temperature"])
        utils_selectai.set_profile(
            db_conn, client_settings.selectai.profile, "max_tokens", model["max_completion_tokens"]
        )

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
