"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore acompletion checkpointer litellm sqlcl multitool

from typing import Literal
import json
import decimal

import litellm

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import convert_to_openai_messages
from langchain_core.runnables import RunnableConfig

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, MessagesState, START, END

from server.mcp.tools.vs_rephrase import _vs_rephrase_impl
from server.mcp.tools.vs_retriever import _vs_retrieve_impl
from server.mcp.tools.vs_grade import _vs_grade_impl

from common import logging_config

logger = logging_config.logging.getLogger("mcp.graph")


#############################################################################
# Graph State
#############################################################################
class OptimizerState(MessagesState):
    """Graph state machine for optimizer workflow"""

    vs_metadata: dict  # Vector search metadata for UX display


#############################################################################
# JSON Encoder for Oracle Decimal types
#############################################################################
class DecimalEncoder(json.JSONEncoder):
    """JSON encoder for Oracle Decimal types"""

    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return str(o)
        return super().default(o)


#############################################################################
# Helper Functions
#############################################################################
def _build_messages_for_llm(state: OptimizerState, sys_prompt, use_history: bool = True) -> list:
    """Build message list for LLM with system prompt and history handling"""
    messages = [SystemMessage(content=sys_prompt.content.text)]

    if use_history:
        # Add all messages except SystemMessages from history
        for msg in state["messages"]:
            if not isinstance(msg, SystemMessage):
                messages.append(msg)
    else:
        # Only include ToolMessages and the latest user message
        for msg in state["messages"]:
            if isinstance(msg, ToolMessage):
                messages.append(msg)
        latest_message = state["messages"][-1]
        if not isinstance(latest_message, ToolMessage):
            messages.append(latest_message)

    return messages


async def _call_llm(messages: list, ll_config: dict, stream: bool = False, tools: list = None):
    """Call LiteLLM with messages and optional tools"""
    openai_messages = convert_to_openai_messages(messages)
    logger.debug("Message types: %s", [msg.get("role") for msg in openai_messages])

    kwargs = {"messages": openai_messages, **ll_config}
    if stream:
        kwargs["stream"] = True
    if tools:
        kwargs["tools"] = tools

    return await litellm.acompletion(**kwargs)


async def _stream_llm_response(response, writer):
    """Stream LLM response chunks and accumulate content"""
    full_response = []
    collected_content = []

    async for chunk in response:
        choice = chunk.choices[0].delta

        # Handle empty response
        if chunk.choices[0].finish_reason == "stop" and choice.content is None and not collected_content:
            return None, None

        # Handle content streaming
        if choice.content is not None:
            # Some providers (OCI/Cohere) send the full completed response in the final chunk with finish_reason='stop'.
            # Skip content from any chunk that has finish_reason='stop' to avoid duplication.
            if chunk.choices[0].finish_reason != "stop":
                writer({"stream": choice.content})
                collected_content.append(choice.content)

        full_response.append(chunk)

    full_text = "".join(collected_content)
    return full_text, full_response


def _build_text_response(full_text: str, full_response: list, writer, state: OptimizerState) -> AIMessage:
    """Build AIMessage for text response with metadata"""

    if not full_response:
        final_response = None
    else:
        last_chunk = full_response[-1]
        last_chunk.object = "chat.completion"
        last_chunk.choices[0].message = {
            "role": "assistant",
            "content": full_text,
        }
        delattr(last_chunk.choices[0], "delta")
        last_chunk.choices[0].finish_reason = "stop"
        final_response = last_chunk.model_dump()

    # Emit completion + token usage
    token_usage = final_response.get("usage", {}) if final_response else {}
    response_metadata = {}
    if token_usage:
        writer({"token_usage": token_usage})
        response_metadata["token_usage"] = token_usage

    if final_response:
        writer({"completion": final_response})

    vs_metadata = state.get("vs_metadata", {})
    if vs_metadata:
        writer({"vs_metadata": vs_metadata})
        response_metadata["vs_metadata"] = vs_metadata

    return AIMessage(
        content=full_text,
        response_metadata=response_metadata,
    )


