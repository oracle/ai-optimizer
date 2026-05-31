"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP tool: Document Grading for vector search results.
"""
# spell-checker:ignore acompletion litellm fastmcp ainvoke

import json
import logging
from typing import Optional, Union

from fastmcp import Context
from litellm.exceptions import APIConnectionError

from server.app.core.mcp import mcp
from server.app.core.settings import resolve_client
from server.app.mcp.prompts.registry import find_prompt
from server.app.models.litellm_utils import LiteLlmModelSpec
from server.app.runtime.langgraph.adapters.litellm import ainvoke_text_from_spec

from .schemas import VectorGradeResponse, get_oci_profile

LOGGER = logging.getLogger(__name__)


def _format_documents(documents: list[dict]) -> str:
    """Extract and format document page content."""
    return "\n\n".join(doc["page_content"] for doc in documents if "page_content" in doc)


async def _grade_documents_with_llm(question: str, documents_str: str, spec: LiteLlmModelSpec) -> str:
    """Grade documents using LLM."""
    prompt_cfg = find_prompt("optimizer_vs-grade")
    if not prompt_cfg:
        LOGGER.warning("Grading prompt not found; assuming all results relevant")
        return "yes"

    grade_template = prompt_cfg.text
    formatted_prompt = grade_template.format(question=question, documents=documents_str)

    relevant = (await ainvoke_text_from_spec(spec, formatted_prompt)).lower()
    LOGGER.info("Grading completed. Relevant: %s", relevant)

    if "yes" in relevant:
        return "yes"
    if "no" in relevant:
        return "no"

    LOGGER.error("LLM did not return binary relevant in grader; assuming all results relevant.")
    return "yes"


async def _vs_grade_impl(
    question: str,
    documents: list[dict],
    client: str = "CONFIGURED",
) -> VectorGradeResponse:
    """Implementation of document grading."""
    try:
        cs = resolve_client(client)
        vector_search = cs.vector_search
        documents_str = _format_documents(documents)
        LOGGER.debug("Grading %d document(s):\n%s", len(documents), documents_str)
        relevant = "yes"
        grading_performed = False

        if vector_search.grade and documents:
            grading_performed = True
            oci_profile = get_oci_profile(client)
            spec = LiteLlmModelSpec.from_ll_model_settings(cs.ll_model, oci_profile)

            try:
                relevant = await _grade_documents_with_llm(question, documents_str, spec)
            except APIConnectionError as ex:
                LOGGER.error("Failed to grade; marking all results relevant: %s", ex)
                relevant = "yes"
        else:
            LOGGER.info("Vector Search Grading disabled; assuming all results relevant.")

        formatted_docs = documents_str if relevant == "yes" else ""

        return VectorGradeResponse(
            relevant=relevant,
            formatted_documents=formatted_docs,
            grading_performed=grading_performed,
            num_documents=len(documents),
            status="success",
        )
    except Exception as ex:
        LOGGER.error("Grading failed: %s", ex)
        return VectorGradeResponse(
            relevant="yes",
            formatted_documents="",
            grading_performed=False,
            num_documents=len(documents) if documents else 0,
            status="error",
            error=str(ex),
        )


def register_grade_tool():
    """Register the VS grade tool with FastMCP."""

    @mcp.tool(
        name="optimizer_vs_grade",
        title="Document Grading",
        tags={"vector-search", "optimizer"},
        annotations={"readOnlyHint": True, "openWorldHint": True},
        timeout=30.0,
    )
    async def grading(
        thread_id: str,
        question: str,
        documents: Union[list[dict], str],
        ctx: Optional[Context] = None,
    ) -> VectorGradeResponse:
        """Grade relevance of retrieved documents to the user's question."""
        if ctx:
            await ctx.info(f"VS Grade (Thread ID: {thread_id}, Docs: {len(documents)})")
        parsed_docs = json.loads(documents) if isinstance(documents, str) else documents
        if isinstance(parsed_docs, dict) and "documents" in parsed_docs:
            parsed_docs = parsed_docs["documents"]
        if not isinstance(parsed_docs, list):
            raise TypeError(f"Expected list of documents, got {type(parsed_docs)}")
        return await _vs_grade_impl(question, parsed_docs, client=thread_id)
