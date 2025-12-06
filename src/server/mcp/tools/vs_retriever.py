"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore mult oraclevs vectorstores litellm

from typing import Optional, List
import json

from pydantic import BaseModel

from langchain_community.vectorstores.oraclevs import OracleVS

from litellm import completion

import server.api.utils.settings as utils_settings
import server.api.utils.databases as utils_databases
import server.api.utils.models as utils_models
import server.api.utils.oci as utils_oci
import server.mcp.prompts.defaults as table_selection_prompts
from server.mcp.tools.vs_discovery import _vs_discovery_impl

from common import logging_config

logger = logging_config.logging.getLogger("mcp.tools.retriever")

# Configuration constants
TABLE_SELECTION_TEMPERATURE = 0.0  # Deterministic table selection
TABLE_SELECTION_MAX_TOKENS = 200  # Limit response size for table selection
DEFAULT_MAX_TABLES = 3  # Default maximum number of tables to search


class DatabaseConnectionError(Exception):
    """Raised when database connection is not available"""


class VectorSearchResponse(BaseModel):
    """Response from the optimizer_vs_retrieve tool"""

    context_input: str  # The (possibly rephrased) question used for retrieval
    documents: List[dict]  # List of retrieved documents with metadata
    num_documents: int  # Number of documents retrieved
    searched_tables: List[str]  # List of table names that were searched successfully
    failed_tables: List[str] = []  # List of table names that failed during search
    status: str  # "success" or "error"
    error: Optional[str] = None


# Helper functions for retriever operations


def _get_available_vector_stores(thread_id: str):
    """Get list of available vector stores with enabled embedding models.

    Delegates to vs_discovery which handles:
    - Discovery enabled: queries database for all vector tables with enabled models
    - Discovery disabled: returns configured vector store from settings
    """
    try:
        response = _vs_discovery_impl(thread_id=thread_id, filter_enabled_models=True)

        if response.status != "success":
            logger.error("Discovery failed: %s", response.error)
            return []

        available = response.parsed_tables
        for table in available:
            logger.info(
                "Checking table %s (alias: %s) with model: %s",
                table.table_name,
                table.parsed.alias,
                table.parsed.model,
            )
            logger.info("  -> Enabled")

        logger.info(
            "Found %d available vector stores with enabled models",
            len(available),
        )
        return available
    except Exception as ex:
        logger.error("Failed to get available vector stores: %s", ex)
        return []


def _select_tables_with_llm(
    question: str, available_tables: List, ll_config: dict, max_tables: int = DEFAULT_MAX_TABLES
) -> List[str]:
    """Use LLM to select most relevant vector stores for the question

    Args:
        question: User's question
        available_tables: List of VectorTable objects
        ll_config: LiteLLM config dict with model and parameters
        max_tables: Maximum number of tables to select (default: DEFAULT_MAX_TABLES)

    Returns:
        List of selected table names
    """
    if not available_tables:
        logger.warning("No available tables to select from")
        return []

    # If only one table available, use it
    if len(available_tables) == 1:
        table_name = available_tables[0].table_name
        logger.info("Only one table available, selecting: %s", table_name)
        return [table_name]

    # Build context about available tables
    table_descriptions = []
    for table in available_tables:
        desc_parts = [f"- {table.table_name}"]
        if table.parsed.alias:
            desc_parts.append(f" (alias: {table.parsed.alias})")
        if table.parsed.description:
            desc_parts.append(f": {table.parsed.description}")
        if table.parsed.model:
            desc_parts.append(f" [model: {table.parsed.model}]")

        table_descriptions.append("".join(desc_parts))

    tables_info = "\n".join(table_descriptions)

    # Get table selection prompt from MCP prompts (user customizable)
    prompt_msg = table_selection_prompts.get_prompt_with_override("optimizer_vs-discovery")
    prompt_template = prompt_msg.content.text

    # Format the template with actual values
    prompt = prompt_template.format(tables_info=tables_info, question=question, max_tables=max_tables)

    try:
        # Use client's configured LLM for table selection
        # Override temperature and max_tokens for deterministic selection
        selection_config = {
            **ll_config,
            "temperature": TABLE_SELECTION_TEMPERATURE,
            "max_tokens": TABLE_SELECTION_MAX_TOKENS,
        }
        response = completion(messages=[{"role": "user", "content": prompt}], **selection_config)

        selection_text = response.choices[0].message.content.strip()
        logger.info("LLM table selection response: %s", selection_text)

        # Parse JSON response
        selected_tables = json.loads(selection_text)

        if not isinstance(selected_tables, list):
            logger.warning("LLM returned non-list response, falling back to first table")
            return [available_tables[0].table_name]

        # Validate selected tables exist
        valid_table_names = {table.table_name for table in available_tables}
        selected_tables = [t for t in selected_tables if t in valid_table_names]

        if not selected_tables:
            logger.warning("No valid tables selected, falling back to first table")
            return [available_tables[0].table_name]

        logger.info("Selected %d tables: %s", len(selected_tables), selected_tables)
        return selected_tables[:max_tables]

    except Exception as ex:
        logger.error("Failed to select tables with LLM: %s", ex)
        # Fallback: return first table
        return [available_tables[0].table_name]


