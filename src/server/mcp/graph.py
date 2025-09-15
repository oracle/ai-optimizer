"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore acompletion checkpointer litellm

import copy

from langchain_core.messages import SystemMessage, ToolMessage, AIMessage
from langchain_core.messages.utils import convert_to_openai_messages
from langchain_core.runnables import RunnableConfig

from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode


from litellm import acompletion
from litellm.exceptions import APIConnectionError

from launch_server import graph_memory

from  common import logging_config

logger = logging_config.logging.getLogger("mcp.graph")


#############################################################################
# Graph State
#############################################################################
class OptimizerState(MessagesState):
    """Establish our Agent State Machine"""

    cleaned_messages: list  # Messages w/o VS Results
    final_response: dict  # OpenAI Response


#############################################################################
# Functions
#############################################################################
def clean_messages(state: OptimizerState, config: RunnableConfig) -> list:
    """Return a list of messages that will be passed to the model for completion
    Filter out old VS documents to avoid blowing-out the context window
    Leave the state as is (deepcopy) for GUI functionality"""

    use_history = config["metadata"]["use_history"]

    state_messages = copy.deepcopy(state.get("messages", []))
    if state_messages:
        # If user decided for no history, only take the last message
        state_messages = state_messages if use_history else state_messages[-1:]

        # Remove System Prompt from top
        if isinstance(state_messages[0], SystemMessage):
            state_messages.pop(0)

        # Remove ToolCalls
        state_messages = [msg for msg in state_messages if not isinstance(msg, ToolMessage)]

    return state_messages


def should_continue(state: OptimizerState):
    """Determine if graph should continue to tools"""
    messages = state["messages"]
    if messages and messages[-1].tool_calls:
        return "tools"
    return END


#############################################################################
# NODES and EDGES
#############################################################################
async def initialise(state: OptimizerState, config: RunnableConfig) -> OptimizerState:
    """Get messages from state based on Thread ID"""
    logger.debug("Initializing OptimizerState")
    cleaned_messages = clean_messages(state, config)

    return {"cleaned_messages": cleaned_messages}


async def stream_completion(state: OptimizerState, config: RunnableConfig) -> OptimizerState:
    """LiteLLM streaming wrapper"""
    writer = get_stream_writer()
    full_response = []
    collected_content = []

    messages = state["cleaned_messages"]
    try:
        # Get our Prompt
        sys_prompt = config.get("metadata", {}).get("sys_prompt")
        if state.get("context_input") and state.get("documents"):
            documents = state["documents"]
            new_prompt = SystemMessage(content=f"{sys_prompt.prompt}\n {documents}")
        else:
            new_prompt = SystemMessage(content=f"{sys_prompt.prompt}")

        # Insert Prompt into cleaned_messages
        messages.insert(0, new_prompt)
        # Await the asynchronous completion with streaming enabled
        logger.info("Streaming completion...")
        ll_raw = config["configurable"]["ll_config"]
        response = await acompletion(messages=convert_to_openai_messages(messages), stream=True, **ll_raw)
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
    except APIConnectionError as ex:
        logger.error(ex)
        full_text = "I'm not able to contact the model API; please validate its configuration/availability."
    except Exception as ex:
        logger.error(ex)
        full_text = f"I'm sorry, an unknown completion problem occurred: {str(ex).split('Traceback', 1)[0]}"
    return {"messages": [AIMessage(content=full_text)]}


# #############################################################################
# # GRAPH
# #############################################################################
def main(tools: list):
    """Define the graph with MCP tool nodes"""
    # Build the graph
    workflow = StateGraph(OptimizerState)

    # Define the nodes
    workflow.add_node("initialise", initialise)
    workflow.add_node("stream_completion", stream_completion)
    workflow.add_node("tools", ToolNode(tools))

    # Add Edges
    workflow.add_edge(START, "initialise")
    workflow.add_edge("initialise", "stream_completion")
    workflow.add_conditional_edges(
        "stream_completion",
        should_continue,
    )
    workflow.add_edge("tools", "stream_completion")
    workflow.add_edge("stream_completion", END)

    # Compile the graph and return it
    mcp_graph = workflow.compile(checkpointer=graph_memory)
    logger.debug("Chatbot Graph Built with tools: %s", tools)
    ## This will output the Graph in ascii; don't deliver uncommented
    # mcp_graph.get_graph(xray=True).print_ascii()

    return mcp_graph


if __name__ == "__main__":
    main([])
