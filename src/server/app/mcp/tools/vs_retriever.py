"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

MCP tool: Vector Search Retriever.
"""
# spell-checker:ignore mult oraclevs vectorstores litellm acompletion fastmcp

import asyncio
import json
import logging
import traceback
from collections.abc import Coroutine
from typing import Any, Optional, cast

from fastmcp import Context
from langchain_oracledb import OracleVS
from litellm import acompletion
from litellm.types.utils import Choices, ModelResponse

from server.app.core.mcp import mcp
from server.app.core.settings import resolve_client
from server.app.mcp.prompts.registry import find_prompt
from server.app.models.litellm_utils import LiteLlmModelSpec, get_client_embed

from .schemas import VectorSearchResponse, VectorTable, get_database_pool, get_oci_profile
from .vs_discovery import _vs_discovery_impl

LOGGER = logging.getLogger(__name__)

TABLE_SELECTION_TEMPERATURE = 0.0
TABLE_SELECTION_MAX_TOKENS = 200
DEFAULT_MAX_TABLES = 3


async def _get_available_vector_stores(client: str = "CONFIGURED") -> list[VectorTable]:
    """Get available vector stores with enabled embedding models."""
    try:
        response = await _vs_discovery_impl(filter_enabled_models=True, client=client)
        if response.status != "success":
            LOGGER.error("Discovery failed: %s", response.error)
            return []
        return response.parsed_tables
    except Exception as ex:
        LOGGER.error("Failed to get available vector stores: %s", ex)
        return []


async def _select_tables_with_llm(
    question: str,
    available_tables: list[VectorTable],
    ll_config: dict,
    max_tables: int = DEFAULT_MAX_TABLES,
) -> list[str]:
    """Use LLM to select the most relevant vector stores for the question."""
    if not available_tables:
        return []

    if len(available_tables) == 1:
        return [available_tables[0].table_name]

    result = [available_tables[0].table_name]
    prompt_cfg = find_prompt("optimizer_vs-discovery")

    if prompt_cfg:
        prompt = prompt_cfg.text.format(
            tables_info="\n".join(
                "".join(
                    part
                    for part in (
                        f"- {table.table_name}",
                        f" (alias: {table.parsed.alias})" if table.parsed.alias else "",
                        f": {table.parsed.description}" if table.parsed.description else "",
                        (
                            f" [model: {table.parsed.embedding_model.provider}/{table.parsed.embedding_model.id}]"
                            if table.parsed.embedding_model
                            else ""
                        ),
                    )
                )
                for table in available_tables
            ),
            question=question,
            max_tables=max_tables,
        )

        try:
            response = cast(
                ModelResponse,
                await acompletion(
                    messages=[{"role": "user", "content": prompt}],
                    **{
                        **ll_config,
                        "temperature": TABLE_SELECTION_TEMPERATURE,
                        "max_tokens": TABLE_SELECTION_MAX_TOKENS,
                    },
                ),
            )

            selection_text = (cast(Choices, response.choices[0]).message.content or "[]").strip()
            LOGGER.info("LLM table selection response: %s", selection_text)

            selected_tables = json.loads(selection_text)
        except Exception as ex:
            LOGGER.error("Failed to select tables with LLM: %s", ex)
        else:
            if isinstance(selected_tables, list):
                valid_table_names = {t.table_name for t in available_tables}
                filtered_tables = [table for table in selected_tables if table in valid_table_names][:max_tables]
                if filtered_tables:
                    result = filtered_tables
                else:
                    LOGGER.warning("No valid tables selected, falling back to first table")
            else:
                LOGGER.warning("LLM returned non-list response, falling back to first table")
    else:
        LOGGER.warning("Table selection prompt not found; using first table")

    return result


def _deduplicate_documents(documents: list) -> list:
    """Deduplicate documents by content, keeping the highest-scoring version."""
    if not documents:
        return documents

    seen_content: dict[str, int] = {}
    deduplicated: list[dict] = []

    for doc in documents:
        content = doc.get("page_content", "")
        if content not in seen_content:
            seen_content[content] = len(deduplicated)
            deduplicated.append(doc)
        else:
            idx = seen_content[content]
            existing_score = deduplicated[idx].get("metadata", {}).get("similarity_score", 0)
            new_score = doc.get("metadata", {}).get("similarity_score", 0)
            if new_score > existing_score:
                deduplicated[idx] = doc

    LOGGER.info("Deduplicated %d to %d documents", len(documents), len(deduplicated))
    return deduplicated


async def _report_progress(ctx: Optional[Context], step: int, total: int) -> None:
    """Send progress updates when a context is available."""
    if ctx:
        await ctx.report_progress(step, total)


async def _search_tables(
    pool,
    tables_to_search: list[str],
    available_tables: list[VectorTable],
    question: str,
    oci_profile,
    vector_search,
    response: VectorSearchResponse,
) -> None:
    """Populate the response with documents from each selected table."""
    tables_by_name = {table.table_name: table for table in available_tables}

    # Phase 1: Pre-validate tables, build embedding client cache, prepare tasks.
    embed_cache: dict[tuple, object] = {}
    tasks: list[tuple[str, Coroutine[Any, Any, list[dict]]]] = []

    async def _run_search(tbl_name, embed_client, distance_strategy):
        """Acquire a dedicated connection and search one table."""
        async with pool.acquire() as table_conn:
            return await _search_table(
                tbl_name,
                question,
                table_conn,
                embed_client,
                vector_search,
                distance_strategy,
            )

    for table_name in tables_to_search:
        table_info = tables_by_name.get(table_name)
        if not table_info:
            LOGGER.warning("Selected table %s not discovered, skipping", table_name)
            response.failed_tables.append(table_name)
            continue

        if not table_info.parsed.embedding_model:
            LOGGER.warning("No embedding model for table %s, skipping", table_name)
            response.failed_tables.append(table_name)
            continue

        cache_key = (table_info.parsed.embedding_model.provider, table_info.parsed.embedding_model.id)
        if cache_key not in embed_cache:
            try:
                embed_cache[cache_key] = get_client_embed(table_info.parsed.embedding_model, oci_profile)
            except Exception:
                LOGGER.warning("Failed to create embed client for table %s, skipping", table_name)
                response.failed_tables.append(table_name)
                continue

        tasks.append(
            (
                table_name,
                _run_search(
                    table_name,
                    embed_cache[cache_key],
                    table_info.parsed.distance_strategy,
                ),
            )
        )

    if not tasks:
        return

    # Phase 2: Run all searches concurrently.
    results = await asyncio.gather(*(coro for _, coro in tasks), return_exceptions=True)

    # Phase 3: Merge results into response (single-threaded, no races).
    for (table_name, _), result in zip(tasks, results):
        if isinstance(result, BaseException):
            LOGGER.error(
                "Failed to search table %s: %s (type: %s)",
                table_name,
                str(result) if str(result) else repr(result),
                type(result).__name__,
            )
            LOGGER.debug(
                "Full traceback: %s",
                "".join(traceback.format_exception(type(result), result, result.__traceback__)),
            )
            response.failed_tables.append(table_name)
        else:
            response.documents.extend(result)
            response.searched_tables.append(table_name)


async def _search_table(
    table_name: str,
    question: str,
    async_conn,
    embed_client,
    vector_search,
    distance_strategy,
) -> list[dict]:
    """Search a single vector table using async OracleVS and return documents."""
    LOGGER.info("Searching table: %s with distance strategy: %s", table_name, distance_strategy)

    vectorstores = await OracleVS.acreate(
        client=async_conn,
        embedding_function=embed_client,
        table_name=table_name,
        distance_strategy=distance_strategy,
    )

    if vector_search.search_type == "Similarity":
        docs_and_scores = await vectorstores.asimilarity_search_with_score(question, k=vector_search.top_k)

        documents = []
        for doc, score in docs_and_scores:
            ds_name = distance_strategy.name if hasattr(distance_strategy, "name") else str(distance_strategy)
            if "COSINE" in ds_name.upper():
                similarity = 1.0 - (score / 2.0)
            elif "DOT" in ds_name.upper():
                similarity = score
            else:
                similarity = 1.0 / (1.0 + score)

            if vector_search.score_threshold > 0 and similarity < vector_search.score_threshold:
                continue

            metadata = doc.metadata if hasattr(doc, "metadata") else {}
            metadata["similarity_score"] = round(similarity, 3)
            metadata["searched_table"] = table_name
            documents.append({"page_content": doc.page_content, "metadata": metadata})
    elif vector_search.search_type == "Maximal Marginal Relevance":
        docs = await vectorstores.amax_marginal_relevance_search(
            question,
            k=vector_search.top_k,
            fetch_k=vector_search.fetch_k,
            lambda_mult=vector_search.lambda_mult,
        )
        documents = []
        for doc in docs:
            metadata = doc.metadata if hasattr(doc, "metadata") else {}
            metadata["searched_table"] = table_name
            documents.append({"page_content": doc.page_content, "metadata": metadata})
    else:
        docs = await vectorstores.asimilarity_search(question, k=vector_search.top_k)
        documents = []
        for doc in docs:
            metadata = doc.metadata if hasattr(doc, "metadata") else {}
            metadata["searched_table"] = table_name
            documents.append({"page_content": doc.page_content, "metadata": metadata})

    LOGGER.info("Retrieved %d documents from %s", len(documents), table_name)
    return documents


async def _vs_retrieve_impl(
    question: str,
    ctx: Optional[Context] = None,
    client: str = "CONFIGURED",
) -> VectorSearchResponse:
    """Smart vector search retriever with automatic table selection."""
    response = VectorSearchResponse(
        context_input=question,
        documents=[],
        num_documents=0,
        searched_tables=[],
        failed_tables=[],
        status="pending",
    )

    try:
        cs = resolve_client(client)
        vector_search = cs.vector_search
        oci_profile = get_oci_profile(client)

        await _report_progress(ctx, 1, 4)
        available_tables = await _get_available_vector_stores(client)
        if not available_tables:
            response.status = "error"
            response.error = "No vector stores available with enabled embedding models"
            return response

        await _report_progress(ctx, 2, 4)
        tables_to_search = await _select_tables_with_llm(
            question,
            available_tables,
            LiteLlmModelSpec.from_ll_model_settings(cs.ll_model, oci_profile).to_litellm_kwargs(),
        )
        LOGGER.info("Searching %d table(s): %s", len(tables_to_search), tables_to_search)

        await _report_progress(ctx, 3, 4)
        pool = get_database_pool(client)
        if not pool:
            response.status = "error"
            response.error = "No database connection pool available"
            return response

        await _search_tables(
            pool,
            tables_to_search,
            available_tables,
            question,
            oci_profile,
            vector_search,
            response,
        )

        await _report_progress(ctx, 4, 4)
        response.documents = _deduplicate_documents(response.documents)
        response.documents.sort(
            key=lambda d: d.get("metadata", {}).get("similarity_score", 0),
            reverse=True,
        )
        response.documents = response.documents[: vector_search.top_k]
        response.num_documents = len(response.documents)
        response.status = "success"

    except (AttributeError, KeyError, TypeError) as ex:
        LOGGER.error("Vector search failed: %s", ex)
        response.status = "error"
        response.error = f"Vector search failed: {ex}"
        return response

    LOGGER.info("Found %d documents from %d table(s)", len(response.documents), len(response.searched_tables))
    if response.failed_tables:
        LOGGER.warning("Failed to search %d table(s): %s", len(response.failed_tables), response.failed_tables)

    return response


def register_retriever_tool():
    """Register the VS retriever tool with FastMCP."""

    @mcp.tool(
        name="optimizer_vs-retriever",
        title="Vector Search Retriever",
        tags={"vector-search", "optimizer"},
        annotations={"readOnlyHint": True, "openWorldHint": True},
        timeout=60.0,
    )
    async def retriever(
        thread_id: str,
        question: str,
        ctx: Optional[Context] = None,
    ) -> VectorSearchResponse:
        """Search documentation using vector similarity. Returns relevant documents."""
        if ctx:
            await ctx.info(f"VS Retriever (Thread ID: {thread_id})")
        # WayFlow may pass the full RephrasePrompt JSON as the question string
        try:
            parsed = json.loads(question)
            if isinstance(parsed, dict) and "rephrased_prompt" in parsed:
                question = parsed["rephrased_prompt"]
        except (json.JSONDecodeError, TypeError):
            pass
        return await _vs_retrieve_impl(question, ctx, client=thread_id)
