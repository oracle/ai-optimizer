"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore acompletion litellm

from typing import Optional, List

from pydantic import BaseModel

from litellm import acompletion
from litellm.exceptions import APIConnectionError
from langchain_core.prompts import PromptTemplate

import server.api.core.settings as core_settings
import server.api.utils.models as utils_models
import server.api.utils.oci as utils_oci

from common import logging_config

logger = logging_config.logging.getLogger("mcp.tools.grading")


class VectorGradeResponse(BaseModel):
    """Response from the optimizer_vs_grade tool"""

    relevant: str  # "yes" or "no"
    formatted_documents: str  # Documents formatted as string (if relevant)
    grading_enabled: bool  # Whether grading was actually performed
    num_documents: int  # Number of documents evaluated
    status: str  # "success" or "error"
    error: Optional[str] = None


def _format_documents(documents: List[dict]) -> str:
    """Extract and format document page content"""
    return "\n\n".join([doc["page_content"] for doc in documents])


async def _grade_documents_with_llm(question: str, documents_str: str, ll_config: dict) -> str:
    """Grade documents using LLM"""
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
    grade_prompt = PromptTemplate(
        template=grade_template,
        input_variables=["question", "documents"],
    )
    formatted_prompt = grade_prompt.format(question=question, documents=documents_str)
    logger.debug("Grading Prompt: %s", formatted_prompt)

    response = await acompletion(
        messages=[{"role": "system", "content": formatted_prompt}],
        stream=False,
        **ll_config,
    )
    relevant = response["choices"][0]["message"]["content"]
    logger.info("Grading completed. Relevant: %s", relevant)

    if relevant.lower() not in ("yes", "no"):
        logger.error("LLM did not return binary relevant in grader; assuming all results relevant.")
        return "yes"

    return relevant.lower()


async def _vs_grade_impl(
    thread_id: str,
    question: str,
    documents: List[dict],
    mcp_client: str,
    model: str,
) -> VectorGradeResponse:
    try:
        logger.info(
            "Grading Vector Search Response (Thread ID: %s, MCP: %s, Model: %s, Docs: %d)",
            thread_id,
            mcp_client,
            model,
            len(documents),
        )

        # Get client settings
        client_settings = core_settings.get_client_settings(thread_id)
        vector_search = client_settings.vector_search

        # Format documents
        documents_str = _format_documents(documents)
        relevant = "yes"
        grading_enabled = False

        # Only grade if grading is enabled and we have documents
        if vector_search.grading and documents:
            grading_enabled = True
            # Get LLM config
            oci_config = utils_oci.get(client=thread_id)
            ll_model = client_settings.ll_model.model_dump()
            ll_config = utils_models.get_litellm_config(ll_model, oci_config)

            # Grade documents
            try:
                relevant = await _grade_documents_with_llm(question, documents_str, ll_config)
            except APIConnectionError as ex:
                logger.error("Failed to grade; marking all results relevant: %s", str(ex))
                relevant = "yes"
        else:
            logger.info("Vector Search Grading disabled; assuming all results relevant.")

        # Return formatted documents only if relevant
        formatted_docs = documents_str if relevant.lower() == "yes" else ""

        return VectorGradeResponse(
            relevant=relevant.lower(),
            formatted_documents=formatted_docs,
            grading_enabled=grading_enabled,
            num_documents=len(documents),
            status="success",
        )
    except Exception as ex:
        logger.error("Grading failed: %s", ex)
        return VectorGradeResponse(
            relevant="yes",  # Default to yes on error
            formatted_documents="",
            grading_enabled=False,
            num_documents=len(documents) if documents else 0,
            status="error",
            error=str(ex),
        )


async def register(mcp, auth):
    """Invoke Registration of Vector Search Tools"""

    @mcp.tool(name="optimizer_vs-grading")
    @auth.get("/vs_grading", operation_id="vs_grading")
    async def grading(
        thread_id: str,
        question: str,
        documents: List[dict],
        mcp_client: str = "Optimizer",
        model: str = "UNKNOWN-LLM",
    ) -> VectorGradeResponse:
        """
        Grade the relevance of retrieved documents to the user's question.

        Uses an LLM to assess whether the retrieved documents are relevant to the
        user's question. Returns a binary 'yes' or 'no' score. If grading is
        disabled, automatically returns 'yes'.

        Args:
            thread_id: Optimizer Client ID (chat thread), used for looking up
                configuration (required)
            question: The user's question to grade against (required)
            documents: List of retrieved documents to grade (required)
            mcp_client: Name of the MCP client implementation being used
                (Default: Optimizer)
            model: Name and version of the language model being used (optional)

        Returns:
            Dictionary containing:
            - relevant: "yes" or "no" indicating if documents are relevant
            - formatted_documents: Documents formatted as concatenated string
                (if relevant)
            - grading_enabled: Whether grading was actually performed
            - num_documents: Number of documents evaluated
            - status: "success" or "error"
            - error: Error message if status is "error" (optional)
        """
        return await _vs_grade_impl(thread_id, question, documents, mcp_client, model)
