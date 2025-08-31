"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore acompletion checkpointer litellm mult oraclevs vectorstores selectai

import copy
import decimal
import json
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, START, END, MessagesState

from langchain_core.documents.base import Document
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import convert_to_openai_messages
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig

from langchain_community.vectorstores.oraclevs import OracleVS

from litellm import acompletion, completion
from litellm.exceptions import APIConnectionError

from common import logging_config

logger = logging_config.logging.getLogger("server.agents.chatbot")


class DecimalEncoder(json.JSONEncoder):
    """Used with json.dumps to encode decimals"""

    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return str(o)
        return super().default(o)


class OptimizerState(MessagesState):
    """Establish our Agent State Machine"""

    cleaned_messages: list  # Messages w/o VS Results
    context_input: str  # Contextualized User Input (for VS)
    documents: dict  # VectorStore documents
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


def use_tool(_, config: RunnableConfig) -> Literal["vs_retrieve", "stream_completion"]:
    """Conditional edge to determine if using SelectAI, Vector Search or not"""
    # selectai_enabled = config["metadata"]["selectai"].enabled
    # if selectai_enabled:
    #     logger.info("Invoking Chatbot with SelectAI: %s", selectai_enabled)
    #     return "selectai"

    enabled = config["metadata"]["vector_search"].enabled
    if enabled:
        logger.info("Invoking Chatbot with Vector Search: %s", enabled)
        return "vs_retrieve"

    return "stream_completion"


def rephrase(state: OptimizerState, config: RunnableConfig) -> str:
    """Take our contextualization prompt and reword the last user prompt"""
    ctx_prompt = config.get("metadata", {}).get("ctx_prompt")
    retrieve_question = state["messages"][-1].content

    if config["metadata"]["use_history"] and ctx_prompt and len(state["messages"]) > 2:
        ctx_template = """
            {prompt}
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
        rephrase_template = PromptTemplate(
            template=ctx_template,
            input_variables=["ctx_prompt", "history", "question"],
        )
        formatted_prompt = rephrase_template.format(
            prompt=ctx_prompt.prompt, history=state["messages"], question=retrieve_question
        )
        ll_raw = config["configurable"]["ll_config"]
        try:
            response = completion(messages=[{"role": "system", "content": formatted_prompt}], stream=False, **ll_raw)
            print(f"************ {response}")

            context_question = response.choices[0].message.content
        except APIConnectionError as ex:
            logger.error("Failed to rephrase: %s", str(ex))

        if context_question != retrieve_question:
            logger.info(
                "**** Replacing User Question: %s with contextual one: %s", retrieve_question, context_question
            )
            retrieve_question = context_question

    return retrieve_question


def document_formatter(rag_context) -> str:
    """Extract the Vector Search Documents and format into a string"""
    logger.info("Extracting chunks from Vector Search Retrieval")
    chunks = "\n\n".join([doc["page_content"] for doc in rag_context])
    return chunks


#############################################################################
# NODES and EDGES
#############################################################################
async def initialise(state: OptimizerState, config: RunnableConfig) -> OptimizerState:
    """Initialise our chatbot"""
    logger.debug("Initializing Chatbot")
    cleaned_messages = clean_messages(state, config)
    return {"cleaned_messages": cleaned_messages}


async def vs_grade(state: OptimizerState, config: RunnableConfig) -> OptimizerState:
    """Determines whether the retrieved documents are relevant to the question."""
    logger.info("Grading Vector Search Response using %i retrieved documents", len(state["documents"]))
    # Initialise documents as relevant
    relevant = "yes"
    if config["metadata"]["vector_search"].grading and state.get("documents"):
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
        {documents}
        """
        grade_template = PromptTemplate(
            template=grade_template,
            input_variables=["question", "documents"],
        )
        documents_dict = document_formatter(state["documents"])
        question = state["context_input"]
        formatted_prompt = grade_template.format(question=question, documents=documents_dict)
        logger.debug("Grading Prompt: %s", formatted_prompt)
        ll_raw = config["configurable"]["ll_config"]

        # Grade
        try:
            response = await acompletion(
                messages=[{"role": "system", "content": formatted_prompt}], stream=False, **ll_raw
            )
            print(f"************ {response}")
            relevant = response["choices"][0]["message"]["content"]
            logger.info("Grading completed. Relevant: %s", relevant)
            if relevant not in ("yes", "no"):
                logger.error("LLM did not return binary relevant in grader; assuming all results relevant.")
        except APIConnectionError as ex:
            logger.error("Failed to grade; marking all results relevant: %s", str(ex))
    else:
        logger.info("Vector Search Grading disabled; assuming all results relevant.")

    if relevant.lower() == "yes":
        # This is where we fake a tools response before the completion.
        logger.debug("Creating ToolMessage Documents: %s", state["documents"])
        logger.debug("Creating ToolMessage ContextQ:  %s", state["context_input"])

        state["messages"].append(
            ToolMessage(
                content=json.dumps([state["documents"], state["context_input"]], cls=DecimalEncoder),
                name="oraclevs_tool",
                tool_call_id="tool_placeholder",
            )
        )
        logger.debug("ToolMessage Created")
        return {"documents": documents_dict}
    else:
        return {"documents": dict()}


