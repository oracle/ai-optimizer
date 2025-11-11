"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore mult oraclevs vectorstores

from typing import Optional, List

from pydantic import BaseModel

from langchain_core.documents.base import Document
from langchain_community.vectorstores.oraclevs import OracleVS

import server.api.core.settings as core_settings
import server.api.utils.databases as utils_databases
import server.api.utils.models as utils_models
import server.api.utils.oci as utils_oci

from common import logging_config

logger = logging_config.logging.getLogger("mcp.tools.retriever")


class DatabaseConnectionError(Exception):
    """Raised when database connection is not available"""


class VectorSearchResponse(BaseModel):
    """Response from the optimizer_vs_retrieve tool"""

    context_input: str  # The (possibly rephrased) question used for retrieval
    documents: List[dict]  # List of retrieved documents with metadata
    num_documents: int  # Number of documents retrieved
    status: str  # "success" or "error"
    error: Optional[str] = None


# Helper functions for retriever operations
def _configure_retriever(vectorstores, search_type: str, vector_search):
    """Configure retriever based on search type"""
    search_kwargs = {"k": vector_search.top_k}

    if search_type == "Similarity":
        return vectorstores.as_retriever(search_type="similarity", search_kwargs=search_kwargs)
    if search_type == "Similarity Score Threshold":
        search_kwargs["score_threshold"] = vector_search.score_threshold
        return vectorstores.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs=search_kwargs,
        )
    if search_type == "Maximal Marginal Relevance":
        search_kwargs.update(
            {
                "fetch_k": vector_search.fetch_k,
                "lambda_mult": vector_search.lambda_mult,
            }
        )
        return vectorstores.as_retriever(search_type="mmr", search_kwargs=search_kwargs)

    raise ValueError(f"Unsupported search_type: {search_type}")


def _vs_retrieve_impl(
    thread_id: str,
    question: str,
    mcp_client: str,
    model: str,
) -> VectorSearchResponse:
    try:
        logger.info(
            "Vector Search Retrieve (Thread ID: %s, MCP: %s, Model: %s)",
            thread_id,
            mcp_client,
            model,
        )

        # Get client settings
        client_settings = core_settings.get_client_settings(thread_id)
        vector_search = client_settings.vector_search

        # Check if vector search is enabled
        if not vector_search.enabled:
            logger.warning("Vector search is not enabled for thread %s", thread_id)
            return VectorSearchResponse(
                context_input=question,
                documents=[],
                num_documents=0,
                status="error",
                error="Vector search is not enabled in client settings",
            )

        logger.info("Perform Vector Search with: %s", question)

        # Get database connection
        db_client = utils_databases.get_client_database(thread_id, False)
        if not db_client or not db_client.connection:
            raise DatabaseConnectionError("No database connection available")
        db_conn = db_client.connection

        # Get embedding client
        oci_config = utils_oci.get(client=thread_id)
        embed_client = utils_models.get_client_embed(vector_search.model_dump(), oci_config)

        # Initialize Vector Store
        logger.info("Initializing Vector Store: %s", vector_search.vector_store)
        try:
            vectorstores = OracleVS(db_conn, embed_client, vector_search.vector_store, vector_search.distance_metric)
        except Exception as ex:
            logger.exception("Failed to initialize the Vector Store")
            raise ex

        # Configure retriever based on search type
        try:
            retriever = _configure_retriever(vectorstores, vector_search.search_type, vector_search)
            logger.info("Invoking retriever on: %s", question)
            documents = retriever.invoke(question)
        except Exception as ex:
            logger.exception("Failed to perform Oracle Vector Store retrieval")
            raise ex

    except (AttributeError, KeyError, TypeError) as ex:
        logger.error("Vector search failed with exception: %s", ex)
        documents = [
            Document(
                id="DocumentException",
                page_content="I'm sorry, I think you found a bug!",
                metadata={"source": f"{ex}"},
            )
        ]

    documents_dict = [vars(doc) for doc in documents]
    logger.info("Found Documents: %i", len(documents_dict))

    return VectorSearchResponse(
        context_input=question,
        documents=documents_dict,
        num_documents=len(documents_dict),
        status="success",
    )


async def register(mcp, auth):
    """Invoke Registration of Vector Search Retriever"""

    @mcp.tool(name="optimizer_vs-retriever")
    @auth.get("/vs_retriever", operation_id="vs_retriever")
    def retriever(
        thread_id: str,
        question: str,
        mcp_client: str = "Optimizer",
        model: str = "UNKNOWN-LLM",
    ) -> VectorSearchResponse:
        """
        Search and return information using Oracle Vector Search.

        Performs semantic search on Oracle Database vector stores using the
        configured embedding model and vector search settings. The question should
        be a standalone query (optionally rephrased by a separate rephrase tool in
        the LangGraph workflow).

        The results should be graded (by a separate grading tool in the LangGraph workflow)
        unless grading has been explicitly disabled.  If grading has determined that the
        documents are not relevant, no documents are returned and completion is performed
        without the results of the semantic search.

        Args:
            thread_id: Optimizer Client ID (chat thread), used for looking up
                configuration (required)
            question: The user's question to search for (required, may be
                pre-rephrased)
            mcp_client: Name of the MCP client implementation being used
                (Default: Optimizer)
            model: Name and version of the language model being used (optional)

        Returns:
            Dictionary containing:
            - context_input: The question used for retrieval
            - documents: List of retrieved documents with page_content and metadata
            - num_documents: Number of documents retrieved
            - status: "success" or "error"
            - error: Error message if status is "error" (optional)
        """
        return _vs_retrieve_impl(thread_id, question, mcp_client, model)