def _create_error_message(exception: Exception, context: str = "") -> AIMessage:
    """Create user-friendly error wrapper around exception"""
    logger.exception("Error %s", context or "in graph execution")

    error_str = str(exception).split("Traceback (most recent call last):", maxsplit=1)[0].strip()
    error_lines = [line.strip() for line in error_str.split("\n") if line.strip()]
    error_msg = error_lines[0] if error_lines else type(exception).__name__

    context_str = f" {context}" if context else ""
    return AIMessage(
        content=f"I'm sorry, I've run into a problem{context_str}: {error_msg}\n\n"
        "If this appears to be a bug, please report it at: "
        "https://github.com/oracle/ai-optimizer/issues"
    )


def _create_tool_message(
    content: str | dict, tool_call_id: str, name: str = None, serialize_json: bool = False
) -> ToolMessage:
    """Create a ToolMessage with optional JSON serialization"""
    if serialize_json and isinstance(content, dict):
        content = json.dumps(content, cls=DecimalEncoder)
    return ToolMessage(
        content=str(content),
        tool_call_id=tool_call_id,
        name=name,
    )


def _create_ai_message_with_tool_calls(content: str, tool_calls: list) -> AIMessage:
    """Create AIMessage with tool_calls (handles both raw and formatted tool calls)"""
    formatted_calls = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            # Already formatted
            formatted_calls.append(tc)
        else:
            # Raw tool call object from LiteLLM
            formatted_calls.append(
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": json.loads(tc.function.arguments),
                }
            )
    return AIMessage(content=content, tool_calls=formatted_calls)


async def _execute_tool_call(tool_call, tools: list, messages: list, all_new_messages: list):
    """Execute a single tool call and append result messages"""
    logger.info("Executing tool: %s with args: %s", tool_call.function.name, tool_call.function.arguments)

    # Find the tool object
    tool_obj = next((t for t in tools if t.name == tool_call.function.name), None)
    if not tool_obj:
        logger.error("Tool not found: %s", tool_call.function.name)
        tool_msg = _create_tool_message(
            content=f"Error: Tool {tool_call.function.name} not found",
            tool_call_id=tool_call.id,
            name=tool_call.function.name,
        )
        messages.append(tool_msg)
        all_new_messages.append(tool_msg)
        return

    # Execute the tool (async)
    try:
        args = json.loads(tool_call.function.arguments)
        result = await tool_obj.ainvoke(args)
        tool_msg = _create_tool_message(
            content=str(result),
            tool_call_id=tool_call.id,
            name=tool_call.function.name,
        )
        messages.append(tool_msg)
        all_new_messages.append(tool_msg)
        logger.info("Tool executed successfully: %s", tool_call.function.name)
        logger.info("Tool result: %s", str(result)[:500])  # First 500 chars
    except Exception as ex:
        logger.error("Tool execution failed: %s - %s", tool_call.function.name, ex)
        tool_msg = _create_tool_message(
            content=f"Error executing {tool_call.function.name}: {str(ex)}",
            tool_call_id=tool_call.id,
            name=tool_call.function.name,
        )
        messages.append(tool_msg)
        all_new_messages.append(tool_msg)


#############################################################################
# Graph Nodes
#############################################################################
async def stream_completion(state: OptimizerState, config: RunnableConfig):
    """Stream completion from LLM"""
    writer = get_stream_writer()

    try:
        ll_config = config["configurable"]["ll_config"]
        metadata = config.get("metadata", {})
        sys_prompt = metadata.get("sys_prompt")
        use_history = metadata.get("use_history", True)

        # Build message list
        messages = _build_messages_for_llm(state, sys_prompt, use_history)

        logger.info("Calling LiteLLM with %d messages (history: %s)", len(messages), use_history)
        response = await _call_llm(messages, ll_config, stream=True)

        # Stream and accumulate response
        full_text, full_response = await _stream_llm_response(response, writer)
        if full_text is None:
            result_message = AIMessage(content="I'm sorry, I was unable to produce a response.")
        else:
            result_message = _build_text_response(full_text, full_response, writer, state)
        return {"messages": [result_message]}

    except litellm.exceptions.APIConnectionError as ex:
        return {"messages": [_create_error_message(ex, "connecting to LLM API")]}
    except Exception as ex:
        return {"messages": [_create_error_message(ex, "generating completion")]}


