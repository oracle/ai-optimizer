"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore litellm fastmcp

from typing import Optional, List

from pydantic import BaseModel

from litellm import completion
from litellm.exceptions import APIConnectionError
from langchain_core.prompts import PromptTemplate
from fastmcp import Client

import server.api.core.settings as core_settings
import server.api.core.prompts as core_prompts
import server.api.utils.models as utils_models
import server.api.utils.oci as utils_oci

from common import logging_config

logger = logging_config.logging.getLogger("mcp.tools.rephrase")


class RephrasePrompt(BaseModel):
    """Response from the optimizer_rephrase tool"""

    original_prompt: str
    rephrased_prompt: str
    was_rephrased: bool
    status: str  # "success" or "error"
    error: Optional[str] = None


async def _get_prompt_content(mcp, user_ctx_prompt: str) -> Optional[str]:
    """Get prompt content from MCP or core prompts"""
    ctx_prompt_content = None

    # Try to get MCP prompt first
    if user_ctx_prompt.startswith("optimizer_"):
        try:
            client = Client(mcp)
            async with client:
                prompt_result = await client.get_prompt(name=user_ctx_prompt)
                # Extract text from the prompt messages
                if prompt_result.messages:
                    for message in prompt_result.messages:
                        if hasattr(message.content, "text"):
                            ctx_prompt_content = message.content.text
                            break
            await client.close()
            logger.info("Retrieved MCP prompt: %s", user_ctx_prompt)
        except Exception as ex:
            logger.warning(
                "Failed to get MCP prompt '%s', falling back to core prompts: %s",
                user_ctx_prompt,
                ex,
            )

    # Fall back to core prompts if MCP prompt not available
    if not ctx_prompt_content:
        ctx_prompt_obj = core_prompts.get_prompts(category="ctx", name=user_ctx_prompt)
        if ctx_prompt_obj:
            ctx_prompt_content = ctx_prompt_obj.prompt

    return ctx_prompt_content


async def _perform_rephrase(question: str, chat_history: List[str], ctx_prompt_content: str, ll_config: dict) -> str:
    """Perform the actual rephrasing using LLM"""
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
        input_variables=["prompt", "history", "question"],
    )
    formatted_prompt = rephrase_template.format(
        prompt=ctx_prompt_content,
        history=chat_history,
        question=question,
    )

    response = completion(
        messages=[{"role": "system", "content": formatted_prompt}],
        stream=False,
        **ll_config,
    )
    return response.choices[0].message.content


async def register(mcp, auth):
    """Invoke Registration of Context Rephrasing"""

    @mcp.tool(name="optimizer_rephrase")
    @auth.get("/rephrase", operation_id="rephrase")
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
            Dictionary containing:
            - original_question: The original user question
            - rephrased_question: The contextualized/rephrased question (may be
                same as original)
            - was_rephrased: Boolean indicating if the question was actually
                rephrased
            - status: "success" or "error"
            - error: Error message if status is "error" (optional)
        """
        try:
            logger.info(
                "Rephrasing question (Thread ID: %s, MCP: %s, Model: %s)",
                thread_id,
                mcp_client,
                model,
            )

            # Get client settings
            client_settings = core_settings.get_client_settings(thread_id)
            use_history = client_settings.ll_model.chat_history

            # Only rephrase if history is enabled and there's actual history
            if use_history and chat_history and len(chat_history) > 2:
                user_ctx_prompt = getattr(client_settings.prompts, "ctx", "Basic Example")

                # Get prompt content (MCP or core)
                ctx_prompt_content = await _get_prompt_content(mcp, user_ctx_prompt)

                if not ctx_prompt_content:
                    logger.warning("No context prompt found, skipping rephrase")
                    return RephrasePrompt(
                        original_prompt=question,
                        rephrased_prompt=question,
                        was_rephrased=False,
                        status="success",
                    )
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

            # No rephrasing occurred
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
