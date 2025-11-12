"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore acompletion checkpointer litellm ainvoke

import copy
import decimal
import json
from typing import Literal

from langchain_core.messages import SystemMessage, ToolMessage, AIMessage, HumanMessage
from langchain_core.messages.utils import convert_to_openai_messages
from langchain_core.runnables import RunnableConfig

from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.checkpoint.memory import InMemorySaver

from litellm import acompletion
from litellm.exceptions import APIConnectionError

from common import logging_config

# Import VS tool implementation functions for internal orchestration
from server.mcp.tools.vs_retriever import _vs_retrieve_impl
from server.mcp.tools.vs_grading import _vs_grade_impl
from server.mcp.tools.vs_rephrase import _vs_rephrase_impl

logger = logging_config.logging.getLogger("mcp.graph")


#############################################################################
# JSON Encoder for Oracle Decimal types
#############################################################################
class DecimalEncoder(json.JSONEncoder):
    """Used with json.dumps to encode decimals from Oracle database"""

    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return str(o)
        return super().default(o)


#############################################################################
# Error Handling
#############################################################################
def _create_error_message(exception: Exception, context: str = "") -> AIMessage:
    """Create user-friendly error wrapper around actual exception message"""
    logger.exception("Error %s", context if context else "in graph execution")

    # Extract just the error message, excluding any embedded tracebacks
    error_str = str(exception)

    # If error contains "Traceback", extract only the part before it
    if "Traceback (most recent call last):" in error_str:
        error_str = error_str.split("Traceback (most recent call last):", maxsplit=1)[0].strip()

    # Take only the first line if multi-line (avoids showing pydantic URLs, etc.)
    error_lines = [line.strip() for line in error_str.split("\n") if line.strip()]
    error_msg = error_lines[0] if error_lines else str(type(exception).__name__)

    error_text = "I'm sorry, I've run into a problem"
    if context:
        error_text += f" {context}"
    error_text += f": {error_msg}"
    error_text += "\n\nPlease raise an issue at: https://github.com/oracle/ai-optimizer/issues"

    return AIMessage(content=error_text)


# LangGraph Short-Term Memory (thread-level persistence)
graph_memory = InMemorySaver()


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
# Helper Functions
#############################################################################
def _remove_system_prompt(messages: list) -> list:
    """Remove SystemMessage from start of message list if present

    System prompts are managed by the graph and injected dynamically,
    so we remove any existing system prompts to avoid duplication.
    """
    if messages and isinstance(messages[0], SystemMessage):
        messages.pop(0)
    return messages


#############################################################################
# Graph State
#############################################################################
class OptimizerState(MessagesState):
    """Establish our Agent State Machine"""

    cleaned_messages: list  # Messages w/o VS Results
    context_input: str = ""  # Rephrased query used for retrieval (NEW for VS)
    documents: str = ""  # Retrieved documents formatted as string (NEW for VS)
    final_response: dict  # OpenAI Response


#############################################################################
# Functions
#############################################################################


def clean_messages(state: OptimizerState, config: RunnableConfig) -> list:
    """Return a list of messages that will be passed to the model for completion.
    Filters ToolMessages marked as internal VS processing to prevent context bloat.
    Preserves external tool ToolMessages as they're needed for context.
    Uses metadata-based filtering: vs_orchestrate marks what it creates."""

    use_history = config["metadata"]["use_history"]

    state_messages = copy.deepcopy(state.get("messages", []))
    if state_messages:
        if not use_history:
            last_human = next(
                (m for m in reversed(state_messages) if isinstance(m, HumanMessage)),
                None,
            )
            state_messages = [last_human] if last_human else []

        state_messages = _remove_system_prompt(state_messages)

        state_messages = [
            msg
            for msg in state_messages
            if not (isinstance(msg, ToolMessage) and msg.additional_kwargs.get("internal_vs", False))
        ]

    return state_messages


