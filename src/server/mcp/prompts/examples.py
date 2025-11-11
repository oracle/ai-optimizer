"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

# pylint: disable=unused-argument
# spell-checker:ignore fastmcp
from fastmcp.prompts.prompt import PromptMessage, TextContent


# Basic prompt returning a string (converted to user message automatically)
async def register(mcp):
    """Register Out-of-Box Prompts"""
    optimizer_tags = {"source", "optimizer"}

    @mcp.prompt(name="optimizer_basic-default-chatbot", tags=optimizer_tags)
    def basic_default() -> PromptMessage:
        """Basic system prompt for chatbot."""

        content = "You are a friendly, helpful assistant."
        return PromptMessage(role="assistant", content=TextContent(type="text", text=content))

    @mcp.prompt(name="optimizer_vector-search-default", tags=optimizer_tags)
    def vector_search_default() -> PromptMessage:
        """Default Vector Search system prompt for chatbot."""

        content = """
            You are an assistant for question-answering tasks, be concise.
            Use the retrieved DOCUMENTS to answer the user input as accurately as possible.
            Keep your answer grounded in the facts of the DOCUMENTS and reference the DOCUMENTS where possible.
            If there ARE DOCUMENTS, you should be able to answer.
            If there are NO DOCUMENTS, respond only with 'I am sorry, but cannot find relevant sources.'
        """
        return PromptMessage(role="assistant", content=TextContent(type="text", text=content))

    @mcp.prompt(name="optimizer_vector-search-custom", tags=optimizer_tags)
    def vector_search_custom() -> PromptMessage:
        """Custom Vector Search system prompt for chatbot."""

        content = """
            You are an assistant for question-answering tasks.  Use the retrieved DOCUMENTS
            and history to answer the question.  If there are no DOCUMENTS or the DOCUMENTS
            do not contain the specific information, do your best to still answer.
        """
        return PromptMessage(role="assistant", content=TextContent(type="text", text=content))

    @mcp.prompt(name="optimizer_context-default", tags=optimizer_tags)
    def context_default() -> PromptMessage:
        """Default Context system prompt for vector search."""

        content = """
            Rephrase the latest user input into a standalone search query optimized for vector retrieval.
            Use only the user's prior inputs for context, ignoring system responses.
            Remove conversational elements like confirmations or clarifications, focusing solely on the core topic and keywords.
        """
        return PromptMessage(role="assistant", content=TextContent(type="text", text=content))

    @mcp.prompt(name="optimizer_context-custom", tags=optimizer_tags)
    def context_custom() -> PromptMessage:
        """Custom Context system prompt for vector search."""

        content = """
            Ignore chat history and context and do not reformulate the question. 
            DO NOT answer the question. Simply return the original query AS-IS.
        """
        return PromptMessage(role="assistant", content=TextContent(type="text", text=content))