def _deduplicate_documents(documents: List) -> List:
    """Deduplicate documents by content, keeping highest scoring version"""
    if not documents:
        return documents

    seen_content = {}
    deduplicated = []

    for doc in documents:
        content = doc.page_content
        if content not in seen_content:
            seen_content[content] = doc
            deduplicated.append(doc)
        else:
            # If duplicate, keep the one with better score (if available)
            existing_score = seen_content[content].metadata.get("score", 0)
            new_score = doc.metadata.get("score", 0)
            if new_score > existing_score:
                # Replace with better scoring document
                deduplicated.remove(seen_content[content])
                seen_content[content] = doc
                deduplicated.append(doc)

    logger.info("Deduplicated %d to %d documents", len(documents), len(deduplicated))
    return deduplicated


def _search_table(table_name, question, db_conn, embed_client, vector_search, table_distance_metric):
    """Search a single vector table and return documents with metadata"""
    logger.info("Searching table: %s with distance metric: %s", table_name, table_distance_metric)

    # Initialize Vector Store for this table using its specific distance metric
    vectorstores = OracleVS(db_conn, embed_client, table_name, table_distance_metric)

    # Configure retriever
    retriever = _configure_retriever(vectorstores, vector_search.search_type, vector_search)

    # Retrieve documents
    documents = retriever.invoke(question)
    logger.info("Retrieved %d documents from %s", len(documents), table_name)

    # Add table name to metadata
    for doc in documents:
        if not hasattr(doc, "metadata"):
            doc.metadata = {}
        doc.metadata["searched_table"] = table_name

    return documents


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
    """Smart vector search retriever with automatic table selection

    Automatically discovers and selects relevant tables based on the question.
    """
    searched_tables = []
    failed_tables = []
    all_documents = []

    try:
        logger.info(
            "Smart Vector Search Retrieve (Thread ID: %s, MCP: %s, Model: %s)",
            thread_id,
            mcp_client,
            model,
        )

        # Get client settings
        client_settings = utils_settings.get_client(thread_id)
        vector_search = client_settings.vector_search

        # Tool presence indicates VS is enabled (controlled by chat.py:77-78)
        logger.info("Perform Vector Search with: %s", question)

        # Get database connection
        db_conn = utils_databases.get_client_database(thread_id, False)
        if not db_conn or not db_conn.connection:
            raise DatabaseConnectionError("No database connection available")
        db_conn = db_conn.connection

        # Get OCI config for embedding client creation
        oci_config = utils_oci.get(client=thread_id)

        # Smart selection: discover and select relevant tables
        logger.info("Performing smart table selection...")
        available_tables = _get_available_vector_stores(thread_id)

        if not available_tables:
            logger.warning("No available vector stores with enabled models")
            return VectorSearchResponse(
                context_input=question,
                documents=[],
                num_documents=0,
                searched_tables=[],
                failed_tables=[],
                status="error",
                error="No vector stores available with enabled embedding models",
            )

        # Build mapping of table_name -> table info for model lookup
        table_info_map = {table.table_name: table for table in available_tables}

        # Use LLM to select relevant tables
        ll_config = utils_models.get_litellm_config(client_settings.ll_model.model_dump(), oci_config)
        tables_to_search = _select_tables_with_llm(
            question,
            available_tables,
            ll_config,  # Uses DEFAULT_MAX_TABLES
        )

        logger.info("Searching %d table(s): %s", len(tables_to_search), tables_to_search)

        # Search each selected table with its specific embedding model
        for table_name in tables_to_search:
            try:
                # Get the table's specific embedding model and distance metric
                table_info = table_info_map[table_name]
                logger.info("Creating embed client for table %s with model %s", table_name, table_info.parsed.model)

                # Create embed client for this table's model and search
                embed_client = utils_models.get_client_embed({"model": table_info.parsed.model}, oci_config)
                documents = _search_table(
                    table_name, question, db_conn, embed_client, vector_search, table_info.parsed.distance_metric
                )
                all_documents.extend(documents)
                searched_tables.append(table_name)
            except Exception as ex:
                logger.error("Failed to search table %s: %s", table_name, ex)
                failed_tables.append(table_name)
                # Continue searching other tables even if one fails

        # Deduplicate documents by content (keep highest scoring)
        all_documents = _deduplicate_documents(all_documents)

        # Sort by score if available (descending)
        all_documents.sort(key=lambda d: d.metadata.get("score", 0), reverse=True)

        # Limit to top_k total documents
        all_documents = all_documents[: vector_search.top_k]

    except (AttributeError, KeyError, TypeError) as ex:
        logger.error("Vector search failed with exception: %s", ex)
        return VectorSearchResponse(
            context_input=question,
            documents=[],
            num_documents=0,
            searched_tables=searched_tables,
            failed_tables=failed_tables,
            status="error",
            error=f"Vector search failed: {str(ex)}",
        )

    logger.info("Found %d documents from %d table(s)", len(all_documents), len(searched_tables))
    if failed_tables:
        logger.warning("Failed to search %d table(s): %s", len(failed_tables), failed_tables)

    return VectorSearchResponse(
        context_input=question,
        documents=[vars(doc) for doc in all_documents],
        num_documents=len(all_documents),
        searched_tables=searched_tables,
        failed_tables=failed_tables,
        status="success",
    )


async def register(mcp, auth):
    """Invoke Registration of Vector Search Retriever"""

    # Note: Keep docstring SHORT for small LLMs. See _vs_retrieve_impl for full documentation.
    @mcp.tool(name="optimizer_vs-retriever")
    @auth.get("/vs_retriever", operation_id="vs_retriever", include_in_schema=False)
    def retriever(
        thread_id: str,
        question: str,
        mcp_client: str = "Optimizer",
        model: str = "UNKNOWN-LLM",
    ) -> VectorSearchResponse:
        """Search documentation using vector similarity. Returns relevant documents."""
        return _vs_retrieve_impl(thread_id, question, mcp_client, model)
