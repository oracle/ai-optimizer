"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

DISABLED!! Due to some models not being able to handle tool calls, this code is not called.  It is
maintained here for future capabilities.  DO NOT DELETE (gotsysdba - 11-Feb-2025)
"""
# spell-checker:ignore vectorstore vectorstores oraclevs mult langgraph

from typing import Annotated

from langchain_core.prompts import PromptTemplate
from langchain_core.tools import BaseTool, tool
from langchain_core.documents.base import Document
from langchain_core.runnables import RunnableConfig
from langchain_community.vectorstores.oraclevs import OracleVS
from langgraph.prebuilt import InjectedState

from common import logging_config

logger = logging_config.logging.getLogger("server.tools.oraclevs_retriever")


#############################################################################
# Oracle Vector Store Retriever Tool
#############################################################################
def oraclevs_tool(
    state: Annotated[dict, InjectedState],
    config: RunnableConfig,
) -> list[dict]:
    """Search and return information using Vector Search"""
    logger.info("Initializing OracleVS Tool")
    # Take our contextualization prompt and reword the question
    # before doing the vector search; do only if history is turned on
    history = state["cleaned_messages"]
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
        vs_settings = config["metadata"]["vector_search"]
        logger.info("Initializing Vector Store: %s", vs_settings.vector_store)
        try:
            vectorstore = OracleVS(db_conn, embed_client, vs_settings.vector_store, vs_settings.distance_metric)
        except Exception as ex:
            logger.exception("Failed to initialize the Vector Store")
            raise ex

        try:
            search_type = vs_settings.search_type
            search_kwargs = {"k": vs_settings.top_k}

            if search_type == "Similarity":
                retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs=search_kwargs)
            elif search_type == "Similarity Score Threshold":
                search_kwargs["score_threshold"] = vs_settings.score_threshold
                retriever = vectorstore.as_retriever(
                    search_type="similarity_score_threshold", search_kwargs=search_kwargs
                )
            elif search_type == "Maximal Marginal Relevance":
                search_kwargs.update(
                    {
                        "fetch_k": vs_settings.fetch_k,
                        "lambda_mult": vs_settings.lambda_mult,
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
    return documents_dict, retrieve_question


oraclevs_retriever: BaseTool = tool(oraclevs_tool)
oraclevs_retriever.name = "oraclevs_retriever"