def should_continue(state: OptimizerState) -> Literal["vs_orchestrate", "tools", END]:
    """Determine if graph should continue to VS orchestration, standard tools, or end

    Implements dual-path routing:
    - VS tools (optimizer_vs-*) → "vs_orchestrate" (internal pipeline, state storage)
    - External tools → "tools" (standard execution, ToolMessages in history)
    - No tools or all responded → END
    """
    messages = state["messages"]

    if not messages or not hasattr(messages[-1], "tool_calls") or not messages[-1].tool_calls:
        return END

    # Extract tool call IDs with validation
    tool_call_ids = {tc.get("id") for tc in messages[-1].tool_calls if isinstance(tc, dict) and tc.get("id")}
    responded_tool_ids = {
        msg.tool_call_id for msg in messages if isinstance(msg, ToolMessage) and hasattr(msg, "tool_call_id")
    }

    if not tool_call_ids - responded_tool_ids:
        return END

    # Extract tool names with validation
    tool_names = {tc.get("name") for tc in messages[-1].tool_calls if isinstance(tc, dict) and tc.get("name")}
    vs_tools = {"optimizer_vs-retriever", "optimizer_vs-rephrase", "optimizer_vs-grading"}

    # Route to VS orchestration if any VS tool called
    if tool_names & vs_tools:
        logger.info("Routing to vs_orchestrate for VS tools: %s", tool_names & vs_tools)
        return "vs_orchestrate"

    # Otherwise route to standard tool execution
    logger.info("Routing to standard tools node for: %s", tool_names)
    return "tools"


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

        thread_id = config["configurable"]["thread_id"]
        tool_map = {tool.name: tool for tool in tools}
        tool_responses = []

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"].copy()
            tool_id = tool_call["id"]

            if tool_name.startswith("optimizer_"):
                tool_args = {**tool_args, "thread_id": thread_id}

            try:
                if tool_name in tool_map:
                    tool = tool_map[tool_name]
                    result = await tool.ainvoke(tool_args) if hasattr(tool, "ainvoke") else tool.invoke(tool_args)

                    if isinstance(result, dict):
                        result = json.dumps(result, indent=2)
                    elif not isinstance(result, str):
                        result = str(result)
                else:
                    result = f"Unknown tool: {tool_name}"

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


def _prepare_messages_for_completion(state: OptimizerState, config: RunnableConfig) -> list:
    """Prepare messages for LLM completion, including system prompt and optional documents"""
    if state.get("messages") and any(isinstance(msg, ToolMessage) for msg in state["messages"]):
        messages = copy.deepcopy(state["messages"])
        messages = _remove_system_prompt(messages)
    else:
        messages = state["cleaned_messages"]

    sys_prompt = config.get("metadata", {}).get("sys_prompt")
    if state.get("documents") and state.get("documents") != "":
        documents = state["documents"]
        new_prompt = SystemMessage(content=f"{sys_prompt.content.text}\n\nRelevant Context:\n{documents}")
        logger.info("Injecting %d chars of documents into system prompt", len(documents))
    else:
        new_prompt = SystemMessage(content=f"{sys_prompt.content.text}")

    messages.insert(0, new_prompt)
    logger.info("Sending Messages: %s", messages)
    return messages


async def _accumulate_tool_calls(response, initial_chunk, initial_choice):
    """Accumulate streaming tool call chunks until complete"""
    accumulated_tool_calls = {}

    for tool_call_delta in initial_choice.tool_calls:
        index = tool_call_delta.index
        accumulated_tool_calls[index] = {
            "id": getattr(tool_call_delta, "id", "") or "",
            "name": getattr(tool_call_delta.function, "name", "") or "",
            "arguments": getattr(tool_call_delta.function, "arguments", "") or "",
        }

    chunk = initial_chunk
    while chunk.choices[0].finish_reason != "tool_calls":
        chunk = await anext(response)
        choice = chunk.choices[0].delta

        if choice.tool_calls:
            for tool_call_delta in choice.tool_calls:
                index = tool_call_delta.index
                if index in accumulated_tool_calls:
                    if hasattr(tool_call_delta, "id") and tool_call_delta.id:
                        accumulated_tool_calls[index]["id"] = tool_call_delta.id
                    if hasattr(tool_call_delta.function, "name") and tool_call_delta.function.name:
                        accumulated_tool_calls[index]["name"] = tool_call_delta.function.name
                    if hasattr(tool_call_delta.function, "arguments") and tool_call_delta.function.arguments:
                        accumulated_tool_calls[index]["arguments"] += tool_call_delta.function.arguments

    return [
        {
            "name": data["name"],
            "args": _parse_tool_arguments(data["arguments"]) or {},
            "id": data["id"],
            "type": "tool_call",
        }
        for data in accumulated_tool_calls.values()
    ]


