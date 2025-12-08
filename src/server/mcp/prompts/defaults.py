"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore fastmcp giskard

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


def optimizer_vs_no_tools_default() -> PromptMessage:
    """Vector Search (no tools) system prompt for chatbot."""
    content = """
        You are a concise assistant for question-answering tasks.

        **Rules:**
        1. Base your response ONLY on the provided context. Do NOT use your own knowledge.
        2. Reference the source documents where possible.
        3. If no relevant context is provided, respond only with: "I could not find relevant information."
    """
    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


def optimizer_tools_default() -> PromptMessage:
    """
    Default system prompt with explicit tool selection guidance.
    Note: Smaller models will struggle with large prompts and tool calling. When
          considering changing this prompt, evaluate the impact on <8b models.
    """
    content = """
        You are a helpful assistant. Answer questions using the available tools.

        Tools:
        - optimizer_vs-retriever: Search documentation (recommendations, best practices, reference info)
        - sqlcl_*: Query database (current settings, live data, actual state)

        Use BOTH tools when comparing documentation against the database (e.g., recommendations vs actual state).

        Rules:
        - Answer using only the exact information from tool results
        - Do not add information that is not in the results
        - If results do not answer the question, say "I could not find relevant information."
    """
    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


def optimizer_context_default() -> PromptMessage:
    """
    Default Context system prompt for vector search.
    Note: Keep this prompt simple for smaller models (<8b parameters).
    """
    content = """
        Rephrase the user's question into a standalone search query optimized for documentation retrieval.

        Rules:
        - If the question uses "it", "this", "that", replace with the actual topic from history
        - If the question is about a new topic, ignore the history
        - Remove conversational words, keep technical terms
        - If the question is vague, expand with specific technical terms from the domain
        - Do not include specific version numbers - use general product names instead
        - Output only the rephrased query, nothing else

        Examples:
        - History: "Tell me about Python" + Question: "How do I install it?" → "How to install Python"
        - History: "Tell me about Python" + Question: "What is Java?" → "What is Java"
        - Question: "Any performance recommendations?" → "database performance tuning parameters memory PGA SGA optimization"
        - Question: "How do I make it faster?" → "performance optimization query tuning indexing best practices"
        - History: "Connected to Oracle 23.26" + Question: "any new features?" → "Oracle Database new features"
    """
    return PromptMessage(role="assistant", content=TextContent(type="text", text=clean_prompt_string(content)))


def optimizer_vs_discovery() -> PromptMessage:
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
        3. If no description exists, assess the relevance based on the alias
        4. Select up to {max_tables} stores
        5. Return ONLY the full TABLE NAMES (the part before any parenthesis/alias)

        Output format (JSON array only):
        ["FULL_TABLE_NAME_1", "FULL_TABLE_NAME_2"]

        Example valid output:
        ["VECTOR_USERS_OPENAI_TEXT_EMBEDDING_3_SMALL_1536_308_COSINE_HNSW"]

        Your JSON array:
    """

    return PromptMessage(role="user", content=TextContent(type="text", text=clean_prompt_string(content)))


def optimizer_vs_grade() -> PromptMessage:
    """Prompt for grading relevance of retrieved documents."""

    content = """
        Assess whether the retrieved documents contain information relevant to the question.

        Respond with ONLY 'yes' or 'no':
        - 'yes' if ANY document contains relevant information
        - 'no' if NO documents are relevant

        Question: {question}

        Documents: {documents}
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


def optimizer_testbed_judge() -> PromptMessage:
    """Prompt for testbed evaluation judge.

    Used to evaluate whether a chatbot's answer correctly matches the reference answer.
    This prompt allows additional context when the core answer is present, but strictly
    fails answers that are off-topic, missing essential information, or contradictory.
    """
    content = """
        You are evaluating whether an AI assistant correctly answered a question.

        CORRECT if:
        - The answer EXPLICITLY STATES the essential information from the EXPECTED ANSWER
        - Extra context, elaboration, or background is acceptable ONLY when the core answer is present

        INCORRECT if:
        - The essential information from the expected answer is MISSING or NOT STATED
        - The answer discusses a different topic or concept than what was asked
        - The answer contradicts or conflicts with the expected answer
        - The agent admits it cannot answer or asks for clarification

        IMPORTANT:
        - The core fact/value from the expected answer MUST appear in the agent's answer
        - Discussing related but different concepts is NOT correct
        - Vague or generic responses that don't include the specific answer are INCORRECT

        Examples:
        - Expected "The default is X" → Agent "The default is X. Previously Y." → CORRECT (core answer present)
        - Expected "The default is X" → Agent "The default is Y or Z depending on config." → INCORRECT (wrong value)
        - Expected "The default is X" → Agent "It depends on your setup." → INCORRECT (core answer missing)

        Output ONLY valid JSON:
        {"correctness": true}
        {"correctness": false, "correctness_reason": "brief explanation"}
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

    @mcp.prompt(name="optimizer_vs-no-tools-default", title="Vector Search (no tools) Prompt", tags=optimizer_tags)
    def vs_no_tools_default_mcp() -> PromptMessage:
        """Prompt for Vector Search without Tools.

        Used when no tools are enabled.
        """
        return get_prompt_with_override("optimizer_vs_no_tools_default")

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

    @mcp.prompt(name="optimizer_vs-discovery", title="Smart Vector Storage Prompt", tags=optimizer_tags)
    def table_selection_mcp() -> PromptMessage:
        """Prompt for LLM-based vector store table selection.

        Used by smart vector search retriever to select which tables to search
        based on table descriptions, aliases, and the user's question.
        """
        return get_prompt_with_override("optimizer_vs-discovery")

    @mcp.prompt(name="optimizer_vs-grade", title="Vector Search Grading Prompt", tags=optimizer_tags)
    def grading_mcp() -> PromptMessage:
        """Prompt for grading relevance of retrieved documents.

        Used by the vector search grading tool to assess whether retrieved documents
        are relevant to the user's question.
        """
        return get_prompt_with_override("optimizer_vs-grade")

    @mcp.prompt(name="optimizer_vs-rephrase", title="Vector Search Rephrase Prompt", tags=optimizer_tags)
    def rephrase_mcp() -> PromptMessage:
        """Prompt for rephrasing user query with conversation history context.

        Used by the vector search rephrase tool to contextualize the user's query
        based on conversation history before performing retrieval.
        """
        return get_prompt_with_override("optimizer_vs-rephrase")

    @mcp.prompt(name="optimizer_testbed-judge", title="Testbed Judge Prompt", tags=optimizer_tags)
    def testbed_judge_mcp() -> PromptMessage:
        """Prompt for testbed evaluation judge.

        Used by the testbed to evaluate whether the chatbot's answer matches the reference.
        Configurable to adjust evaluation strictness. The default prompt is lenient -
        it allows additional context in answers and only fails on contradictions or
        missing essential information.
        """
        return get_prompt_with_override("optimizer_testbed-judge")
