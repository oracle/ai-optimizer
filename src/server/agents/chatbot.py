"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore langgraph, oraclevs, checkpointer, ainvoke
# spell-checker:ignore vectorstore, vectorstores, oraclevs, mult, selectai

from datetime import datetime, timezone
from typing import Literal
import json
import copy
import decimal

from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState, StateGraph, START, END

from server.api.core.databases import execute_sql
from common.schema import ChatResponse, ChatUsage, ChatChoices, ChatMessage
from common import logging_config

logger = logging_config.logging.getLogger("server.agents.chatbot")


#############################################################################
# AGENT STATE
#############################################################################
class AgentState(MessagesState):
    """Establish our Agent State Machine"""

    logger.info("Establishing Agent State")
    final_response: ChatResponse  # OpenAI Response
    cleaned_messages: list  # Messages w/o VS Results
    context_input: str  # Contextualized User Input
    documents: dict  # VectorStore documents


#############################################################################
# Functions
#############################################################################
def get_messages(state: AgentState, config: RunnableConfig) -> list:
    """Return a list of messages that will be passed to the model for completion
    Filter out old VS documents to avoid blowing-out the context window
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

    # insert the system prompt; remaining messages cleaned
    if config["metadata"]["sys_prompt"].prompt:
        messages.insert(0, SystemMessage(content=config["metadata"]["sys_prompt"].prompt))

    return messages


def document_formatter(rag_context) -> str:
    """Extract the Vector Search Documents and format into a string"""
    logger.info("Extracting chunks from Vector Search Retrieval")
    logger.debug("Vector Search Context: %s", rag_context)
    chunks = "\n\n".join([doc["page_content"] for doc in rag_context])
    return chunks


class DecimalEncoder(json.JSONEncoder):
    """Used with json.dumps to encode decimals"""

    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return str(o)
        return super().default(o)


#############################################################################
# NODES and EDGES
#############################################################################
def respond(state: AgentState, config: RunnableConfig) -> ChatResponse:
    """Respond in OpenAI Compatible return"""
    ai_message = state["messages"][-1]
    logger.debug("Formatting Response to OpenAI compatible message: %s", repr(ai_message))
    model_id = config["metadata"]["model_id"]
    if "model_id" in ai_message.response_metadata:
        ai_metadata = ai_message
    else:
        ai_metadata = state["messages"][1]
        logger.debug("Using Metadata from: %s", repr(ai_metadata))

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


async def selectai_generate(state: AgentState, config: RunnableConfig) -> None:
    """Generate answer when SelectAI enabled; modify state with response"""
    history = copy.deepcopy(state["cleaned_messages"])
    selectai_prompt = history.pop().content

    logger.info("Generating SelectAI Response on %s", selectai_prompt)
    sql = """
        SELECT DBMS_CLOUD_AI.GENERATE(
            prompt       => :query,
            profile_name => :profile,
            action       => :action)
        FROM dual
    """
    binds = {
        "query": selectai_prompt,
        "profile": config["metadata"]["selectai"].profile,
        "action": config["metadata"]["selectai"].action,
    }
    # Execute the SQL using the connection
    db_conn = config["configurable"]["db_conn"]
    try:
        completion = execute_sql(db_conn, sql, binds)
    except Exception as ex:
        logger.error("SelectAI has hit an issue: %s", ex)
        completion = [{sql: "I'm sorry, I have no information related to your query."}]
    # Response will be [{sql:, completion}]; return the completion
    logger.debug("SelectAI Responded: %s", completion)
    response = list(completion[0].values())[0]

    return {"messages": ("assistant", response)}


async def agent(state: AgentState, config: RunnableConfig) -> AgentState:
    """Invokes the chatbot with messages to be used"""
    logger.debug("Initializing Agent")
    messages = get_messages(state, config)
    return {"cleaned_messages": messages}


def use_tool(_, config: RunnableConfig) -> Literal["selectai_generate", "generate_response"]:
    """Conditional edge to determine if using SelectAI or not"""
    selectai_enabled = config["metadata"]["selectai"].enabled
    if selectai_enabled:
        logger.info("Invoking Chatbot with SelectAI: %s", selectai_enabled)
        return "selectai_generate"

    # Vector search is now handled by MCP tool, so we skip it here
    # But we still need to check if vector search is enabled
    vector_search_enabled = config["metadata"]["vector_search"].enabled if "vector_search" in config["metadata"] else False
    if vector_search_enabled:
        logger.info("Invoking Chatbot with Vector Search enabled")
        # Vector search will be handled by MCP tool calling in the client
        pass

    return "generate_response"


async def generate_response(state: AgentState, config: RunnableConfig) -> AgentState:
    """Invoke the model"""
    model = config["configurable"].get("ll_client", None)
    logger.debug("Invoking on: %s", state["cleaned_messages"])
    try:
        response = await model.ainvoke(state["cleaned_messages"])
    except Exception as ex:
        if hasattr(ex, "message"):
            response = ("assistant", f"I'm sorry: {ex.message}")
        else:
            raise
    return {"messages": [response]}


#############################################################################
# GRAPH
#############################################################################
workflow = StateGraph(AgentState)

# Define the nodes
workflow.add_node("agent", agent)
workflow.add_node("selectai_generate", selectai_generate)
workflow.add_node("generate_response", generate_response)
workflow.add_node("respond", respond)

# Start the agent with clean messages
workflow.add_edge(START, "agent")

# Branch to either "selectai_generate" or "generate_response"
workflow.add_conditional_edges("agent", use_tool)
workflow.add_edge("generate_response", "respond")

# If selectAI
workflow.add_edge("selectai_generate", "respond")

# Finish with OpenAI Compatible Response
workflow.add_edge("respond", END)

# Compile
memory = MemorySaver()
chatbot_graph = workflow.compile(checkpointer=memory)

## This will output the Graph in ascii; don't deliver uncommented
# chatbot_graph.get_graph(xray=True).print_ascii()
