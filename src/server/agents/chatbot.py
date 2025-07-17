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

from langchain_core.documents.base import Document
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.output_parsers import StrOutputParser, PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_community.vectorstores.oraclevs import OracleVS

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState, StateGraph, START, END

from pydantic import BaseModel, Field

from server.api.utils.databases import execute_sql
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
    model_name = config["metadata"]["model_name"]
    if "model" in ai_message.response_metadata:
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
        model=model_name,
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


def vs_retrieve(state: AgentState, config: RunnableConfig) -> AgentState:
    """Search and return information using Vector Search"""
    ## Note that this should be a tool call; but some models (Perplexity/OCI GenAI)
    ## have limited or no tools support.  Instead we'll call as part of the pipeline
    ## and fake a tools call.  This can be later reverted to a tool without much code change.
    logger.info("Perform Vector Search")
    # Take our contextualization prompt and reword the question
    # before doing the vector search; do only if history is turned on
    history = copy.deepcopy(state["cleaned_messages"])
    retrieve_question = history.pop().content
    if config["metadata"]["use_history"] and config["metadata"]["ctx_prompt"].prompt and len(history) > 1:
        model = config["configurable"].get("ll_client", None)
        ctx_template = """
            {ctx_prompt}
            Here is the context and history:
            -------
            {history}
            -------
            Here is the user input:
            -------
            {question}
            -------
            Return ONLY the rephrased query without any explanation or additional text.
        """
        rephrase = PromptTemplate(
            template=ctx_template,
            input_variables=["ctx_prompt", "history", "question"],
        )
        chain = rephrase | model
        logger.info("Retrieving Rephrased Input for VS")
        result = chain.invoke(
            {
                "ctx_prompt": config["metadata"]["ctx_prompt"].prompt,
                "history": history,
                "question": retrieve_question,
            }
        )
        if result.content != retrieve_question:
            logger.info("**** Replacing User Question: %s with contextual one: %s", retrieve_question, result.content)
            retrieve_question = result.content
    try:
        logger.info("Connecting to VectorStore")
        db_conn = config["configurable"]["db_conn"]
        embed_client = config["configurable"]["embed_client"]
        vector_search = config["metadata"]["vector_search"]
        logger.info("Initializing Vector Store: %s", vector_search.vector_store)
        try:
            vectorstore = OracleVS(db_conn, embed_client, vector_search.vector_store, vector_search.distance_metric)
        except Exception as ex:
            logger.exception("Failed to initialize the Vector Store")
            raise ex

        try:
            search_type = vector_search.search_type
            search_kwargs = {"k": vector_search.top_k}

            if search_type == "Similarity":
                retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs=search_kwargs)
            elif search_type == "Similarity Score Threshold":
                search_kwargs["score_threshold"] = vector_search.score_threshold
                retriever = vectorstore.as_retriever(
                    search_type="similarity_score_threshold", search_kwargs=search_kwargs
                )
            elif search_type == "Maximal Marginal Relevance":
                search_kwargs.update(
                    {
                        "fetch_k": vector_search.fetch_k,
                        "lambda_mult": vector_search.lambda_mult,
                    }
                )
                retriever = vectorstore.as_retriever(search_type="mmr", search_kwargs=search_kwargs)
            else:
                raise ValueError(f"Unsupported search_type: {search_type}")
            logger.info("Invoking retriever on: %s", retrieve_question)
            documents = retriever.invoke(retrieve_question)
        except Exception as ex:
            logger.exception("Failed to perform Oracle Vector Store retrieval")
            raise ex
    except (AttributeError, KeyError, TypeError) as ex:
        documents = Document(
            id="DocumentException", page_content="I'm sorry, I think you found a bug!", metadata={"source": f"{ex}"}
        )
    documents_dict = [vars(doc) for doc in documents]
    logger.info("Found Documents: %i", len(documents_dict))
    return {"context_input": retrieve_question, "documents": documents_dict}