async def vs_orchestrate(state: OptimizerState, config: RunnableConfig):
    """Orchestrate vector search RAG pipeline"""
    thread_id = config["configurable"]["thread_id"]
    metadata = config.get("metadata", {})
    vector_search = metadata.get("vector_search")

    logger.info("VS orchestrate starting (thread: %s)", thread_id)

    # Remove old ToolMessages and their corresponding AIMessages with tool_calls
    messages = [
        msg
        for msg in state["messages"]
        if not isinstance(msg, ToolMessage) and not (isinstance(msg, AIMessage) and msg.tool_calls)
    ]

    # Extract user question from latest message
    latest_message = messages[-1]
    question = latest_message.content if hasattr(latest_message, "content") else str(latest_message)

    # Build chat history for rephrase (exclude latest question and system messages)
    chat_history = []
    if vector_search.rephrase:
        for msg in messages[:-1]:
            if not isinstance(msg, SystemMessage):
                role = "user" if msg.type == "human" else "assistant"
                chat_history.append(f"{role}: {msg.content}")

    # Step 1: Optionally rephrase the question
    query = question
    if vector_search.rephrase:
        logger.info("Calling rephrase...")
        rephrase_result = await _vs_rephrase_impl(
            thread_id=thread_id,
            question=question,
            chat_history=chat_history if chat_history else None,
            mcp_client="Optimizer",
            model="graph-orchestration",
        )
        if rephrase_result.status == "success" and rephrase_result.was_rephrased:
            query = rephrase_result.rephrased_prompt
            logger.info("Query rephrased: '%s'", query)

    # Step 2: Retrieve documents
    logger.info("Calling retriever with query: '%s'", query)
    retrieval_result = _vs_retrieve_impl(
        thread_id=thread_id,
        question=query,
        mcp_client="Optimizer",
        model="graph-orchestration",
    )

    if retrieval_result.status != "success":
        logger.error("Retrieval failed: %s", retrieval_result.error)
        # Return empty ToolMessage on failure
        tool_message = _create_tool_message(
            content="Vector search retrieval failed. Please try again.",
            tool_call_id="vs_retriever",
        )
        return {"messages": messages + [tool_message]}

    documents = retrieval_result.documents
    logger.info("Retrieved %d documents", len(documents))

    # Step 3: Optionally grade documents
    formatted_docs = ""
    if vector_search.grade and documents:
        logger.info("Calling grade...")
        grade_result = await _vs_grade_impl(
            thread_id=thread_id,
            question=question,  # Use original question for grading
            documents=documents,
            mcp_client="Optimizer",
            model="graph-orchestration",
        )
        if grade_result.status == "success" and grade_result.relevant == "yes":
            formatted_docs = grade_result.formatted_documents
            logger.info("Documents graded as relevant")
        else:
            logger.info("Documents graded as not relevant")
    else:
        # No grading - format all documents
        formatted_docs = "\n\n".join([doc["page_content"] for doc in documents])

    # Create AIMessage with tool_calls (required by OpenAI API)
    ai_message = _create_ai_message_with_tool_calls(
        content="",
        tool_calls=[
            {
                "id": "vs_retriever",
                "name": "optimizer_vs-retriever",
                "args": {"question": query},
            }
        ],
    )

    # Create ToolMessage with documents as JSON (client expects this format)
    tool_message = _create_tool_message(
        content={
            "documents": documents,
            "num_documents": len(documents),
            "searched_tables": retrieval_result.searched_tables,
            "formatted_text": formatted_docs if formatted_docs else "No relevant documents found.",
        },
        tool_call_id="vs_retriever",
        name="optimizer_vs-retriever",
        serialize_json=True,
    )

    # Store metadata for UX display (preserved separately from context)
    vs_metadata = {
        "num_documents": len(documents),
        "searched_tables": retrieval_result.searched_tables,
        "context_input": query,
    }

    return {
        "messages": messages + [ai_message, tool_message],
        "vs_metadata": vs_metadata,
    }


