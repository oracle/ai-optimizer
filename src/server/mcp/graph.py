"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore acompletion checkpointer litellm ainvoke

import copy
import json

from langchain_core.messages import SystemMessage, ToolMessage, AIMessage, HumanMessage
from langchain_core.messages.utils import convert_to_openai_messages
from langchain_core.runnables import RunnableConfig

from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, MessagesState, START, END

from litellm import acompletion
from litellm.exceptions import APIConnectionError

from launch_server import graph_memory

from common import logging_config

logger = logging_config.logging.getLogger("mcp.graph")


def _parse_tool_arguments(arguments: str) -> dict:
    """Parse tool call arguments from string to dict"""
    if not arguments or not isinstance(arguments, str):
        return {}

    try:
        parsed = json.loads(arguments)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.error("Failed to parse tool call arguments: %s", arguments)
        return {}


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
    Filter out old VS documents to avoid blowing-out the context window (#TODO)
    Leave the state as is (deepcopy) for GUI functionality"""

    use_history = config["metadata"]["use_history"]

    state_messages = copy.deepcopy(state.get("messages", []))
    if state_messages:
        # If user decided for no history, only take the last HumanMessage
        if not use_history:
            last_human = next(
                (m for m in reversed(state_messages) if isinstance(m, HumanMessage)),
                None,
            )
            state_messages = [last_human] if last_human else []

        # Remove System Prompt from top if it exists
        if state_messages and isinstance(state_messages[0], SystemMessage):
            state_messages.pop(0)

    return state_messages


def should_continue(state: OptimizerState):
    """Determine if graph should continue to tools"""
    messages = state["messages"]

    if not messages or not hasattr(messages[-1], "tool_calls") or not messages[-1].tool_calls:
        return END

    # Get tool call IDs that need responses
    tool_call_ids = {tc.get("id") for tc in messages[-1].tool_calls if tc.get("id")}

    # Get tool call IDs that already have responses
    responded_tool_ids = {
        msg.tool_call_id for msg in messages if isinstance(msg, ToolMessage) and hasattr(msg, "tool_call_id")
    }

    # Continue to tools if there are unprocessed tool calls
    return "tools" if tool_call_ids - responded_tool_ids else END


#############################################################################
# NODES and EDGES
#############################################################################
def custom_tool_node(tools):
    """Custom tool node that injects Optimizer configurations"""

    async def tool_node(state: OptimizerState, config: RunnableConfig):
        """Custom tool node that injects Optimizer configurations into tool calls"""
        messages = state["messages"]
        last_message = messages[-1]

        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            return {"messages": []}

        # Get thread_id from config
        thread_id = config["configurable"]["thread_id"]
        logger.info("Thread ID from config: %s", thread_id)  # Add this line

        # Create a mapping of tool names to tool objects
        tool_map = {tool.name: tool for tool in tools}

        # Execute tools and collect responses
        tool_responses = []

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"].copy()  # Copy to avoid modifying original
            tool_id = tool_call["id"]

            # Inject thread_id into args for native Optimizer tools (not proxies)
            if tool_name.startswith("optimizer_"):
                tool_args = {**tool_args, "thread_id": thread_id}

            try:
                if tool_name in tool_map:
                    # Execute the actual tool
                    tool = tool_map[tool_name]
                    result = await tool.ainvoke(tool_args) if hasattr(tool, "ainvoke") else tool.invoke(tool_args)

                    # Convert result to string if it's not already
                    if isinstance(result, dict):
                        result = json.dumps(result, indent=2)
                    elif not isinstance(result, str):
                        result = str(result)
                else:
                    logger.error(
                        "Tool '%s' not found in tool_map. Available tools: %s", tool_name, list(tool_map.keys())
                    )
                    result = (
                        f"Error: Tool '{tool_name}' is not available; it was not properly registered in the graph."
                    )

                tool_responses.append(ToolMessage(content=result, tool_call_id=tool_id, name=tool_name))
            except Exception as ex:
                logger.error("Tool execution failed for %s: %s", tool_name, ex)
                tool_responses.append(
                    ToolMessage(
                        content=f"Error executing {tool_name}: {str(ex)}", tool_call_id=tool_id, name=tool_name
                    )
                )

        return {"messages": tool_responses}

    return tool_node


async def initialise(state: OptimizerState, config: RunnableConfig) -> OptimizerState:
    """Get messages from state based on Thread ID"""
    logger.debug("Initializing OptimizerState")
    cleaned_messages = clean_messages(state, config)

    return {"cleaned_messages": cleaned_messages}


def _prepare_messages(state: OptimizerState, config: RunnableConfig) -> list:
    """Prepare messages with system prompt

    Uses state['messages'] which includes all messages including tool responses,
    rather than state['cleaned_messages'] which is only set once at initialization.
    """
    messages = list(state["messages"])  # Make a copy to avoid modifying state
    sys_prompt = config.get("metadata", {}).get("sys_prompt")

    # Remove any existing SystemMessages to avoid duplicates
    messages = [m for m in messages if not isinstance(m, SystemMessage)]

    if state.get("context_input") and state.get("documents"):
        documents = state["documents"]
        new_prompt = SystemMessage(content=f"{sys_prompt.prompt}\n {documents}")
    else:
        new_prompt = SystemMessage(content=f"{sys_prompt.prompt}")

    messages.insert(0, new_prompt)
    logger.info("Sending Messages: %s", messages)
    return messages


async def _accumulate_tool_calls(chunk, response):
    """Accumulate tool call deltas until complete"""
    accumulated_tool_calls = {}
    choice = chunk.choices[0].delta

    # Process initial chunk
    for tool_call_delta in choice.tool_calls or []:
        index = tool_call_delta.index
        accumulated_tool_calls[index] = {
            "id": getattr(tool_call_delta, "id", "") or "",
            "name": getattr(tool_call_delta.function, "name", "") or "",
            "arguments": getattr(tool_call_delta.function, "arguments", "") or "",
        }

    # Continue accumulating until complete
    while chunk.choices[0].finish_reason != "tool_calls":
        chunk = await anext(response)
        choice = chunk.choices[0].delta

        for tool_call_delta in choice.tool_calls or []:
            index = tool_call_delta.index
            if index in accumulated_tool_calls:
                if hasattr(tool_call_delta, "id") and tool_call_delta.id:
                    accumulated_tool_calls[index]["id"] = tool_call_delta.id
                if hasattr(tool_call_delta.function, "name") and tool_call_delta.function.name:
                    accumulated_tool_calls[index]["name"] = tool_call_delta.function.name
                if hasattr(tool_call_delta.function, "arguments") and tool_call_delta.function.arguments:
                    accumulated_tool_calls[index]["arguments"] += tool_call_delta.function.arguments

    # Build complete tool calls
    tool_calls = [
        {
            "name": data["name"],
            "args": _parse_tool_arguments(data["arguments"]) or {},
            "id": data["id"],
            "type": "tool_call",
        }
        for data in accumulated_tool_calls.values()
    ]
    return tool_calls


def _build_final_response(full_response: list, collected_content: list):
    """Build final response from accumulated chunks"""
    last_chunk = full_response[-1]
    full_text = "".join(collected_content)
    last_chunk.object = "chat.completion"
    last_chunk.choices[0].message = {"role": "assistant", "content": full_text}
    delattr(last_chunk.choices[0], "delta")
    last_chunk.choices[0].finish_reason = "stop"
    return last_chunk.model_dump()


async def stream_completion(state: OptimizerState, config: RunnableConfig) -> OptimizerState:
    """LiteLLM streaming wrapper"""
    writer = get_stream_writer()
    full_response = []
    collected_content = []

    try:
        # Prepare messages with system prompt
        messages = _prepare_messages(state, config)

        # Get LLM config and tools
        ll_raw = config["configurable"]["ll_config"]
        tools = config["metadata"].get("tools", [])

        logger.info("Streaming completion...")
        logger.info("Tools being sent: %s", tools)
        logger.info("Model: %s", ll_raw.get("model", ""))

        # Start streaming completion
        try:
            response = await acompletion(
                messages=convert_to_openai_messages(messages), stream=True, **ll_raw, tools=tools
            )
        except Exception as ex:
            logger.error("Error during completion: %s", ex)
            raise ex

        # Process streaming response
        async for chunk in response:
            logger.info("Stream Response: %s", response)
            logger.info("Stream Chunk: %s", chunk)
            choice = chunk.choices[0].delta

            # Check for immediate empty response
            if chunk.choices[0].finish_reason == "stop" and choice.content is None and not collected_content:
                logger.info("Stream finished immediately without content")
                return {"messages": [AIMessage(content="I'm sorry, I was unable to produce a response.")]}

            # Handle tool call streaming
            if choice.tool_calls:
                logger.info("Tool call detected, accumulating chunks...")
                tool_calls = await _accumulate_tool_calls(chunk, response)
                return {"messages": [AIMessage(content="", tool_calls=tool_calls)]}

            # Handle content streaming
            if choice.content is not None:
                writer({"stream": choice.content})
                collected_content.append(choice.content)

            full_response.append(chunk)

        # Build and send final response
        if full_response:
            final_response = _build_final_response(full_response, collected_content)
            writer({"completion": final_response})
            full_text = "".join(collected_content)
        else:
            full_text = ""

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
    workflow.add_node("tools", custom_tool_node(tools))

    # Add Edges
    workflow.add_edge(START, "initialise")
    workflow.add_edge("initialise", "stream_completion")
    workflow.add_conditional_edges(
        "stream_completion",
        should_continue,
    )
    workflow.add_edge("tools", "stream_completion")

    # Compile the graph and return it
    mcp_graph = workflow.compile(checkpointer=graph_memory)
    logger.debug("Chatbot Graph Built with tools: %s", tools)
    ## This will output the Graph in ascii; don't deliver uncommented
    # mcp_graph.get_graph(xray=True).print_ascii()

    return mcp_graph


if __name__ == "__main__":
    main([])