async def vs_retrieve(state: OptimizerState, config: RunnableConfig) -> OptimizerState:
    """Search and return information using Vector Search"""
    ## Note that this should be a tool call; but some models (Perplexity/OCI GenAI)
    ## have limited or no tools support.  Instead we'll call as part of the pipeline
    ## and fake a tools call.  This can be later reverted to a tool without much code change.
    retrieve_question = rephrase(state, config)
    logger.info("Perform Vector Search with: %s", retrieve_question)

    try:
        logger.info("Connecting to VectorStore")
        db_conn = config["configurable"]["db_conn"]
        embed_client = config["configurable"]["embed_client"]
        vector_search = config["metadata"]["vector_search"]
        logger.info("Initializing Vector Store: %s", vector_search.vector_store)
        try:
            vectorstores = OracleVS(db_conn, embed_client, vector_search.vector_store, vector_search.distance_metric)
        except Exception as ex:
            logger.exception("Failed to initialize the Vector Store")
            raise ex

        try:
            search_type = vector_search.search_type
            search_kwargs = {"k": vector_search.top_k}

            if search_type == "Similarity":
                retriever = vectorstores.as_retriever(search_type="similarity", search_kwargs=search_kwargs)
            elif search_type == "Similarity Score Threshold":
                search_kwargs["score_threshold"] = vector_search.score_threshold
                retriever = vectorstores.as_retriever(
                    search_type="similarity_score_threshold", search_kwargs=search_kwargs
                )
            elif search_type == "Maximal Marginal Relevance":
                search_kwargs.update(
                    {
                        "fetch_k": vector_search.fetch_k,
                        "lambda_mult": vector_search.lambda_mult,
                    }
                )
                retriever = vectorstores.as_retriever(search_type="mmr", search_kwargs=search_kwargs)
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
    except Exception as ex:
        logger.error(ex)
        full_text = f"I'm sorry, a completion problem occurred: {str(ex).split('Traceback', 1)[0]}"
    return {"messages": [AIMessage(content=full_text)]}


# Build the state graph
workflow = StateGraph(OptimizerState)
workflow.add_node("initialise", initialise)
workflow.add_node("rephrase", rephrase)
workflow.add_node("vs_retrieve", vs_retrieve)
workflow.add_node("vs_grade", vs_grade)
workflow.add_node("stream_completion", stream_completion)

# Start the chatbot with clean messages
workflow.add_edge(START, "initialise")

# Branch to either "selectai", "vs_retrieve", or "generate_response"
workflow.add_conditional_edges("initialise", use_tool)
# workflow.add_edge("selectai", "stream_completion")
workflow.add_edge("vs_retrieve", "vs_grade")
workflow.add_edge("vs_grade", "stream_completion")

# End the workflow
workflow.add_edge("stream_completion", END)

# Compile the graph
memory = MemorySaver()
chatbot_graph = workflow.compile(checkpointer=memory)