async def initialise(state: OptimizerState, config: RunnableConfig) -> OptimizerState:
    """Initialize cleaned messages"""
    return {"cleaned_messages": clean_messages(state, config)}


async def stream_completion(state: OptimizerState, config: RunnableConfig) -> OptimizerState:
    """LiteLLM streaming wrapper"""
    writer = get_stream_writer()
    full_response = []
    collected_content = []

    messages = _prepare_messages_for_completion(state, config)

    try:
        ll_raw = config["configurable"]["ll_config"]
        tools = config["metadata"].get("tools", [])

        logger.info("Streaming completion...")
        logger.info("Tools being sent: %s", tools)
        logger.info("Model: %s", ll_raw.get("model", ""))

        try:
            response = await acompletion(
                messages=convert_to_openai_messages(messages), stream=True, **ll_raw, tools=tools
            )
        except Exception as ex:
            logger.exception("Error calling LLM API")
            raise ex

        async for chunk in response:
            choice = chunk.choices[0].delta

            if chunk.choices[0].finish_reason == "stop" and choice.content is None and not collected_content:
                return {"messages": [AIMessage(content="I'm sorry, I was unable to produce a response.")]}

            if choice.tool_calls:
                tool_calls = await _accumulate_tool_calls(response, chunk, choice)
                return {"messages": [AIMessage(content="", tool_calls=tool_calls)]}

            if choice.content is not None:
                writer({"stream": choice.content})
                collected_content.append(choice.content)

            full_response.append(chunk)

        if full_response:
            last_chunk = full_response[-1]
            full_text = "".join(collected_content)
            last_chunk.object = "chat.completion"
            last_chunk.choices[0].message = {"role": "assistant", "content": full_text}
            delattr(last_chunk.choices[0], "delta")
            last_chunk.choices[0].finish_reason = "stop"
            final_response = last_chunk.model_dump()
            logger.info("Final completion response: %s", final_response)

            writer({"completion": final_response})
    except APIConnectionError as ex:
        error_msg = _create_error_message(ex, "connecting to LLM API")
        return {"messages": [error_msg]}
    except Exception as ex:
        error_msg = _create_error_message(ex, "generating completion")
        return {"messages": [error_msg]}
    return {"messages": [AIMessage(content=full_text)]}


async def _vs_step_rephrase(thread_id: str, question: str, chat_history: list, use_history: bool) -> str:
    """Execute rephrase step of VS pipeline

    Returns rephrased question, or original question if rephrasing fails/disabled
    """
    if not use_history or len(chat_history) <= 2:
        logger.info("Skipping rephrase (history disabled or insufficient)")
        return question

    logger.info("Rephrasing question with chat history (%d messages)", len(chat_history))
    try:
        rephrase_result = await _vs_rephrase_impl(
            thread_id=thread_id,
            question=question,
            chat_history=chat_history,
            mcp_client="Optimizer-Internal",
            model="graph-orchestrated",
        )

        if rephrase_result.status == "success" and rephrase_result.was_rephrased:
            logger.info("Question rephrased: '%s' -> '%s'", question, rephrase_result.rephrased_prompt)
            return rephrase_result.rephrased_prompt

        logger.info("Question not rephrased (status: %s)", rephrase_result.status)
        return question
    except Exception as ex:
        logger.error("Rephrase failed: %s (using original question)", ex)
        return question


