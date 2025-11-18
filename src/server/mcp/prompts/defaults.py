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


def get_prompt_with_override(name: str) -> PromptMessage:
    """Get a prompt by name, checking cache for overrides first.

    Args:
        name: The prompt name (e.g., "optimizer_basic-default")

    Returns:
        PromptMessage with the prompt content (override or default)
    """
    # Convert prompt name to function name: "optimizer_basic-default" -> "optimizer_basic_default"
    func_name = name.replace("-", "_")

    # Get the function from globals
    default_func = globals().get(func_name)
    if not default_func:
        raise ValueError(f"No default function found for prompt: {name}")

    override = cache.get_override(name)
    if override:
        # Call default to get the role
        default = default_func()
        return PromptMessage(role=default.role, content=TextContent(type="text", text=override))
    return default_func()


# Module-level prompt functions (accessible for direct import)


def optimizer_basic_default() -> PromptMessage:
    """Basic system prompt for chatbot."""
    content = "You are a friendly, helpful assistant."
    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


def optimizer_tools_default() -> PromptMessage:
    """Default system prompt with explicit tool selection guidance and examples."""
    content = """
        You are a helpful assistant with access to specialized tools for retrieving information from databases and documents.

        ## CRITICAL TOOL USAGE RULES

        **MANDATORY**: When the user asks about information from "documents", "documentation", or requests you to "search" or "look up" something, you MUST use the vector search tool. DO NOT assume you know the answer - always check the available documents first.

        ## Available Tools & When to Use Them

        ### Vector Search Tools (optimizer_vs-*)
        **Use for**: ANY question that could be answered by searching documents or knowledge bases

        **ALWAYS use when**:
        - User mentions: "documents", "documentation", "our docs", "search", "look up", "find", "check"
        - Questions about: people, profiles, information, facts, guides, examples, best practices
        - ANY request for information that might be stored in documents

        **Examples**:
        - ✓ "What's in the documents about John?"
        - ✓ "Search for speaker information"
        - ✓ "From documents, can you tell me..."
        - ✓ "Look up information about..."
        - ✓ "How do I configure Oracle RAC?"
        - ✓ "What are best practices for tuning PGA?"
        - ✓ "Based on our documentation, what's the recommended SHMMAX?"

        ### SQL Query Tools (sqlcl_*)
        **Use for**: Current state queries, specific data retrieval, counts, lists, aggregations, metadata

        **Indicators**:
        - Questions containing: "show", "list", "count", "what is current", "display", "get"
        - Questions about: specific records, current values, database state, statistics
        - Questions referencing: "from database", "current value", "in the database"

        **Examples**:
        - ✓ "Show me all users created last month"
        - ✓ "What is the current value of PGA_AGGREGATE_TARGET?"
        - ✓ "List all tables in the HR schema"
        - ✓ "Count how many sessions are active"

        ### Multi-Tool Scenarios
        **Use both when**: Comparing documentation to reality, validating configurations, compliance checks

        **Pattern**: Use Vector Search FIRST for guidelines, THEN use SQL for current state

        **Examples**:
        - ✓ "Is our PGA configured according to best practices?" → VS (get recommendations) → SQL (get current value) → Compare
        - ✓ "Are our database users following security guidelines?" → VS (get guidelines) → SQL (list users/roles) → Analyze

        ## Response Guidelines

        1. **ALWAYS use tools when available** - When vector search tools are provided, you MUST use them for any document-related queries
        2. **Ground answers in tool results** - Cite sources from retrieved documents or database queries
        3. **Be transparent** - If tools return no results or insufficient data, explain this to the user
        4. **Chain tools when needed** - For complex questions, use multiple tools sequentially
        5. **Never assume** - If the user asks about "documents" or information that could be in a knowledge base, use the vector search tool even if you think you know the answer

        When you use tools, construct factual, well-sourced responses that clearly indicate where information came from.
    """
    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