def grade_documents(state: AgentState, config: RunnableConfig) -> Literal["generate_response", "vs_generate"]:
    """Determines whether the retrieved documents are relevant to the question."""
    logger.info("Grading Vector Search Response using %i retrieved documents", len(state["documents"]))

    # Data model
    class Grade(BaseModel):
        """Binary score for relevance check."""

        binary_score: str = Field(description="Relevance score 'yes' or 'no'")

    if config["metadata"]["vector_search"].grading:
        # LLM (Bound to Tool)
        model = config["configurable"].get("ll_client", None)
        try:
            llm_with_grader = model.with_structured_output(Grade)
        except NotImplementedError:
            logger.error("Model does not support structured output")
            parser = PydanticOutputParser(pydantic_object=Grade)
            llm_with_grader = model | parser

        # Prompt
        grade_template = """
        You are a Grader assessing the relevance of retrieved text to the user's input.
        You MUST respond with a only a binary score of 'yes' or 'no'.
        If you DO find ANY relevant retrieved text to the user's input, return 'yes' immediately and stop grading.
        If you DO NOT find relevant retrieved text to the user's input, return 'no'.
        Here is the user input:
        -------
        {question}
        -------
        Here is the retrieved text:
        -------
        {context}
        """
        grader = PromptTemplate(
            template=grade_template,
            input_variables=["context", "question"],
        )
        documents = document_formatter(state["documents"])
        question = state["context_input"]
        logger.debug("Grading %s against Documents: %s", question, documents)
        chain = grader | llm_with_grader
        try:
            scored_result = chain.invoke({"question": question, "context": documents})
            logger.info("Grading completed.")
            score = scored_result.binary_score
        except Exception:
            logger.error("LLM is not returning binary score in grader; marking all results relevant.")
            score = "yes"
    else:
        logger.info("Vector Search Grading disabled; marking all results relevant.")
        score = "yes"

    logger.info("Grading Decision: Vector Search Relevant: %s", score)
    if score == "yes":
        # This is where we fake a tools response before the completion.
        logger.debug("Creating ToolsMessage Documents: %s", state["documents"])
        logger.debug("Creating ToolsMessage ContextQ:  %s", state["context_input"])

        state["messages"].append(
            ToolMessage(
                content=json.dumps([state["documents"], state["context_input"]], cls=DecimalEncoder),
                name="oraclevs_tool",
                tool_call_id="tool_placeholder",
            )
        )
        logger.debug("ToolsMessage Created")
        return "vs_generate"
    else:
        return "generate_response"


async def vs_generate(state: AgentState, config: RunnableConfig) -> None:
    """Generate answer when Vector Search enabled; modify state with response"""
    logger.info("Generating Vector Search Response")

    # Generate prompt with Vector Search context
    generate_template = "SystemMessage(content='{sys_prompt}\n {context}'), HumanMessage(content='{question}')"
    prompt_template = PromptTemplate(
        template=generate_template,
        input_variables=["sys_prompt", "context", "question"],
    )

    # Chain and Run
    llm = config["configurable"].get("ll_client", None)
    generate_chain = prompt_template | llm | StrOutputParser()
    documents = document_formatter(state["documents"])
    logger.debug("Completing: '%s' against relevant VectorStore documents", state["context_input"])
    chain = {
        "sys_prompt": config["metadata"]["sys_prompt"].prompt,
        "question": state["context_input"],
        "context": documents,
    }

    response = await generate_chain.ainvoke(chain)
    return {"messages": ("assistant", response)}


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


def use_tool(_, config: RunnableConfig) -> Literal["selectai_generate", "vs_retrieve", "generate_response"]:
    """Conditional edge to determine if using SelectAI, Vector Search or not"""
    selectai_enabled = config["metadata"]["selectai"].enabled
    if selectai_enabled:
        logger.info("Invoking Chatbot with SelectAI: %s", selectai_enabled)
        return "selectai_generate"

    enabled = config["metadata"]["vector_search"].enabled
    if enabled:
        logger.info("Invoking Chatbot with Vector Search: %s", enabled)
        return "vs_retrieve"

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
workflow.add_node("vs_retrieve", vs_retrieve)
workflow.add_node("vs_generate", vs_generate)
workflow.add_node("selectai_generate", selectai_generate)
workflow.add_node("generate_response", generate_response)
workflow.add_node("respond", respond)

# Start the agent with clean messages
workflow.add_edge(START, "agent")

# Branch to either "selectai_generate", "vs_retrieve", or "generate_response"
workflow.add_conditional_edges("agent", use_tool)
workflow.add_edge("generate_response", "respond")

# If selectAI
workflow.add_edge("selectai_generate", "respond")

# If retrieving, grade the documents returned and either generate (not relevant) or vs_generate (relevant)
workflow.add_conditional_edges("vs_retrieve", grade_documents)
workflow.add_edge("vs_generate", "respond")

# Finish with OpenAI Compatible Response
workflow.add_edge("respond", END)

# Compile
memory = MemorySaver()
chatbot_graph = workflow.compile(checkpointer=memory)

## This will output the Graph in ascii; don't deliver uncommented
# chatbot_graph.get_graph(xray=True).print_ascii()