def sqlcl_orchestrate(tools):
    """Orchestrate SQL tool execution (true MCP pattern with multi-turn support)"""

    async def execute_tools(state: OptimizerState, config: RunnableConfig):
        """Execute SQL tools via LLM-driven tool calling with multi-turn loop"""
        thread_id = config["configurable"]["thread_id"]
        ll_config = config["configurable"]["ll_config"]
        metadata = config.get("metadata", {})
        sys_prompt = metadata.get("sys_prompt")
        tool_defs = metadata.get("tools", [])  # OpenAI function definitions
        use_history = metadata.get("use_history", True)

        logger.info("SQLcl orchestrate starting (thread: %s)", thread_id)

        # Build initial message list
        messages = _build_messages_for_llm(state, sys_prompt, use_history)

        # Track all messages created during orchestration
        all_new_messages = []
        max_iterations = 10  # Prevent infinite loops

        for iteration in range(max_iterations):
            # Call LLM with tools bound (let LLM decide which tools to call)
            sqlcl_tools = [t for t in tool_defs if "sqlcl" in t["function"]["name"]]
            logger.info("Turn %d: Calling LLM with %d sqlcl tools", iteration + 1, len(sqlcl_tools))
            response = await _call_llm(messages, ll_config, tools=sqlcl_tools)

            logger.debug("Response received, extracting tool calls...")
            # Extract tool calls from LLM response
            try:
                ai_msg_content = response.choices[0].message.content or ""
                tool_calls = response.choices[0].message.tool_calls or []
                logger.debug("Extracted: content_len=%d, tool_calls=%d", len(ai_msg_content), len(tool_calls))
            except (AttributeError, IndexError) as ex:
                logger.error("Failed to extract response: %s", ex)
                logger.error("Response object: %s", response)
                break

            if not tool_calls:
                # LLM decided not to call any tools - we're done
                logger.info("Turn %d: LLM did not call any tools, ending orchestration", iteration + 1)
                break

            logger.info("Turn %d: LLM called %d tool(s)", iteration + 1, len(tool_calls))

            # Create AIMessage with tool_calls (required for OpenAI message format)
            ai_message = _create_ai_message_with_tool_calls(
                content=ai_msg_content,
                tool_calls=tool_calls,
            )
            messages.append(ai_message)
            all_new_messages.append(ai_message)

            # Execute each tool and create ToolMessages
            for tc in tool_calls:
                await _execute_tool_call(tc, tools, messages, all_new_messages)

            # Continue loop - LLM will see tool results and decide if it needs more tools

        logger.info("SQLcl orchestration completed after %d turn(s)", iteration + 1)
        return {"messages": all_new_messages}

    return execute_tools


