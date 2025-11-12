"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# pylint: disable=unused-argument
# spell-checker:ignore fastmcp
from fastmcp.prompts.prompt import PromptMessage, TextContent
from server.mcp.prompts import cache


def clean_prompt_string(text):
    """Clean formatting of prompt"""
    lines = text.splitlines()[1:] if text.splitlines() and text.splitlines()[0].strip() == "" else text.splitlines()
    return "\n".join(line.strip() for line in lines)


# Module-level prompt functions (accessible for direct import)


def basic_completion() -> PromptMessage:
    """Basic system prompt for chatbot."""
    content = "You are a friendly, helpful assistant."
    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


def vector_search() -> PromptMessage:
    """Default Vector Search system prompt for chatbot."""
    content = """
        You are an assistant for question-answering tasks.
        
        You MUST use the optimizer_vs-retriever tool to search for information before answering any question.
        Once you have retrieved documents, use them to answer the user's question accurately and concisely.
        Keep your answer grounded in the facts of the retrieved documents.
        If the retrieved documents are not relevant, state that you cannot find relevant sources.
    """
    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


def context() -> PromptMessage:
    """Default Context system prompt for vector search."""
    content = """
        Rephrase the latest user input into a standalone search query optimized for vector retrieval.
        Use only the user's prior inputs for context, ignoring system responses.
        Remove conversational elements like confirmations or clarifications, focusing solely on the core topic and keywords.
    """
    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


def table_selection_default() -> PromptMessage:
    """Prompt for LLM-based vector store table selection."""

    content = """
        Select vector stores to search based on semantic relevance to the question.

        Available stores:
        {tables_info}

        Question: "{question}"

        Selection rules:
        1. When a store has a DESCRIPTION (after the colon), use it to judge relevance
        2. Prefer stores whose description relates to the question's topic
        3. If no description, use alias and document count as secondary signals
        4. Select up to {max_tables} stores
        5. Return ONLY a JSON array of full TABLE NAMES (before the alias)

        Format: ["FULL_TABLE_NAME_1", "FULL_TABLE_NAME_2"]

        Your selection:
    """

    return PromptMessage(role="user", content=TextContent(type="text", text=clean_prompt_string(content)))


# MCP Registration
async def register(mcp):
    """Register Out-of-Box Prompts"""
    optimizer_tags = {"source", "optimizer"}

    @mcp.prompt(name="optimizer_basic-default", title="Basic Prompt", tags=optimizer_tags)
    def basic_default_mcp() -> PromptMessage:
        """Prompt for basic completions.

        Used when no tools are enabled.
        """
        # Check for override first
        override = cache.get_override("optimizer_basic-default")
        if override:
            return PromptMessage(role="assistant", content=TextContent(type="text", text=override))
        return basic_completion()

    @mcp.prompt(name="optimizer_vector-search-default", title="Vector Search Prompt", tags=optimizer_tags)
    def vector_search_mcp() -> PromptMessage:
        """Vector Search Prompt.

        Used to invoke the Vector Search tool to keep answers grounded.
        """
        # Check for override first
        override = cache.get_override("optimizer_vector-search-default")
        if override:
            return PromptMessage(role="assistant", content=TextContent(type="text", text=override))
        return vector_search()

    @mcp.prompt(name="optimizer_context-default", title="Contextualize Prompt", tags=optimizer_tags)
    def context_default_mcp() -> PromptMessage:
        """Rephrase based on Context Prompt.

        Used before performing a Vector Search to ensure the user prompt
        is phrased in a way that will result in a relevant search based
        on the conversation context.
        """
        # Check for override first
        override = cache.get_override("optimizer_context-default")
        if override:
            return PromptMessage(role="assistant", content=TextContent(type="text", text=override))
        return context()

    @mcp.prompt(name="optimizer_vs-table-selection", title="Smart Vector Storage Prompt", tags=optimizer_tags)
    def table_selection_mcp() -> PromptMessage:
        """Prompt for LLM-based vector store table selection.

        Used by smart vector search retriever to select which tables to search
        based on table descriptions, aliases, and the user's question.
        """
        # Check for override first
        override = cache.get_override("optimizer_vs-table-selection")
        if override:
            return PromptMessage(role="user", content=TextContent(type="text", text=override))
        return table_selection_default()