def _vs_step_retrieve(thread_id: str, rephrased_question: str):
    """Execute retrieve step of VS pipeline

    Returns retrieval result, or None if retrieval fails
    """
    logger.info("Retrieving documents for: %s", rephrased_question)
    try:
        retrieval_result = _vs_retrieve_impl(
            thread_id=thread_id,
            question=rephrased_question,
            mcp_client="Optimizer-Internal",
            model="graph-orchestrated",
        )

        if retrieval_result.status != "success":
            logger.error("Retrieval failed: %s", retrieval_result.error)
            return None

        logger.info(
            "Retrieved %d documents from tables: %s",
            retrieval_result.num_documents,
            retrieval_result.searched_tables,
        )
        return retrieval_result
    except Exception as ex:
        logger.error("Retrieval exception: %s", ex)
        return None


async def _vs_step_grade(thread_id: str, question: str, documents: list, rephrased_question: str) -> dict:
    """Execute grade step of VS pipeline

    Returns dict with context_input and documents if relevant, empty dict otherwise
    """
    logger.info("Grading %d documents for relevance", len(documents))
    try:
        grading_result = await _vs_grade_impl(
            thread_id=thread_id,
            question=question,
            documents=documents,
            mcp_client="Optimizer-Internal",
            model="graph-orchestrated",
        )

        if grading_result.status != "success":
            logger.error("Grading failed: %s (defaulting to relevant)", grading_result.error)
            return {
                "context_input": rephrased_question,
                "documents": grading_result.formatted_documents,
            }

        logger.info(
            "Grading result: %s (grading_enabled: %s)",
            grading_result.relevant,
            grading_result.grading_enabled,
        )

        if grading_result.relevant == "yes":
            logger.info("Documents deemed relevant - storing in state")
            return {
                "context_input": rephrased_question,
                "documents": grading_result.formatted_documents,
            }

        logger.info("Documents deemed NOT relevant - transparent completion (no VS context)")
        return {"context_input": "", "documents": ""}
    except Exception as ex:
        logger.error("Grading exception: %s (defaulting to not relevant)", ex)
        return {"context_input": "", "documents": ""}


def _validate_vs_config(config: RunnableConfig) -> tuple[str, AIMessage | None]:
    """Validate configuration for VS orchestration

    Returns:
        tuple: (thread_id, error_message) - error_message is None if valid
    """
    if "configurable" not in config:
        logger.error("Missing 'configurable' in config")
        error_msg = _create_error_message(ValueError("Missing required configuration"), "initializing vector search")
        return "", error_msg

    if "thread_id" not in config["configurable"]:
        logger.error("Missing 'thread_id' in config")
        error_msg = _create_error_message(ValueError("Missing session identifier"), "initializing vector search")
        return "", error_msg

    return config["configurable"]["thread_id"], None


def _validate_vs_state(state: OptimizerState) -> tuple[list, AIMessage | None]:
    """Validate state for VS orchestration

    Returns:
        tuple: (messages, error_message) - error_message is None if valid
    """
    messages = state.get("messages", [])
    if not messages:
        logger.warning("No messages in state - skipping VS orchestration")
        return [], None

    if not isinstance(messages, list):
        logger.error("State messages is not a list: %s", type(messages))
        error_msg = _create_error_message(
            TypeError(f"Expected list, got {type(messages).__name__}"), "reading message history"
        )
        return [], error_msg

    return messages, None


def _create_vs_tool_messages(messages: list, raw_documents: list, result: dict) -> list:
    """Create ToolMessages for VS results

    Returns:
        list: ToolMessages or single error message if serialization fails
    """
    tool_responses = []
    last_message = messages[-1]

    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return tool_responses

    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name", "")
        if tool_name in {"optimizer_vs-retriever", "optimizer_vs-rephrase", "optimizer_vs-grading"}:
            try:
                tool_responses.append(
                    ToolMessage(
                        content=json.dumps(
                            {"documents": raw_documents, "context_input": result["context_input"]}, cls=DecimalEncoder
                        ),
                        tool_call_id=tool_call["id"],
                        name=tool_name,
                        additional_kwargs={"internal_vs": True},
                    )
                )
            except (TypeError, ValueError) as ex:
                logger.exception("Failed to serialize VS results")
                error_msg = _create_error_message(ex, "serializing vector search results")
                return [error_msg]

    return tool_responses


