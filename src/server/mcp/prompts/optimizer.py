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

    @mcp.prompt(name="basic-example-chatbot", tags=optimizer_tags)
    def basic_example() -> PromptMessage:
        """Basic system prompt for chatbot."""

        content = "You are a friendly, helpful assistant."
        return PromptMessage(role="system", content=TextContent(type="text", text=content))
