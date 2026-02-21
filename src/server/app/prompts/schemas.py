"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for MCP prompt configuration.
"""

from pydantic import BaseModel, Field


class PromptConfig(BaseModel):
    """MCP Prompt metadata and content."""

    name: str = Field(..., description="MCP prompt name (e.g., 'optimizer_basic-default')")
    title: str = Field(..., description="Human-readable title")
    description: str = Field(default="", description="Prompt purpose and usage")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    text: str = Field(..., description="Effective prompt text (override if customized, otherwise default)")
    default_text: str = Field(default="", exclude=True, description="Code-provided default text")
    customized: bool = Field(default=False, description="True when the user has overridden the default text")