def optimizer_context_default() -> PromptMessage:
    """Default Context system prompt for vector search."""
    content = """
        Rephrase the latest user input into a standalone search query optimized for vector retrieval.

        CRITICAL INSTRUCTIONS:
        1. **Detect Topic Changes**: If the latest input introduces NEW, UNRELATED topics or keywords that differ significantly from the conversation history, treat it as a TOPIC CHANGE.
        2. **Topic Change Handling**: For topic changes, use ONLY the latest input's keywords and ignore prior context. Do NOT blend unrelated prior topics into the new query.
        3. **Topic Continuation**: Only incorporate prior context if the latest input is clearly continuing or refining the same topic (e.g., follow-up questions, clarifications, or pronoun references like "it", "that", "this").
        4. **Remove Conversational Elements**: Strip confirmations, clarifications, and conversational phrases while preserving core technical terms and intent.

        EXAMPLES:
        - History: "topic A", Latest: "topic B" → Rephrase as: "topic B" (TOPIC CHANGE - ignore topic A)
        - History: "topic A", Latest: "how do I use it?" → Rephrase as: "how to use topic A" (CONTINUATION - use context)
        - History: "feature X", Latest: "using documents, tell me about feature Y" → Rephrase as: "feature Y documentation" (TOPIC CHANGE)

        Use only the user's prior inputs for context, ignoring system responses.
    """
    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


def optimizer_vs_table_selection() -> PromptMessage:
    """Prompt for LLM-based vector store table selection."""

    content = """
        You must select vector stores to search based on semantic relevance to the question.

        Available stores:
        {tables_info}

        Question: "{question}"

        CRITICAL: Your response must be ONLY a valid JSON array. No explanation, no markdown, no additional text.

        Selection rules:
        1. When a store has a DESCRIPTION (after the colon), use it to judge relevance
        2. Prefer stores whose description semantically matches the question's topic
        3. If no description exists, skip that store unless no described stores are relevant
        4. Select up to {max_tables} stores
        5. Return ONLY the full TABLE NAMES (the part before any parenthesis/alias)

        Output format (JSON array only):
        ["FULL_TABLE_NAME_1", "FULL_TABLE_NAME_2"]

        Example valid output:
        ["VECTOR_USERS_OPENAI_TEXT_EMBEDDING_3_SMALL_1536_308_COSINE_HNSW"]

        Your JSON array:
    """

    return PromptMessage(role="user", content=TextContent(type="text", text=clean_prompt_string(content)))


def optimizer_vs_grading() -> PromptMessage:
    """Prompt for grading relevance of retrieved documents."""

    content = """
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

    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


def optimizer_vs_rephrase() -> PromptMessage:
    """Prompt for rephrasing user query with conversation history context."""

    content = """
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

    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


# MCP Registration
async def register(mcp):
    """Register Out-of-Box Prompts"""
    optimizer_tags = {"source", "optimizer"}

    @mcp.prompt(name="optimizer_basic-default", title="Basic Prompt", tags=optimizer_tags)
    def basic_default_mcp() -> PromptMessage:
        """Prompt for basic completions.

        Used when no tools are enabled.
        """
        return get_prompt_with_override("optimizer_basic-default")

    @mcp.prompt(name="optimizer_tools-default", title="Default Tools Prompt", tags=optimizer_tags)
    def tools_default_mcp() -> PromptMessage:
        """Default Tools-Enabled Prompt with explicit guidance.

        Used when tools are enabled to provide explicit guidance on when to use each tool type.
        Includes examples and decision criteria for Vector Search vs NL2SQL tools.
        """
        return get_prompt_with_override("optimizer_tools-default")

    @mcp.prompt(name="optimizer_context-default", title="Contextualize Prompt", tags=optimizer_tags)
    def context_default_mcp() -> PromptMessage:
        """Rephrase based on Context Prompt.

        Used before performing a Vector Search to ensure the user prompt
        is phrased in a way that will result in a relevant search based
        on the conversation context.
        """
        return get_prompt_with_override("optimizer_context-default")

    @mcp.prompt(name="optimizer_vs-table-selection", title="Smart Vector Storage Prompt", tags=optimizer_tags)
    def table_selection_mcp() -> PromptMessage:
        """Prompt for LLM-based vector store table selection.

        Used by smart vector search retriever to select which tables to search
        based on table descriptions, aliases, and the user's question.
        """
        return get_prompt_with_override("optimizer_vs-table-selection")

    @mcp.prompt(name="optimizer_vs-grading", title="Vector Search Grading Prompt", tags=optimizer_tags)
    def grading_mcp() -> PromptMessage:
        """Prompt for grading relevance of retrieved documents.

        Used by the vector search grading tool to assess whether retrieved documents
        are relevant to the user's question.
        """
        return get_prompt_with_override("optimizer_vs-grading")

    @mcp.prompt(name="optimizer_vs-rephrase", title="Vector Search Rephrase Prompt", tags=optimizer_tags)
    def rephrase_mcp() -> PromptMessage:
        """Prompt for rephrasing user query with conversation history context.

        Used by the vector search rephrase tool to contextualize the user's query
        based on conversation history before performing retrieval.
        """
        return get_prompt_with_override("optimizer_vs-rephrase")