def multitool(tools):
    """Orchestrate both vector search and SQL tools together

    Execution order:
    1. VS orchestration (forced retrieval, ephemeral documents)
    2. SQL orchestration (LLM-driven, persistent messages)

    This preserves the forced retrieval pattern for VS while allowing
    LLM-driven tool calling for SQL operations.
    """

    async def execute_multitool(state: OptimizerState, config: RunnableConfig):
        thread_id = config["configurable"]["thread_id"]
        logger.info("Multitool orchestration starting (thread: %s)", thread_id)

        # Split tools by prefix
        sql_tools = [t for t in tools if t.name.startswith("sqlcl_")]

        logger.debug("SQL tools: %s", [t.name for t in sql_tools])

        # Execute VS orchestration first (forced retrieval)
        # Note: vs_orchestrate uses internal tools (rephrase, grade, retriever)
        vs_result = await vs_orchestrate(state, config)

        # Update state with VS messages so LLM can see the documents
        # Messages are ephemeral (cleared next turn) but visible within this turn
        vs_messages = vs_result.get("messages", [])
        updated_state = {
            **state,
            "messages": state["messages"] + vs_messages,
        }

        # Filter metadata to only show SQL tools to LLM
        sql_config = {
            **config,
            "metadata": {
                **config.get("metadata", {}),
                "tools": [t for t in config["metadata"]["tools"] if t["function"]["name"].startswith("sqlcl_")],
            },
        }

        # Execute SQL orchestration with updated state (LLM-driven, multi-turn)
        # LLM sees VS ToolMessage with documents and can decide if SQL is needed
        sql_result = await sqlcl_orchestrate(sql_tools)(updated_state, sql_config)
        sql_messages = sql_result.get("messages", [])

        # Return both VS and SQL messages when SQL was used
        # LLM may need both: documents for guidelines/context, SQL for current values
        if sql_messages:
            logger.info("SQL tools were used, returning both VS and SQL messages")
            return {
                "messages": vs_messages + sql_messages,
                "vs_metadata": vs_result.get("vs_metadata", {}),
            }
        logger.info("No SQL tools used, returning only VS messages")
        return {
            "messages": vs_messages,
            "vs_metadata": vs_result.get("vs_metadata", {}),
        }

    return execute_multitool


def route_tools(
    _: OptimizerState, config: RunnableConfig
) -> Literal["vs_orchestrate", "sqlcl_orchestrate", "multitool", "stream_completion"]:
    """Route to appropriate orchestrator based on tool configuration"""
    tools = config["metadata"].get("tools", [])

    if not tools:
        logger.debug("No tools configured, routing to stream_completion")
        return "stream_completion"

    tool_names = [tool["function"]["name"] for tool in tools]
    tool_config = {
        "has_optimizer": any(name.startswith("optimizer_") for name in tool_names),
        "has_sqlcl": any(name.startswith("sqlcl_") for name in tool_names),
    }

    if tool_config["has_optimizer"] and not tool_config["has_sqlcl"]:
        logger.debug("Routing to vs_orchestrate")
        return "vs_orchestrate"
    if tool_config["has_sqlcl"] and not tool_config["has_optimizer"]:
        logger.debug("Routing to sqlcl_orchestrate")
        return "sqlcl_orchestrate"
    if tool_config["has_optimizer"] and tool_config["has_sqlcl"]:
        logger.debug("Routing to multitool")
        return "multitool"

    # Fallback: no recognized tools
    logger.warning("No recognized tools detected, routing to stream_completion")
    return "stream_completion"


#############################################################################
# MAIN
#############################################################################
graph_memory = InMemorySaver()


def main(tools: list):
    """Define the graph with MCP tool nodes and dual-path routing"""
    workflow = StateGraph(OptimizerState)

    # Add nodes
    workflow.add_node("stream_completion", stream_completion)
    workflow.add_node("vs_orchestrate", vs_orchestrate)
    workflow.add_node("sqlcl_orchestrate", sqlcl_orchestrate(tools))
    workflow.add_node("multitool", multitool(tools))

    # Wire up the graph with conditional routing from START
    workflow.add_conditional_edges(
        START,
        route_tools,
        {
            "vs_orchestrate": "vs_orchestrate",
            "sqlcl_orchestrate": "sqlcl_orchestrate",
            "multitool": "multitool",
            "stream_completion": "stream_completion",  # No tools → go straight to completion
        },
    )

    # All orchestrators route to stream_completion for final response
    workflow.add_edge("vs_orchestrate", "stream_completion")
    workflow.add_edge("sqlcl_orchestrate", "stream_completion")
    workflow.add_edge("multitool", "stream_completion")

    # stream_completion routes to END
    workflow.add_edge("stream_completion", END)

    # Compile and return
    mcp_graph = workflow.compile(checkpointer=graph_memory)
    logger.debug("Graph compiled with %d tools.", len(tools))
    return mcp_graph


if __name__ == "__main__":
    main([])
