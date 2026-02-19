"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore litellm fastmcp

from typing import Optional, List

from pydantic import BaseModel

from litellm import completion
from litellm.exceptions import APIConnectionError
from langchain_core.prompts import PromptTemplate

import server.api.utils.settings as utils_settings
import server.api.utils.models as utils_models
import server.api.utils.oci as utils_oci

import server.mcp.prompts.defaults as default_prompts

from common import logging_config

logger = logging_config.logging.getLogger("mcp.tools.rephrase")

# Configuration constants
MIN_CHAT_HISTORY_FOR_REPHRASE = 2  # Minimum chat messages needed to trigger rephrasing


class RephrasePrompt(BaseModel):
    """Response from the optimizer_rephrase tool"""

    original_prompt: str
    rephrased_prompt: str
    was_rephrased: bool
    status: str  # "success" or "error"
    error: Optional[str] = None


async def _perform_rephrase(question: str, chat_history: List[str], ctx_prompt_content: str, ll_config: dict) -> str:
    """Perform the actual rephrasing using LLM"""
    # Get rephrase prompt template from prompts module (checks cache for overrides)
    rephrase_prompt_msg = default_prompts.get_prompt_with_override("optimizer_vs-rephrase")
    rephrase_template_text = rephrase_prompt_msg.content.text

    # Format the template with actual values
    rephrase_template = PromptTemplate(
        template=rephrase_template_text,
        input_variables=["prompt", "history", "question"],
    )
    formatted_prompt = rephrase_template.format(
        prompt=ctx_prompt_content,
        history=chat_history,
        question=question,
    )

    response = completion(
        messages=[{"role": rephrase_prompt_msg.role, "content": formatted_prompt}],
        stream=False,
        **ll_config,
    )
    return response.choices[0].message.content


async def _vs_rephrase_impl(
    thread_id: str,
    question: str,
    chat_history: Optional[List[str]],
    mcp_client: str,
    model: str,
) -> RephrasePrompt:
    """Internal implementation for rephrasing questions

    Callable directly by graph orchestration without going through MCP tool layer.
    """
    try:
        logger.info(
            "Rephrasing question (Thread ID: %s, MCP: %s, Model: %s)",
            thread_id,
            mcp_client,
            model,
        )

        # Get client settings
        client_settings = utils_settings.get_client(thread_id)

        # Check if rephrasing is enabled in vector search settings
        if not client_settings.vector_search.rephrase:
            logger.info("Rephrasing disabled in vector search settings")
            return RephrasePrompt(
                original_prompt=question,
                rephrased_prompt=question,
                was_rephrased=False,
                status="success",
            )

        use_history = client_settings.ll_model.chat_history

        # Only rephrase if history is enabled and there's actual history
        if use_history and chat_history and len(chat_history) >= MIN_CHAT_HISTORY_FOR_REPHRASE:
            # Get context prompt (checks cache for overrides first)
            ctx_prompt_msg = default_prompts.get_prompt_with_override("optimizer_context-default")
            ctx_prompt_content = ctx_prompt_msg.content.text

            # Get LLM config
            oci_config = utils_oci.get(client=thread_id)
            ll_model = client_settings.ll_model.model_dump()
            ll_config = utils_models.get_litellm_config(ll_model, oci_config)

            try:
                rephrased = await _perform_rephrase(question, chat_history, ctx_prompt_content, ll_config)

                if rephrased != question:
                    logger.info("Rephrased: '%s' -> '%s'", question, rephrased)
                    return RephrasePrompt(
                        original_prompt=question,
                        rephrased_prompt=rephrased,
                        was_rephrased=True,
                        status="success",
                    )
            except APIConnectionError as ex:
                logger.error("Failed to rephrase: %s", str(ex))
                return RephrasePrompt(
                    original_prompt=question,
                    rephrased_prompt=question,
                    was_rephrased=False,
                    status="error",
                    error=f"API connection failed: {str(ex)}",
                )

        # No rephrasing needed or performed
        logger.info("No rephrasing needed or history insufficient")
        return RephrasePrompt(
            original_prompt=question,
            rephrased_prompt=question,
            was_rephrased=False,
            status="success",
        )

    except Exception as ex:
        logger.error("Rephrase failed: %s", ex)
        return RephrasePrompt(
            original_prompt=question,
            rephrased_prompt=question,
            was_rephrased=False,
            status="error",
            error=str(ex),
        )


async def register(mcp, auth):
    """Invoke Registration of Context Rephrasing"""

    @mcp.tool(name="optimizer_vs-rephrase")
    @auth.get("/vs_rephrase", operation_id="vs_rephrase", include_in_schema=False)
    async def rephrase(
        thread_id: str,
        question: str,
        chat_history: Optional[List[str]] = None,
        mcp_client: str = "Optimizer",
        model: str = "UNKNOWN-LLM",
    ) -> RephrasePrompt:
        """
        Rephrase user question using conversation history for better vector search retrieval.

        Takes a user's question and contextualizes it based on chat history to
        create a standalone search query optimized for vector retrieval. Uses the
        configured context prompt and LLM to reformulate the question.

        Args:
            thread_id: Optimizer Client ID (chat thread), used for looking up
                configuration (required)
            question: The user's question to be rephrased (required)
            chat_history: List of previous conversation messages for context
                (optional)
            mcp_client: Name of the MCP client implementation being used
                (Default: Optimizer)
            model: Name and version of the language model being used (optional)

        Returns:
            RephrasePrompt object containing:
            - original_prompt: The original user question
            - rephrased_prompt: The contextualized/rephrased question (may be
                same as original)
            - was_rephrased: Boolean indicating if the question was actually
                rephrased
            - status: "success" or "error"
            - error: Error message if status is "error" (optional)
        """
        # Delegate to internal implementation (allows graph orchestration to bypass MCP layer)
        return await _vs_rephrase_impl(thread_id, question, chat_history, mcp_client, model)
