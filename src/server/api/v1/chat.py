"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore litellm

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from litellm import ModelResponse

from langchain_core.messages import (
    AnyMessage,
    convert_to_openai_messages,
    ChatMessage,
    RemoveMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES

import server.api.utils.chat as utils_chat
from server.mcp import graph

from common import schema, logging_config

logger = logging_config.logging.getLogger("endpoints.v1.chat")

auth = APIRouter()


@auth.post(
    "/completions",
    description="Submit a message for full completion.",
    response_model=ModelResponse,
)
async def chat_post(
    request: schema.ChatRequest, client: schema.ClientIdType = Header(default="server")
) -> ModelResponse:
    """Full Completion Requests"""
    last_message = None
    async for chunk in utils_chat.completion_generator(client, request, "completions"):
        last_message = chunk
    return last_message


@auth.post(
    "/streams",
    description="Submit a message for streamed completion.",
    response_class=StreamingResponse,
    include_in_schema=False,
)
async def chat_stream(
    request: schema.ChatRequest, client: schema.ClientIdType = Header(default="server")
) -> StreamingResponse:
    """Completion Requests"""
    return StreamingResponse(
        utils_chat.completion_generator(client, request, "streams"),
        media_type="application/octet-stream",
    )


@auth.patch(
    "/history",
    description="Delete Chat History",
    response_model=list[schema.ChatMessage],
)
async def chat_history_clean(client: schema.ClientIdType = Header(default="server")) -> list[ChatMessage]:
    """Delete all Chat History"""
    agent: CompiledStateGraph = graph.main(tools=[])

    try:
        _ = agent.update_state(
            config=RunnableConfig(
                configurable={
                    "thread_id": client,
                }
            ),
            values={
                "messages": RemoveMessage(id=REMOVE_ALL_MESSAGES),
                "cleaned_messages": [],
                "context_input": "",
                "documents": {},
                "final_response": {},
            },
        )
        return [ChatMessage(content="As requested, I've forgotten our conversation.", role="system")]
    except KeyError:
        return [ChatMessage(content="I'm sorry, I have no history of this conversation.", role="system")]


@auth.get(
    "/history",
    description="Get Chat History",
    response_model=list[schema.ChatMessage],
)
async def chat_history_return(client: schema.ClientIdType = Header(default="server")) -> list[ChatMessage]:
    """Return Chat History"""
    agent: CompiledStateGraph = graph.main(tools=[])

    try:
        state_snapshot = agent.get_state(
            config=RunnableConfig(
                configurable={
                    "thread_id": client,
                }
            )
        )
        messages: list[AnyMessage] = state_snapshot.values["messages"]

        # Convert to OpenAI format while preserving response_metadata
        chat_messages = []
        for msg in messages:
            openai_msg = convert_to_openai_messages([msg])[0]
            # Preserve response_metadata if present
            if hasattr(msg, "response_metadata") and msg.response_metadata:
                openai_msg["response_metadata"] = msg.response_metadata
            chat_messages.append(openai_msg)

        return chat_messages
    except KeyError:
        return [ChatMessage(content="I'm sorry, I have no history of this conversation.", role="system")]
