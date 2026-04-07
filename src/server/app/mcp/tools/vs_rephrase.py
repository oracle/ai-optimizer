"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP tool: Question Rephrase for vector search retrieval.
"""
# spell-checker:ignore acompletion litellm fastmcp

import json
import logging
from typing import Optional, Union, cast

from fastmcp import Context
from langchain_core.prompts import PromptTemplate
from litellm import acompletion
from litellm.exceptions import APIConnectionError
from litellm.types.utils import Choices, ModelResponse

from server.app.core.mcp import mcp
from server.app.core.settings import resolve_client
from server.app.mcp.prompts.registry import find_prompt
from server.app.models.litellm_utils import LiteLlmModelSpec

from .schemas import RephrasePrompt, get_oci_profile

LOGGER = logging.getLogger(__name__)

MIN_CHAT_HISTORY_FOR_REPHRASE = 2


async def _perform_rephrase(
    question: str,
    chat_history: Union[list[str], str],
    ctx_prompt_content: str,
    ll_config: dict,
) -> str:
    """Perform the actual rephrasing using LLM."""
    prompt_cfg = find_prompt("optimizer_vs-rephrase")
    if not prompt_cfg:
        LOGGER.warning("Rephrase prompt not found; returning original question")
        return question

    rephrase_template = PromptTemplate(
        template=prompt_cfg.text,
        input_variables=["prompt", "history", "question"],
    )
    formatted_prompt = rephrase_template.format(
        prompt=ctx_prompt_content,
        history=chat_history,
        question=question,
    )

    response = cast(
        ModelResponse,
        await acompletion(
            messages=[{"role": "user", "content": formatted_prompt}],
            stream=False,
            **ll_config,
        ),
    )
    choice = cast(Choices, response.choices[0])
    return choice.message.content or question


async def _vs_rephrase_impl(
    question: str,
    chat_history: Union[list[str], str, None],
    client: str = "CONFIGURED",
) -> RephrasePrompt:
    """Implementation of question rephrasing."""
    try:
        client_settings = resolve_client(client)

        if not client_settings.vector_search.rephrase:
            LOGGER.info("Rephrasing disabled in vector search settings")
            return RephrasePrompt(
                original_prompt=question,
                rephrased_prompt=question,
                was_rephrased=False,
                status="success",
            )

        use_history = client_settings.ll_model.chat_history

        # Normalize string history: try JSON first (MCP clients may send a list),
        # otherwise keep the plain string (WayFlow sends newline-delimited turns).
        if isinstance(chat_history, str):
            try:
                parsed = json.loads(chat_history)
                if isinstance(parsed, list):
                    chat_history = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        if use_history and chat_history:
            history_len = (
                len(chat_history)
                if isinstance(chat_history, list)
                else chat_history.count("User:") + chat_history.count("Assistant:")
            )
            if history_len >= MIN_CHAT_HISTORY_FOR_REPHRASE:
                ctx_prompt_cfg = find_prompt("optimizer_context-default")
                ctx_prompt_content = ctx_prompt_cfg.text if ctx_prompt_cfg else ""

                oci_profile = get_oci_profile(client)
                ll_config = LiteLlmModelSpec.from_ll_model_settings(
                    client_settings.ll_model, oci_profile
                ).to_litellm_kwargs()

                try:
                    rephrased = await _perform_rephrase(question, chat_history, ctx_prompt_content, ll_config)

                    if rephrased != question:
                        LOGGER.info("Rephrased: '%s' -> '%s'", question, rephrased)
                        return RephrasePrompt(
                            original_prompt=question,
                            rephrased_prompt=rephrased,
                            was_rephrased=True,
                            status="success",
                        )
                except APIConnectionError as ex:
                    LOGGER.error("Failed to rephrase: %s", ex)
                    return RephrasePrompt(
                        original_prompt=question,
                        rephrased_prompt=question,
                        was_rephrased=False,
                        status="error",
                        error=f"API connection failed: {ex}",
                    )

        LOGGER.info("No rephrasing needed or history insufficient")
        return RephrasePrompt(
            original_prompt=question,
            rephrased_prompt=question,
            was_rephrased=False,
            status="success",
        )
    except Exception as ex:
        LOGGER.error("Rephrase failed: %s", ex)
        return RephrasePrompt(
            original_prompt=question,
            rephrased_prompt=question,
            was_rephrased=False,
            status="error",
            error=str(ex),
        )


def register_rephrase_tool():
    """Register the VS rephrase tool with FastMCP."""

    @mcp.tool(
        name="optimizer_vs-rephrase",
        title="Question Rephrase",
        tags={"vector-search", "optimizer"},
        annotations={"readOnlyHint": True, "openWorldHint": True},
        timeout=30.0,
    )
    async def rephrase(
        thread_id: str,
        question: str,
        chat_history: Union[list[str], str, None] = None,
        ctx: Optional[Context] = None,
    ) -> RephrasePrompt:
        """Rephrase user question using conversation history for better vector search retrieval."""
        if ctx:
            await ctx.info(f"VS Rephrase (Thread ID: {thread_id})")
        return await _vs_rephrase_impl(question, chat_history, client=thread_id)
