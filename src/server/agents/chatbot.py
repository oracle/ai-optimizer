"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore litellm checkpointer acompletion astream

from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, START, END, MessagesState
from langchain_core.messages import AIMessage

from langchain_core.runnables import RunnableConfig
from litellm import acompletion

from common import logging_config

logger = logging_config.logging.getLogger("server.agents.chatbot")


class OptimizerState(MessagesState):
    """Establish our Agent State Machine"""

    final_response: dict  # OpenAI Response


#############################################################################
# Functions
#############################################################################
def get_messages(state: OptimizerState, config: RunnableConfig) -> list:
    """Return a list of messages that will be passed to the model for completion
    Filter out old VS documents to avoid blowing-out the context window
    Leave the state as is for GUI functionality"""
    use_history = config["metadata"]["use_history"]

    state_messages = state.get("messages", [])
    if state_messages:
        # If user decided for no history, only take the last message
        state_messages = state_messages if use_history else state_messages[-1:]

    prompt_messages = [{"role": "user", "content": m.content} for m in state_messages]

    return prompt_messages


#############################################################################
# NODES and EDGES
#############################################################################
async def stream_completion(state: OptimizerState, config: RunnableConfig | None = None):
    """LiteLLM streaming wrapper"""
    writer = get_stream_writer()
    full_response = []
    collected_content = []

    try:
        # Await the asynchronous completion with streaming enabled
        logger.info("Streaming completion...")
        prompt_messages = get_messages(state, config)

        # ll_raw holds either a dict(litellm) or an object(client)
        ll_raw = config["configurable"].get("ll_config", {})
        response = await acompletion(messages=prompt_messages, stream=True, **ll_raw)
        async for chunk in response:
            content = chunk.choices[0].delta.content
            if content is not None:
                writer({"stream": content})
                collected_content.append(content)
            full_response.append(chunk)

        # After loop: update last chunk to a full completion with usage details
        if full_response:
            last_chunk = full_response[-1]
            full_text = "".join(collected_content)
            last_chunk.object = "chat.completion"
            last_chunk.choices[0].message = {"role": "assistant", "content": full_text}
            delattr(last_chunk.choices[0], "delta")
            last_chunk.choices[0].finish_reason = "stop"
            final_response = last_chunk.model_dump()

            writer({"completion": final_response})
    except Exception as ex:
        logger.error(ex)
        full_text = f"I'm sorry, a completion problem occurred: {str(ex).split('Traceback', 1)[0]}"

    return {"messages": [AIMessage(content=full_text)]}


# Build the state graph
workflow = StateGraph(OptimizerState)
workflow.add_node("stream_completion", stream_completion)

workflow.add_edge(START, "stream_completion")
workflow.add_edge("stream_completion", END)

# Compile the graph
memory = MemorySaver()
chatbot_graph = workflow.compile(checkpointer=memory)