async def vs_orchestrate(state: OptimizerState, config: RunnableConfig) -> dict:
    """
    Orchestrate internal VS pipeline: rephrase → retrieve → grade
    Store results in state, NOT in message history (avoids context bloat)

    Creates ToolMessages with raw documents for GUI, formatted string for LLM injection.
    """
    empty_result = {"context_input": "", "documents": ""}

    # Validate config
    thread_id, error_msg = _validate_vs_config(config)
    if error_msg:
        return {"context_input": "", "documents": "", "messages": [error_msg]}

    logger.info("VS Orchestration started for thread: %s", thread_id)

    # Validate state
    messages, error_msg = _validate_vs_state(state)
    if error_msg:
        return {"context_input": "", "documents": "", "messages": [error_msg]}
    if not messages:
        return empty_result

    # Execute VS pipeline
    result, raw_documents = await _execute_vs_pipeline(thread_id, messages, config, empty_result)

    # Create ToolMessages
    tool_responses = _create_vs_tool_messages(messages, raw_documents, result)

    # If tool message creation returned error, return it
    if tool_responses and isinstance(tool_responses[0], AIMessage):
        return {"context_input": "", "documents": "", "messages": tool_responses}

    # Combine state updates with ToolMessages
    result["messages"] = tool_responses
    return result


async def _execute_vs_pipeline(
    thread_id: str, messages: list, config: RunnableConfig, empty_result: dict
) -> tuple[dict, list]:
    """Execute the VS pipeline: rephrase → retrieve → grade

    Returns:
        tuple: (result dict, raw_documents list)
    """
    raw_documents = []

    try:
        # Extract user question
        question = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                question = msg.content
                break

        if not question:
            logger.error("No user question found in message history")
            return empty_result, raw_documents

        logger.info("User question: %s", question)

        # Get chat history for rephrasing
        chat_history = [msg.content for msg in messages if isinstance(msg, (HumanMessage, AIMessage))]
        use_history = config["metadata"].get("use_history", True)

        # Step 1: Rephrase
        rephrased_question = await _vs_step_rephrase(thread_id, question, chat_history, use_history)

        # Step 2: Retrieve
        retrieval_result = _vs_step_retrieve(thread_id, rephrased_question)
        if not retrieval_result or retrieval_result.num_documents == 0:
            logger.info("No documents retrieved - transparent completion")
            return empty_result, raw_documents

        # Preserve raw documents for client GUI
        raw_documents = retrieval_result.documents

        # Step 3: Grade
        result = await _vs_step_grade(thread_id, question, retrieval_result.documents, rephrased_question)
        return result, raw_documents

    except Exception as ex:
        error_msg = _create_error_message(ex, "during vector search orchestration")
        return {"context_input": "", "documents": "", "messages": [error_msg]}, raw_documents


# #############################################################################
# # GRAPH
# #############################################################################
def main(tools: list):
    """Define the graph with MCP tool nodes and dual-path routing"""
    # Build the graph
    workflow = StateGraph(OptimizerState)

    # Define the nodes
    workflow.add_node("initialise", initialise)
    workflow.add_node("stream_completion", stream_completion)
    workflow.add_node("tools", custom_tool_node(tools))
    workflow.add_node("vs_orchestrate", vs_orchestrate)  # Internal VS pipeline

    # Add Edges
    workflow.add_edge(START, "initialise")
    workflow.add_edge("initialise", "stream_completion")

    # Conditional routing: should_continue() returns "vs_orchestrate", "tools", or END
    workflow.add_conditional_edges(
        "stream_completion",
        should_continue,
    )

    # Both paths return to stream_completion for final response
    workflow.add_edge("tools", "stream_completion")  # External tools path
    workflow.add_edge("vs_orchestrate", "stream_completion")  # VS orchestration path

    # Compile the graph and return it
    mcp_graph = workflow.compile(checkpointer=graph_memory)
    logger.debug("Chatbot Graph Built with tools: %s", tools)
    logger.info("Dual-path routing enabled: VS tools → vs_orchestrate, External tools → tools")
    ## This will output the Graph in ascii; don't deliver uncommented
    # mcp_graph.get_graph(xray=True).print_ascii()

    return mcp_graph


if __name__ == "__main__":
    main([])
