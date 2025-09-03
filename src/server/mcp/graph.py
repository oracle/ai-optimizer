"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore ainvoke checkpointer

from datetime import datetime, timezone

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from common.schema import ChatResponse, ChatUsage, ChatChoices, ChatMessage
from launch_server import graph_memory

import common.logging_config as logging_config

logger = logging_config.logging.getLogger("mcp.graph")


#############################################################################
# AGENT STATE
#############################################################################
class OptimizerState(MessagesState):
    """Establish our Agent State Machine"""

    final_response: ChatResponse  # OpenAI Response
    cleaned_messages: list  # Messages w/o VS Results


#############################################################################
# NODES and EDGES
#############################################################################
def respond(state: OptimizerState, config: RunnableConfig) -> ChatResponse:
    """Respond in OpenAI Compatible return"""
    ai_message = state["messages"][-1]
    logger.debug("Formatting to OpenAI compatible response: %s", repr(ai_message))
    if "model_name" in ai_message.response_metadata:
        model_id = ai_message.response_metadata["model_name"]
        ai_metadata = ai_message
    else:
        logger.debug("Using Metadata from: %s", repr(ai_metadata))
        model_id = config["metadata"]["ll_model"]
        ai_metadata = state["messages"][1]

    finish_reason = ai_metadata.response_metadata.get("finish_reason", "stop")
    if finish_reason == "COMPLETE":
        finish_reason = "stop"
    elif finish_reason == "MAX_TOKENS":
        finish_reason = "length"

    openai_response = ChatResponse(
        id=ai_message.id,
        created=int(datetime.now(timezone.utc).timestamp()),
        model=model_id,
        usage=ChatUsage(
            prompt_tokens=ai_metadata.response_metadata.get("token_usage", {}).get("prompt_tokens", -1),
            completion_tokens=ai_metadata.response_metadata.get("token_usage", {}).get("completion_tokens", -1),
            total_tokens=ai_metadata.response_metadata.get("token_usage", {}).get("total_tokens", -1),
        ),
        choices=[
            ChatChoices(
                index=0,
                message=ChatMessage(
                    role="ai",
                    content=ai_message.content,
                    additional_kwargs=ai_metadata.additional_kwargs,
                    response_metadata=ai_metadata.response_metadata,
                ),
                finish_reason=finish_reason,
                logprobs=None,
            )
        ],
    )
    return {"final_response": openai_response}


async def client(state: OptimizerState, config: RunnableConfig) -> OptimizerState:
    """Get messages from state based on Thread ID"""
    logger.debug("Initializing OptimizerState")
    messages = get_messages(state, config)

    return {"cleaned_messages": messages}


#############################################################################
def get_messages(state: OptimizerState, config: RunnableConfig) -> list:
    """Return a list of messages that will be passed to the model for completion
    Leave the state as is for GUI functionality"""
    use_history = config["metadata"]["use_history"]

    # If user decided for no history, only take the last message
    state_messages = state["messages"] if use_history else state["messages"][-1:]

    messages = []
    for msg in state_messages:
        if isinstance(msg, SystemMessage):
            continue
        if isinstance(msg, ToolMessage):
            if messages:  # Check if there are any messages in the list
                messages.pop()  # Remove the last appended message
            continue
        messages.append(msg)

    # # insert the system prompt; remaining messages cleaned
    # if config["metadata"]["sys_prompt"].prompt:
    #     messages.insert(0, SystemMessage(content=config["metadata"]["sys_prompt"].prompt))

    return messages


def should_continue(state: OptimizerState):
    """Determine if graph should continue to tools"""
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return END


# Define call_model function
async def call_model(state: OptimizerState, config: RunnableConfig):
    """Invoke the model"""
    try:
        model = config["configurable"].get("ll_model", None)
        messages = state["messages"]
        response = await model.ainvoke(messages)
        return {"messages": [response]}
    except AttributeError as ex:
        # The model is not in our RunnableConfig
        return {"messages": [f"I'm sorry; {ex}"]}


# #############################################################################
# # GRAPH
# #############################################################################
def main(tools: list):
    """Define the graph with MCP tool nodes"""
    # Build the graph
    workflow = StateGraph(OptimizerState)

    # Define the nodes
    workflow.add_node("client", client)
    workflow.add_node("call_model", call_model)
    workflow.add_node("tools", ToolNode(tools))
    workflow.add_node("respond", respond)

    # Add Edges
    workflow.add_edge(START, "client")
    workflow.add_edge("client", "call_model")
    workflow.add_conditional_edges(
        "call_model",
        should_continue,
    )
    workflow.add_edge("tools", "call_model")
    workflow.add_edge("call_model", "respond")
    workflow.add_edge("respond", END)

    # Compile the graph and return it
    mcp_graph = workflow.compile(checkpointer=graph_memory)
    logger.debug("Chatbot Graph Built with tools: %s", tools)
    ## This will output the Graph in ascii; don't deliver uncommented
    # mcp_graph.get_graph(xray=True).print_ascii()

    return mcp_graph


if __name__ == "__main__":
    main(list())
